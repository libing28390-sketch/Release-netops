import sys
import os

# --- CRITICAL WINDOWS FIX ---
# This MUST happen before ANY other imports (especially fastapi/uvicorn)
if sys.platform == 'win32':
    import asyncio
    try:
        # Force ProactorEventLoop to bypass the 64 file descriptor limit in select()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass
# ----------------------------
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.config import settings
from core.textfsm import configure_ntc_templates
from core.logging import setup_logging
from api.health import router as health_router, record_host_resource_snapshot
from api.devices import router as devices_router
from api.jobs import router as jobs_router
from api.templates import router as templates_router
from api.automation import router as automation_router
from api.users import router as users_router
from api.topology import router as topology_router, discover_lldp_neighbors
from api.configs import router as configs_router, run_scheduled_backup, _get_schedule_from_db, reschedule_backup
from api.playbooks import router as playbooks_router
from services import notification_service
from services import alert_maintenance_service
from services import alert_rule_service
from services.device_health_service import record_device_health_snapshot
from api.notifications import router as notifications_router
from api.monitoring import router as monitoring_router
from api.device_health import router as device_health_router
from api.alerts import router as alerts_router
from api.audit import router as audit_router
from api.compliance import router as compliance_router
from api.config_drift import router as config_drift_router
from api.capacity import router as capacity_router
from api.reports import router as reports_router
from api.ipam import router as ipam_router
from api.assets import router as assets_router
from api.pam import router as pam_router, ws_router as pam_ws_router
from api.change_orders import router as change_orders_router
from api.setup import router as setup_router
from api.ip_locator import router as ip_locator_router
from api.inspections import router as inspections_router
from api.textfsm_templates import router as textfsm_templates_router
from api.tags import router as tags_router
from api.scheduled_jobs import router as scheduled_jobs_router
from api.racks import router as racks_router
from license_auth.api import router as license_router
from api.system import router as system_router
from api.access import router as access_router
from license_auth.middleware import LicenseMiddleware
from license_auth.verifier import get_license_verifier, bootstrap_license_protection
from services.scheduler_service import sync_scheduler_jobs, run_scheduled_automation_job_sync_wrapper
from engine.orchestrator import get_telemetry_orchestrator
import logging
import os
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib import request as urlrequest
from urllib import error as urlerror
from ping3 import ping
from database import DB_PATH, init_db, get_db_connection, _USE_PG
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from core.scheduler_manager import scheduler, refresh_dynamic_scheduler
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# SNMP Imports removed for stability


# 初始化日志配置
setup_logging()
logger = logging.getLogger(__name__) 

# ── Startup ──

async def _bg_init():
    """
    Background initialization to avoid blocking startup.
    """
    try:
        # Sync dynamic scheduled jobs from database
        sync_scheduler_jobs(scheduler)
        # Start status monitor loops (A/B Loops)
        telemetry_orch = get_telemetry_orchestrator()
        telemetry_orch.start_loops()
        logger.info("[Background] Core background tasks initialized.")
    except Exception as e:
        logger.error(f"[Background] Initialization failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    logger.info(f"Starting up {settings.PROJECT_NAME} in {settings.ENVIRONMENT} mode...")
    
    # Initialize Database once
    init_db()
    try:
        seed_data()
        logger.info("Database seeding successfully checked/completed.")
    except Exception as e:
        logger.error(f"Database seeding failed: {e}", exc_info=True)
    
    # ── One-time PAM stale-session recovery ──
    # After a server restart, sessions that were 'active' or 'connecting'
    # are orphaned (no WebSocket is alive for them). Close them once here.
    try:
        from api.pam import recover_stale_sessions_on_startup
        recover_stale_sessions_on_startup()
    except Exception as e:
        logger.warning(f"[PAM] Stale session recovery failed: {e}")

    # License validation at startup
    _lic = get_license_verifier()
    _lic.load()
    _lic_status = _lic.validate(force=True)
    if _lic_status.valid:
        logger.info(f"[License] [OK] Valid - {_lic_status.company} ({_lic_status.license_type}), "
                     f"expires in {_lic_status.days_remaining}d, "
                     f"devices: {_lic_status.device_limit}")
    
    # Start core components immediately
    schedule_cfg = _get_schedule_from_db()
    scheduler.start()
    
    # Register periodic jobs
    scheduler.add_job(record_host_resource_snapshot, 'interval', minutes=1, id='host_resource_sampler', replace_existing=True)
    scheduler.add_job(record_device_health_snapshot, 'interval', minutes=1, id='device_health_sampler', replace_existing=True)
    
    reschedule_backup(schedule_cfg)
    
    from services.ip_locator_service import run_arp_sweep, ARP_SWEEP_INTERVAL_SECONDS
    scheduler.add_job(run_arp_sweep, 'interval', seconds=ARP_SWEEP_INTERVAL_SECONDS, id='arp_cache_sweep', replace_existing=True)
    
    from services.inspection_service import run_scheduled_inspections
    scheduler.add_job(run_scheduled_inspections, CronTrigger(minute='0,30'), id='inspection_scheduler', replace_existing=True)
    
    from services.password_rotation_service import run_rotation_sweep
    scheduler.add_job(run_rotation_sweep, CronTrigger(hour=2, minute=0), id='password_rotation_sweep', replace_existing=True)

    # Launch background tasks
    asyncio.create_task(_bg_init())
    logger.info("[Scheduler] APScheduler started (background init pending)")

    yield
    # ── shutdown ──
    try:
        from engine.orchestrator import get_telemetry_orchestrator
        telemetry_orch = get_telemetry_orchestrator()
        telemetry_orch.stop_loops()
        logger.info("[Background] Telemetry loops stopped")
    except Exception as e:
        logger.warning(f"[Background] Failed to stop telemetry loops: {e}")

    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] APScheduler stopped")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部异常，请联系管理员查看后端日志"},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

# CORS - restrict to known origins in production; permissive in dev
_cors_origins = ["*"] if os.environ.get("NODE_ENV") == "development" else [
    f"http://localhost:{os.environ.get('PORT', '9010')}",
    f"http://127.0.0.1:{os.environ.get('PORT', '9010')}",
]
# In production, set CORS_ORIGINS env var to a comma-separated list of allowed origins
_env_origins = os.environ.get("CORS_ORIGINS", "").strip()
if _env_origins:
    _cors_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# 注册路由
# ── 无需 License 的基础路由 ──
app.include_router(health_router,        prefix="/api")
app.include_router(users_router,         prefix="/api")
app.include_router(setup_router,         prefix="/api")
app.include_router(license_router,       prefix="/api")
app.include_router(system_router,        prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(tags_router,          prefix="/api")

# ── 需要 License 但不限定具体 feature 的路由（设备基础操作）──
from fastapi import Depends
from license_auth.middleware import require_license
_lic = [Depends(require_license)]

app.include_router(devices_router,       prefix="/api", dependencies=_lic)
app.include_router(jobs_router,          prefix="/api", dependencies=_lic)
app.include_router(templates_router,     prefix="/api", dependencies=_lic)
app.include_router(assets_router,        prefix="/api", dependencies=_lic)
app.include_router(racks_router,         prefix="/api", dependencies=_lic)
app.include_router(ip_locator_router,    prefix="/api", dependencies=_lic)
app.include_router(device_health_router, prefix="/api", dependencies=_lic)
app.include_router(access_router,        prefix="/api", dependencies=_lic)

# ── Feature-gated 路由：每个路由绑定对应的 License feature ──
from license_auth.middleware import require_feature

app.include_router(automation_router,     prefix="/api", dependencies=[Depends(require_feature("automation"))])
app.include_router(playbooks_router,      prefix="/api", dependencies=[Depends(require_feature("automation"))])
app.include_router(scheduled_jobs_router, prefix="/api", dependencies=[Depends(require_feature("scheduled_jobs"))])
app.include_router(configs_router,        prefix="/api", dependencies=[Depends(require_feature("config_management"))])
app.include_router(config_drift_router,   prefix="/api", dependencies=[Depends(require_feature("config_management"))])
app.include_router(monitoring_router,     prefix="/api", dependencies=[Depends(require_feature("monitoring"))])
app.include_router(alerts_router,         prefix="/api", dependencies=[Depends(require_feature("alerting"))])
app.include_router(topology_router,       prefix="/api", dependencies=[Depends(require_feature("topology"))])
app.include_router(ipam_router,           prefix="/api", dependencies=[Depends(require_feature("ipam"))])
app.include_router(capacity_router,       prefix="/api", dependencies=[Depends(require_feature("capacity"))])
app.include_router(reports_router,        prefix="/api", dependencies=[Depends(require_feature("reports"))])
app.include_router(compliance_router,     prefix="/api", dependencies=[Depends(require_feature("compliance"))])
app.include_router(inspections_router,    prefix="/api", dependencies=[Depends(require_feature("inspections"))])
app.include_router(textfsm_templates_router, prefix="/api", dependencies=[Depends(require_feature("inspections"))])
app.include_router(change_orders_router,  prefix="/api", dependencies=[Depends(require_feature("change_orders"))])
app.include_router(pam_router,            prefix="/api", dependencies=[Depends(require_feature("access_center"))])
app.include_router(audit_router,          prefix="/api", dependencies=[Depends(require_feature("rbac"))])
# PAM WebSocket 单独注册，不带 feature 依赖（token 本身即凭证）
app.include_router(pam_ws_router,         prefix="/api")

# ── License Middleware (after CORS) ──────────────
# bootstrap_license_protection() 在编译后的 .so 内部强制注册中间件并建立完整性基线。
# 即使此行被删除，.so 内部的逻辑仍会在 import 时触发保护。
import os as _os
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
bootstrap_license_protection(app, project_root=_PROJECT_ROOT)

# ── APScheduler ──────────────────────────────────────────────────────
# scheduler is now imported from core.scheduler_manager

def _daily_db_maintenance():
    """Clean expired sessions, vacuum database."""
    conn = get_db_connection()
    try:
        import time
        cutoff = time.time() - 28800  # 8 hours session TTL
        conn.execute('DELETE FROM sessions WHERE created_at < ?', (cutoff,))
        conn.execute('DELETE FROM login_failures WHERE locked_until > 0 AND locked_until < ?', (time.time() - 86400,))
        conn.commit()
    finally:
        conn.close()
    # VACUUM is SQLite-only maintenance; PG handles this via autovacuum
    if not _USE_PG:
        conn2 = get_db_connection()
        try:
            conn2.execute('VACUUM')
        except Exception as e:
            logger.warning(f"VACUUM failed: {e}")
        finally:
            conn2.close()
    logger.info("[Maintenance] Daily DB maintenance completed")


# Serve static files from backend/static for downloads
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static_bin")

# Serve static files from dist directory if it exists
if os.path.exists("dist"):
    logger.info("Serving static files from dist directory")
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")
else:
    logger.warning("dist directory not found. Frontend will not be served.")

def seed_data():
    from database import _USE_PG
    if not _USE_PG and not os.path.exists(DB_PATH):
        return
    conn = get_db_connection()
    
    try:
        # Check if devices table is empty
        count = conn.execute('SELECT COUNT(*) as count FROM devices').fetchone()['count']
        if count == 0:
            import uuid
            conn.execute('INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, cpu_usage, memory_usage, snmp_community, role, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (str(uuid.uuid4()), 'Core-SW-01', '192.168.1.1', 'cisco_ios', 'online', 'compliant', 'admin', 'admin', 12, 45, 'public', 'Core', 'HQ'))
            conn.execute('INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, cpu_usage, memory_usage, snmp_community, role, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (str(uuid.uuid4()), 'Edge-RTR-02', '10.0.0.5', 'juniper_junos', 'online', 'non-compliant', 'admin', 'admin', 28, 62, 'public', 'Edge', 'Branch-A'))
            conn.execute('INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, cpu_usage, memory_usage, snmp_community, role, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (str(uuid.uuid4()), 'Access-SW-01', '10.0.0.10', 'cisco_ios', 'online', 'compliant', 'admin', 'admin', 15, 30, 'public', 'Access', 'HQ'))
            conn.execute('INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, cpu_usage, memory_usage, snmp_community, role, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (str(uuid.uuid4()), 'Access-SW-02', '10.0.0.11', 'cisco_ios', 'online', 'compliant', 'admin', 'admin', 18, 35, 'public', 'Access', 'HQ'))
            conn.execute('INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, cpu_usage, memory_usage, snmp_community, role, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (str(uuid.uuid4()), 'Mock-Device-01', '127.0.0.1', 'cisco_ios', 'online', 'compliant', 'test', 'test', 5, 20, 'public', 'Test', 'Lab'))
        
        # Check if users table is empty - only insert default admin if no users exist
        count = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
        if count == 0:
            import bcrypt as _bcrypt
            _hashed_default = _bcrypt.hashpw('admin'.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')
            conn.execute('INSERT INTO users (id, username, password, role, status, last_login) VALUES (?, ?, ?, ?, ?, ?)',
                         ('1', 'admin', _hashed_default, 'Administrator', 'active', 'Never'))
        
        # Check if templates table is empty
        count = conn.execute('SELECT COUNT(*) as count FROM templates').fetchone()['count']
        if count == 0:
            import uuid
            from datetime import datetime
            now = datetime.now().isoformat()
            templates = [
                (str(uuid.uuid4()), 'Basic SSH Setup', 'cli', 'security', 'Cisco', 
                 'ip domain-name {{ domain_name | default("local.net") }}\ncrypto key generate rsa modulus {{ key_size | default(2048) }}\nip ssh version 2\nline vty 0 4\n transport input ssh\n login local', 
                 'no ip domain-name {{ domain_name | default("local.net") }}\ncrypto key zeroize rsa\nline vty 0 4\n transport input all\n no login local', now),
                (str(uuid.uuid4()), 'Standard ACL', 'cli', 'security', 'Cisco', 
                 'access-list {{ acl_number | default(10) }} permit {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\naccess-list {{ acl_number | default(10) }} deny any\ninterface {{ interface_name | default("GigabitEthernet0/1") }}\n ip access-group {{ acl_number | default(10) }} in', 
                 'interface {{ interface_name | default("GigabitEthernet0/1") }}\n no ip access-group {{ acl_number | default(10) }} in\nno access-list {{ acl_number | default(10) }}', now),
                (str(uuid.uuid4()), 'BGP Configuration', 'cli', 'routing', 'Cisco', 
                 'router bgp {{ local_as | default(65000) }}\n bgp router-id {{ router_id | default("10.0.0.1") }}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n network {{ network_ip | default("192.168.1.0") }} mask {{ network_mask | default("255.255.255.0") }}', 
                 'no router bgp {{ local_as | default(65000) }}', now),
                (str(uuid.uuid4()), 'OSPF Single Area', 'cli', 'routing', 'Cisco', 
                 'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }} area {{ area_id | default(0) }}', 
                 'no router ospf {{ ospf_process_id | default(1) }}', now),
                (str(uuid.uuid4()), 'VLAN Creation', 'cli', 'switching', 'Cisco', 
                 'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}', 
                 'no vlan {{ vlan_id | default(10) }}', now),
                
                (str(uuid.uuid4()), 'Basic SSH Setup', 'cli', 'security', 'Juniper', 
                 'set system services ssh root-login {{ root_login | default("deny") }}\nset system services ssh protocol-version v2', 
                 'delete system services ssh', now),
                (str(uuid.uuid4()), 'Firewall Filter (ACL)', 'cli', 'security', 'Juniper', 
                 'set firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 from source-address {{ source_network | default("192.168.1.0/24") }}\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 then accept\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 2 then reject', 
                 'delete firewall family inet filter {{ filter_name | default("PROTECT") }}', now),
                (str(uuid.uuid4()), 'BGP Configuration', 'cli', 'routing', 'Juniper', 
                 'set routing-options autonomous-system {{ local_as | default(65000) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} type external\nset protocols bgp group {{ group_name | default("EXTERNAL") }} peer-as {{ peer_as | default(65001) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} neighbor {{ peer_ip | default("10.0.0.2") }}', 
                 'delete protocols bgp group {{ group_name | default("EXTERNAL") }}\ndelete routing-options autonomous-system {{ local_as | default(65000) }}', now),
                (str(uuid.uuid4()), 'OSPF Single Area', 'cli', 'routing', 'Juniper', 
                 'set protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}', 
                 'delete protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}', now),
                (str(uuid.uuid4()), 'VLAN Creation', 'cli', 'switching', 'Juniper', 
                 'set vlans {{ vlan_name | default("USERS") }} vlan-id {{ vlan_id | default(10) }}', 
                 'delete vlans {{ vlan_name | default("USERS") }}', now),

                (str(uuid.uuid4()), 'Basic SSH Setup', 'cli', 'security', 'Huawei', 
                 'rsa local-key-pair create {{ key_size | default(2048) }}\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh', 
                 'rsa local-key-pair destroy', now),
                (str(uuid.uuid4()), 'Basic ACL', 'cli', 'security', 'Huawei', 
                 'acl number {{ acl_number | default(2000) }}\n rule 5 permit source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\n rule 10 deny', 
                 'undo acl {{ acl_number | default(2000) }}', now),
                (str(uuid.uuid4()), 'BGP Configuration', 'cli', 'routing', 'Huawei', 
                 'bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n peer {{ peer_ip | default("10.0.0.2") }} as-number {{ peer_as | default(65001) }}\n ipv4-family unicast\n  peer {{ peer_ip | default("10.0.0.2") }} enable\n  network {{ network_ip | default("192.168.1.0") }} {{ network_mask | default("255.255.255.0") }}', 
                 'undo bgp {{ local_as | default(65000) }}', now),
                (str(uuid.uuid4()), 'OSPF Single Area', 'cli', 'routing', 'Huawei', 
                 'ospf {{ ospf_process_id | default(1) }} router-id {{ router_id | default("10.0.0.1") }}\n area {{ area_id | default("0.0.0.0") }}\n  network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }}', 
                 'undo ospf {{ ospf_process_id | default(1) }}', now),
                (str(uuid.uuid4()), 'VLAN Creation', 'cli', 'switching', 'Huawei', 
                 'vlan {{ vlan_id | default(10) }}\n description Created_by_NetOps', 
                 'undo vlan {{ vlan_id | default(10) }}', now),

                (str(uuid.uuid4()), 'Basic SSH Setup', 'cli', 'security', 'Arista', 
                 'management ssh\n server-port {{ ssh_port | default(22) }}\n no shutdown', 
                 'management ssh\n shutdown', now),
                (str(uuid.uuid4()), 'Standard ACL', 'cli', 'security', 'Arista', 
                 'ip access-list standard {{ acl_name | default("PROTECT") }}\n permit {{ source_network | default("192.168.1.0/24") }}\n deny any', 
                 'no ip access-list standard {{ acl_name | default("PROTECT") }}', now),
                (str(uuid.uuid4()), 'BGP Configuration', 'cli', 'routing', 'Arista', 
                 'router bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n network {{ network_ip | default("192.168.1.0/24") }}', 
                 'no router bgp {{ local_as | default(65000) }}', now),
                (str(uuid.uuid4()), 'OSPF Single Area', 'cli', 'routing', 'Arista', 
                 'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0/24") }} area {{ area_id | default("0.0.0.0") }}', 
                 'no router ospf {{ ospf_process_id | default(1) }}', now),
                (str(uuid.uuid4()), 'VLAN Creation', 'cli', 'switching', 'Arista', 
                 'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}', 
                 'no vlan {{ vlan_id | default(10) }}', now)
            ]
            conn.executemany('INSERT INTO templates (id, name, type, category, vendor, content, rollback, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', templates)
        else:
            # Update existing templates in existing database to add Jinja2 variables
            updates = [
                # Cisco
                ('Basic SSH Setup', 'Cisco', 
                 'ip domain-name {{ domain_name | default("local.net") }}\ncrypto key generate rsa modulus {{ key_size | default(2048) }}\nip ssh version 2\nline vty 0 4\n transport input ssh\n login local',
                 'no ip domain-name {{ domain_name | default("local.net") }}\ncrypto key zeroize rsa\nline vty 0 4\n transport input all\n no login local'),
                ('Standard ACL', 'Cisco',
                 'access-list {{ acl_number | default(10) }} permit {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\naccess-list {{ acl_number | default(10) }} deny any\ninterface {{ interface_name | default("GigabitEthernet0/1") }}\n ip access-group {{ acl_number | default(10) }} in',
                 'interface {{ interface_name | default("GigabitEthernet0/1") }}\n no ip access-group {{ acl_number | default(10) }} in\nno access-list {{ acl_number | default(10) }}'),
                ('BGP Configuration', 'Cisco',
                 'router bgp {{ local_as | default(65000) }}\n bgp router-id {{ router_id | default("10.0.0.1") }}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n network {{ network_ip | default("192.168.1.0") }} mask {{ network_mask | default("255.255.255.0") }}',
                 'no router bgp {{ local_as | default(65000) }}'),
                ('OSPF Single Area', 'Cisco',
                 'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }} area {{ area_id | default(0) }}',
                 'no router ospf {{ ospf_process_id | default(1) }}'),
                ('VLAN Creation', 'Cisco',
                 'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}',
                 'no vlan {{ vlan_id | default(10) }}'),
                # Juniper
                ('Basic SSH Setup', 'Juniper',
                 'set system services ssh root-login {{ root_login | default("deny") }}\nset system services ssh protocol-version v2',
                 'delete system services ssh'),
                ('Firewall Filter (ACL)', 'Juniper',
                 'set firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 from source-address {{ source_network | default("192.168.1.0/24") }}\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 then accept\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 2 then reject',
                 'delete firewall family inet filter {{ filter_name | default("PROTECT") }}'),
                ('BGP Configuration', 'Juniper',
                 'set routing-options autonomous-system {{ local_as | default(65000) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} type external\nset protocols bgp group {{ group_name | default("EXTERNAL") }} peer-as {{ peer_as | default(65001) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} neighbor {{ peer_ip | default("10.0.0.2") }}',
                 'delete protocols bgp group {{ group_name | default("EXTERNAL") }}\ndelete routing-options autonomous-system {{ local_as | default(65000) }}'),
                ('OSPF Single Area', 'Juniper',
                 'set protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}',
                 'delete protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}'),
                ('VLAN Creation', 'Juniper',
                 'set vlans {{ vlan_name | default("USERS") }} vlan-id {{ vlan_id | default(10) }}',
                 'delete vlans {{ vlan_name | default("USERS") }}'),
                # Huawei
                ('Basic SSH Setup', 'Huawei',
                 'rsa local-key-pair create {{ key_size | default(2048) }}\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh',
                 'rsa local-key-pair destroy'),
                ('Basic ACL', 'Huawei',
                 'acl number {{ acl_number | default(2000) }}\n rule 5 permit source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\n rule 10 deny',
                 'undo acl {{ acl_number | default(2000) }}'),
                ('BGP Configuration', 'Huawei',
                 'bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n peer {{ peer_ip | default("10.0.0.2") }} as-number {{ peer_as | default(65001) }}\n ipv4-family unicast\n  peer {{ peer_ip | default("10.0.0.2") }} enable\n  network {{ network_ip | default("192.168.1.0") }} {{ network_mask | default("255.255.255.0") }}',
                 'undo bgp {{ local_as | default(65000) }}'),
                ('OSPF Single Area', 'Huawei',
                 'ospf {{ ospf_process_id | default(1) }} router-id {{ router_id | default("10.0.0.1") }}\n area {{ area_id | default("0.0.0.0") }}\n  network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }}',
                 'undo ospf {{ ospf_process_id | default(1) }}'),
                ('VLAN Creation', 'Huawei',
                 'vlan {{ vlan_id | default(10) }}\n description Created_by_NetOps',
                 'undo vlan {{ vlan_id | default(10) }}'),
                # Arista
                ('Basic SSH Setup', 'Arista',
                 'management ssh\n server-port {{ ssh_port | default(22) }}\n no shutdown',
                 'management ssh\n shutdown'),
                ('Standard ACL', 'Arista',
                 'ip access-list standard {{ acl_name | default("PROTECT") }}\n permit {{ source_network | default("192.168.1.0/24") }}\n deny any',
                 'no ip access-list standard {{ acl_name | default("PROTECT") }}'),
                ('BGP Configuration', 'Arista',
                 'router bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n network {{ network_ip | default("192.168.1.0/24") }}',
                 'no router bgp {{ local_as | default(65000) }}'),
                ('OSPF Single Area', 'Arista',
                 'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0/24") }} area {{ area_id | default("0.0.0.0") }}',
                 'no router ospf {{ ospf_process_id | default(1) }}'),
                ('VLAN Creation', 'Arista',
                 'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}',
                 'no vlan {{ vlan_id | default(10) }}')
            ]
            for name, vendor, content, rollback in updates:
                conn.execute('UPDATE templates SET content = ?, rollback = ? WHERE name = ? AND vendor = ?', (content, rollback, name, vendor))

        # ── Seed Device Types & Demo Racks ──
        dt_count = conn.execute('SELECT COUNT(*) as count FROM device_types').fetchone()['count']
        if dt_count == 0:
            import uuid
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            device_types = [
                # id, model, vendor, u_height, device_role, is_full_depth, description, created_at, updated_at
                (str(uuid.uuid4()), 'Catalyst 9300',     'Cisco',   1, 'switch',   1, '48-port L3 access switch', now, now),
                (str(uuid.uuid4()), 'Catalyst 9500',     'Cisco',   1, 'switch',   1, '32-port 100G core switch', now, now),
                (str(uuid.uuid4()), 'Nexus 9332C',       'Cisco',   1, 'switch',   1, '32x100G spine switch', now, now),
                (str(uuid.uuid4()), 'Nexus 9508',        'Cisco',  13, 'switch',   1, 'Modular chassis switch', now, now),
                (str(uuid.uuid4()), 'ISR 4451',          'Cisco',   2, 'router',   1, 'Branch router', now, now),
                (str(uuid.uuid4()), 'ASR 1001-X',        'Cisco',   1, 'router',   1, 'WAN aggregation router', now, now),
                (str(uuid.uuid4()), 'Firepower 2130',    'Cisco',   1, 'firewall', 1, 'Next-gen firewall', now, now),
                (str(uuid.uuid4()), 'S5735-L48T4S',      'Huawei',  1, 'switch',   1, '48-port access switch', now, now),
                (str(uuid.uuid4()), 'CE6881-48S6CQ',     'Huawei',  1, 'switch',   1, '25G datacenter switch', now, now),
                (str(uuid.uuid4()), 'USG6555E',          'Huawei',  1, 'firewall', 1, 'Enterprise firewall', now, now),
                (str(uuid.uuid4()), 'S6850-56HF',        'H3C',     1, 'switch',   1, '25G datacenter TOR switch', now, now),
                (str(uuid.uuid4()), 'PowerEdge R650',    'Dell',    1, 'server',   1, '1U rack server', now, now),
                (str(uuid.uuid4()), 'PowerEdge R750',    'Dell',    2, 'server',   1, '2U rack server', now, now),
                (str(uuid.uuid4()), 'ProLiant DL380 G10','HPE',     2, 'server',   1, '2U rack server', now, now),
                (str(uuid.uuid4()), 'ThinkSystem SR650', 'Lenovo',  2, 'server',   1, '2U rack server', now, now),
                (str(uuid.uuid4()), 'Patch Panel 24P',   'Generic', 1, 'patch_panel', 0, '24-port Cat6 patch panel', now, now),
                (str(uuid.uuid4()), 'APC SUA3000RMI2U',  'APC',     2, 'ups',      1, 'Smart-UPS 3000 RM', now, now),
            ]
            conn.executemany(
                'INSERT INTO device_types (id, model, vendor, u_height, device_role, is_full_depth, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                device_types
            )

        # Seed demo racks if empty
        rack_count = conn.execute('SELECT COUNT(*) as count FROM racks').fetchone()['count']
        if rack_count == 0:
            import uuid
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            demo_racks = [
                (str(uuid.uuid4()), 'A-01', 'DC-Beijing', 'Server Room 1', 'A', 42, 'Core network rack', 'active', now, now),
                (str(uuid.uuid4()), 'A-02', 'DC-Beijing', 'Server Room 1', 'A', 42, 'Server rack', 'active', now, now),
                (str(uuid.uuid4()), 'B-01', 'DC-Shanghai', 'Server Room 2', 'B', 42, 'Distribution rack', 'active', now, now),
            ]
            conn.executemany(
                'INSERT INTO racks (id, name, datacenter, room, row, total_u, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                demo_racks
            )

            # Seed demo devices into first rack
            dt_rows = conn.execute("SELECT id, model, u_height FROM device_types").fetchall()
            dt_map = {r['model'] if hasattr(r, '__getitem__') else r[1]: (r['id'] if hasattr(r, '__getitem__') else r[0], r['u_height'] if hasattr(r, '__getitem__') else r[2]) for r in dt_rows}
            rack_a01_id = demo_racks[0][0]
            rack_a02_id = demo_racks[1][0]

            demo_devices = []
            # Rack A-01: Network rack
            if 'Patch Panel 24P' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'PP-A01-01', rack_a01_id, dt_map['Patch Panel 24P'][0], 1, 'front', 'active', '', '', now, now))
            if 'Catalyst 9300' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'Core-SW-01', rack_a01_id, dt_map['Catalyst 9300'][0], 2, 'front', 'active', '', '', now, now))
                demo_devices.append((str(uuid.uuid4()), 'Core-SW-02', rack_a01_id, dt_map['Catalyst 9300'][0], 3, 'front', 'active', '', '', now, now))
            if 'Catalyst 9500' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'Dist-SW-01', rack_a01_id, dt_map['Catalyst 9500'][0], 5, 'front', 'active', '', '', now, now))
            if 'ISR 4451' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'Edge-RTR-01', rack_a01_id, dt_map['ISR 4451'][0], 7, 'front', 'active', '', '', now, now))
            if 'Firepower 2130' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'FW-01', rack_a01_id, dt_map['Firepower 2130'][0], 10, 'front', 'active', '', '', now, now))
            if 'APC SUA3000RMI2U' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'UPS-A01', rack_a01_id, dt_map['APC SUA3000RMI2U'][0], 41, 'front', 'active', '', '', now, now))

            # Rack A-02: Server rack
            if 'Patch Panel 24P' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'PP-A02-01', rack_a02_id, dt_map['Patch Panel 24P'][0], 1, 'front', 'active', '', '', now, now))
            if 'S5735-L48T4S' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'TOR-SW-01', rack_a02_id, dt_map['S5735-L48T4S'][0], 2, 'front', 'active', '', '', now, now))
            if 'PowerEdge R650' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'SRV-Web-01', rack_a02_id, dt_map['PowerEdge R650'][0], 4, 'front', 'active', '', '', now, now))
                demo_devices.append((str(uuid.uuid4()), 'SRV-Web-02', rack_a02_id, dt_map['PowerEdge R650'][0], 5, 'front', 'active', '', '', now, now))
            if 'PowerEdge R750' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'SRV-DB-01', rack_a02_id, dt_map['PowerEdge R750'][0], 7, 'front', 'active', '', '', now, now))
            if 'ProLiant DL380 G10' in dt_map:
                demo_devices.append((str(uuid.uuid4()), 'SRV-App-01', rack_a02_id, dt_map['ProLiant DL380 G10'][0], 10, 'front', 'active', '', '', now, now))
                demo_devices.append((str(uuid.uuid4()), 'SRV-App-02', rack_a02_id, dt_map['ProLiant DL380 G10'][0], 12, 'front', 'active', '', '', now, now))

            if demo_devices:
                conn.executemany(
                    'INSERT INTO rack_devices (id, name, rack_id, device_type_id, start_u, position, status, serial_number, asset_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    demo_devices
                )

        # Update/Seed hardware parameters for specific devices
        conn.execute('''
            UPDATE devices 
            SET ports_count = 48, ports_bandwidth_gbps = 88.0, switching_capacity_gbps = 176.0 
            WHERE hostname = 'cisco-sw1' OR ip_address = '192.168.18.201'
        ''')
        conn.execute('''
            UPDATE devices 
            SET ports_count = 24, ports_bandwidth_gbps = 44.0, switching_capacity_gbps = 88.0 
            WHERE hostname = 'cisco-sw2' OR ip_address = '192.168.18.202'
        ''')
        conn.execute('''
            UPDATE devices 
            SET ports_count = 2, ports_bandwidth_gbps = 20.0, switching_capacity_gbps = 40.0 
            WHERE hostname = 'ubuntu-server-jp2' OR ip_address = '3.112.222.158'
        ''')
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    import sys
    import os

    # Re-enforce Proactor on Windows before uvicorn starts
    if sys.platform == 'win32':
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    port = int(os.environ.get("PORT", "9010"))
    workers = int(os.environ.get("WORKERS", "1"))
    is_dev = os.environ.get("NODE_ENV") == "development"

    # On modern uvicorn versions, loop must be one of: auto/asyncio/uvloop/none.
    # Windows Proactor is already enforced via event loop policy above.
    loop_type = "asyncio" if sys.platform == "win32" else "auto"

    # Windows 热重载方案：
    #   uvicorn 原生 reload 在 Windows 下会让子进程回退到 select() 事件循环，
    #   触发 64 个 FD 上限崩溃，因此禁用。
    #   替代方案：使用 uvicorn 的 reload_dirs + watchfiles 后端（需安装 watchfiles）。
    #   watchfiles 在 Windows 下使用 ReadDirectoryChangesW API，不依赖 select()，
    #   且不会 fork 子进程，避免了 FD 限制问题。
    if is_dev and sys.platform == 'win32':
        try:
            import watchfiles  # noqa: F401 — 仅检测是否已安装
            effective_reload = True
            reload_kwargs = {
                'reload': True,
                'reload_dirs': [str(os.path.dirname(os.path.abspath(__file__)))],
                'reload_excludes': ['*.pyc', '__pycache__', '*.db', '*.log'],
            }
        except ImportError:
            # watchfiles 未安装，回退到禁用 reload（安全模式）
            # 安装方法：pip install watchfiles
            effective_reload = False
            reload_kwargs = {}
    elif is_dev:
        effective_reload = True
        reload_kwargs = {'reload': True}
    else:
        effective_reload = False
        reload_kwargs = {}

    if workers > 1:
        uvicorn.run("main:app", host="0.0.0.0", port=port, workers=workers, loop=loop_type)
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=port, loop=loop_type, **reload_kwargs)

# Reloader validation check comment

