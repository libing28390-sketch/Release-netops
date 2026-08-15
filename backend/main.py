import sys
import os

# Prevent writing .pyc files in development mode to avoid triggering watchfiles reload loops
if os.environ.get("NODE_ENV") == "development":
    sys.dont_write_bytecode = True

# Add backend directory to sys.path to resolve core, api, services, etc.
# SOCKS proxy support initialized
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --- CRITICAL WINDOWS FIX ---
# This MUST happen before ANY other imports (especially fastapi/uvicorn)
if sys.platform == 'win32':
    import asyncio
    try:
        # Force ProactorEventLoop to bypass the 64 file descriptor limit in select()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass
# Ensure proper MIME type mapping for static files on Windows (prevents white screen)
import mimetypes
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
# ----------------------------
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from core.config import settings
from core.textfsm import configure_ntc_templates
from core.logging import setup_logging, classify_request_log_level
from api.health import router as health_router, record_host_resource_snapshot
from api.devices import router as devices_router
from api.jobs import router as jobs_router
from api.templates import router as templates_router
from api.config_templates import router as config_templates_router
from api.automation import router as automation_router
from api.users import router as users_router
from api.topology import router as topology_router
from api.configs import router as configs_router, run_scheduled_backup, _get_schedule_from_db, reschedule_backup
from api.config_backup_policies import router as config_backup_policies_router
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
from api.config_search import router as config_search_router
from api.config_diff_analysis import router as config_diff_analysis_router
from api.capacity import router as capacity_router
from api.reports import router as reports_router
from api.ipam import router as ipam_router
from api.assets import router as assets_router
from api.pam import router as pam_router, ws_router as pam_ws_router
from api.pam_web import router as pam_web_router
from api.change_orders import router as change_orders_router
from api.setup import router as setup_router
from api.ip_locator import router as ip_locator_router
from api.inspections import router as inspections_router
from api.collection_plans import router as collection_plans_router
from api.textfsm_templates import router as textfsm_templates_router
from api.parser_templates import router as parser_templates_router
from api.platform_registry import router as platform_registry_router, device_registry_router
from api.knowledge_sources import router as knowledge_sources_router
from api.knowledge_documents import router as knowledge_documents_router
from api.knowledge_catalog import router as knowledge_catalog_router
from api.knowledge_collections import router as knowledge_collections_router
from api.knowledge_ingestion import router as knowledge_ingestion_router
from api.tags import router as tags_router
from api.scheduled_jobs import router as scheduled_jobs_router
from api.racks import router as racks_router
from api.credentials import router as credentials_router
from api.cmdb import router as cmdb_router
from api.interfaces import router as interfaces_router
from api.discovery import router as discovery_router
from api.graph import router as graph_router
from api.system import router as system_router
from api.access import router as access_router
from ai.api import ai_router
from ai.gateway.exceptions import AIException
from ai.api.chat_v1 import router as ai_v1_chat_router
from ai.api.security import load_persisted_security_policy
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
    load_persisted_security_policy()
    try:
        seed_data()
        logger.info("Database seeding successfully checked/completed.")
    except Exception as e:
        logger.error(f"Database seeding failed: {e}", exc_info=True)

    # Backfill the evidence-first knowledge graph from existing normalized
    # topology observations.  Discovery runs call the same projection after
    # every rebuild; startup makes already-collected evidence visible on
    # installations upgraded after the graph tables were introduced.
    try:
        from services.topology_service import _sync_evidence_graph_from_observations
        _sync_evidence_graph_from_observations()
        logger.info("[Topology] Evidence graph projection synchronized.")
    except Exception as e:
        logger.warning(f"[Topology] Evidence graph projection skipped: {e}")
    
    # ── One-time PAM stale-session recovery ──
    # After a server restart, sessions that were 'active' or 'connecting'
    # are orphaned (no WebSocket is alive for them). Close them once here.
    try:
        from api.pam import recover_stale_sessions_on_startup
        recover_stale_sessions_on_startup()
    except Exception as e:
        logger.warning(f"[PAM] Stale session recovery failed: {e}")


    
    arp_worker_tasks = []

    # Start core components immediately
    schedule_cfg = _get_schedule_from_db()
    scheduler.start()
    
    # Register periodic jobs
    scheduler.add_job(
        synchronized_scheduler_job('host_resource_sampler', expire_seconds=55)(record_host_resource_snapshot),
        'interval', minutes=1, id='host_resource_sampler', replace_existing=True
    )
    scheduler.add_job(
        synchronized_scheduler_job('device_health_sampler', expire_seconds=55)(record_device_health_snapshot),
        'interval', minutes=1, id='device_health_sampler', replace_existing=True
    )

    # ING-018: periodically revalidate active Knowledge Engine sources using
    # server-owned ETag/Last-Modified validators.  The scheduler lock keeps
    # multiple application instances from refreshing the same batch; the
    # service itself remains tenant-scoped and fail-closed per source.
    from services.source_freshness_service import (
        REFRESH_INTERVAL_MINUTES,
        run_scheduled_source_freshness_refresh,
    )
    scheduler.add_job(
        synchronized_scheduler_job('knowledge_source_freshness_refresh', expire_seconds=(REFRESH_INTERVAL_MINUTES * 60) - 5)(
            run_scheduled_source_freshness_refresh
        ),
        'interval', minutes=REFRESH_INTERVAL_MINUTES,
        id='knowledge_source_freshness_refresh', replace_existing=True,
        max_instances=1, coalesce=True,
    )

    # Read-only database consistency and orphan patrol.  The job is bounded,
    # never repairs rows, and is protected by the same cross-instance lock as
    # the other maintenance jobs.  Findings are logged as counts/fingerprints
    # only; operators use an approved migration or reconciliation action for
    # any repair.
    from database.consistency import run_scheduled_consistency_patrol
    scheduler.add_job(
        synchronized_scheduler_job('database_consistency_patrol', expire_seconds=23 * 3600)(
            run_scheduled_consistency_patrol
        ),
        'cron', hour=2, minute=25, id='database_consistency_patrol', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    
    from services.telemetry_service import record_device_telemetry_snapshot
    scheduler.add_job(
        synchronized_scheduler_job('device_telemetry_sampler', expire_seconds=55)(record_device_telemetry_snapshot),
        'interval', minutes=1, id='device_telemetry_sampler', replace_existing=True
    )

    from services.playbook_output_service import cleanup_expired_playbook_outputs
    scheduler.add_job(
        synchronized_scheduler_job('playbook_output_retention', expire_seconds=23 * 3600)(cleanup_expired_playbook_outputs),
        'cron', hour=3, minute=40, id='playbook_output_retention', replace_existing=True,
        max_instances=1, coalesce=True,
    )

    from services.outbound_probe_service import record_outbound_egress_snapshot, run_outbound_probe_once
    scheduler.add_job(
        synchronized_scheduler_job('outbound_probe_sampler', expire_seconds=55)(run_outbound_probe_once),
        'interval', minutes=1, id='outbound_probe_sampler', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('outbound_egress_sampler', expire_seconds=290)(record_outbound_egress_snapshot),
        'interval', minutes=5, id='outbound_egress_sampler', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    from services.wan_link_service import run_wan_collection_once
    scheduler.add_job(
        synchronized_scheduler_job('wan_link_sampler', expire_seconds=55)(run_wan_collection_once),
        'interval', seconds=60, id='wan_link_sampler', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    from services.wan_p1_service import apply_wan_retention_once, ensure_wan_partitions_once, rollup_wan_samples_once
    scheduler.add_job(synchronized_scheduler_job('wan_partition_maintenance', expire_seconds=900)(ensure_wan_partitions_once), 'cron', hour=2, minute=10, id='wan_partition_maintenance', replace_existing=True)
    scheduler.add_job(
        synchronized_scheduler_job('wan_rollup', expire_seconds=240)(rollup_wan_samples_once),
        'interval', minutes=5, id='wan_rollup', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('wan_retention', expire_seconds=900)(apply_wan_retention_once),
        'cron', hour=3, minute=20, id='wan_retention', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    from services.wan_p2_service import build_capacity_recommendations, calculate_wan_baselines, recompute_wan_correlations
    scheduler.add_job(
        synchronized_scheduler_job('wan_correlations', expire_seconds=240)(recompute_wan_correlations),
        'interval', minutes=5, id='wan_correlations', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('wan_baselines', expire_seconds=900)(calculate_wan_baselines),
        'cron', hour=2, minute=40, id='wan_baselines', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('wan_capacity', expire_seconds=900)(build_capacity_recommendations),
        'cron', hour=4, minute=10, id='wan_capacity', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    
    reschedule_backup(schedule_cfg)
    
    from services.ip_locator_service import (
        dispatch_arp_sweep,
        run_endpoint_fact_collector,
        run_route_collector,
        ARP_SWEEP_INTERVAL_SECONDS,
        ENDPOINT_FACT_INTERVAL_SECONDS,
        ROUTE_SWEEP_INTERVAL_SECONDS,
    )
    from services.collector_worker_service import start_arp_worker_tasks, stop_worker_tasks
    arp_worker_tasks = await start_arp_worker_tasks()
    scheduler.add_job(
        synchronized_scheduler_job('arp_cache_sweep', expire_seconds=int(ARP_SWEEP_INTERVAL_SECONDS - 1))(dispatch_arp_sweep),
        'interval', seconds=ARP_SWEEP_INTERVAL_SECONDS, id='arp_cache_sweep', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('endpoint_fact_sync', expire_seconds=int(ENDPOINT_FACT_INTERVAL_SECONDS - 1))(run_endpoint_fact_collector),
        'interval', seconds=ENDPOINT_FACT_INTERVAL_SECONDS, id='endpoint_fact_sync', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('route_cache_sweep', expire_seconds=int(ROUTE_SWEEP_INTERVAL_SECONDS - 1))(run_route_collector),
        'interval', seconds=ROUTE_SWEEP_INTERVAL_SECONDS, id='route_cache_sweep', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    
    from services.scheduler_service import sync_topology_and_interfaces_job, poll_endpoints_job, sync_routing_neighbors_job, sync_bgp_routes_job
    from services.topology_service import TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS
    from services.prefix_discovery_service import run_prefix_discovery_job
    scheduler.add_job(
        synchronized_scheduler_job(
            'topology_interface_sync',
            expire_seconds=max(30, TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS - 10),
        )(sync_topology_and_interfaces_job),
        'interval', seconds=TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS,
        id='topology_interface_sync', replace_existing=True
    )
    scheduler.add_job(
        synchronized_scheduler_job(
            'prefix_discovery_sync',
            expire_seconds=max(30, TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS - 10),
        )(run_prefix_discovery_job),
        'interval', seconds=TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS,
        id='prefix_discovery_sync', replace_existing=True,
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        synchronized_scheduler_job('poll_endpoints', expire_seconds=290)(poll_endpoints_job),
        'interval', minutes=5, id='poll_endpoints', replace_existing=True
    )
    scheduler.add_job(
        synchronized_scheduler_job('routing_neighbors_sync', expire_seconds=290)(sync_routing_neighbors_job),
        'interval', minutes=5, id='routing_neighbors_sync', replace_existing=True
    )
    scheduler.add_job(
        synchronized_scheduler_job('bgp_routes_sync', expire_seconds=290)(sync_bgp_routes_job),
        'interval', minutes=5, id='bgp_routes_sync', replace_existing=True
    )
    
    from services.inspection_service import run_scheduled_inspections
    try:
        inspection_trigger = CronTrigger.from_crontab(settings.INSPECTION_MASTER_CRON)
    except Exception:
        logger.warning(
            "Invalid INSPECTION_MASTER_CRON=%r; falling back to twice-daily 02:30/14:30",
            settings.INSPECTION_MASTER_CRON,
        )
        inspection_trigger = CronTrigger(minute=30, hour='2,14')
    scheduler.add_job(
        synchronized_scheduler_job('inspection_scheduler', expire_seconds=1700)(run_scheduled_inspections),
        inspection_trigger, id='inspection_scheduler', replace_existing=True
    )
    
    # Do not register a daily no-op when credential rotation is disabled. This
    # keeps the scheduler registry aligned with the features actually enabled
    # for the deployment while preserving the job when the feature is on.
    if settings.PASSWORD_ROTATION_ENABLED:
        from services.password_rotation_service import run_rotation_sweep
        scheduler.add_job(
            synchronized_scheduler_job('password_rotation_sweep', expire_seconds=3600)(run_rotation_sweep),
            CronTrigger(hour=2, minute=0), id='password_rotation_sweep', replace_existing=True
        )
    else:
        logger.info("[Scheduler] Password rotation sweep disabled by configuration")

    # Launch background tasks
    asyncio.create_task(_bg_init())
    logger.info("[Scheduler] APScheduler started (background init pending)")

    yield
    # ── shutdown ──
    try:
        await stop_worker_tasks(arp_worker_tasks)
        logger.info("[ARP Workers] Worker tasks stopped")
    except Exception as e:
        logger.warning(f"[ARP Workers] Failed to stop worker tasks: {e}")
    try:
        from engine.orchestrator import get_telemetry_orchestrator
        telemetry_orch = get_telemetry_orchestrator()
        telemetry_orch.stop_loops()
        logger.info("[Background] Telemetry loops stopped")
    except Exception as e:
        logger.warning(f"[Background] Failed to stop telemetry loops: {e}")

    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] APScheduler stopped")

from core.context import request_id_var, user_var, route_var
from core.metrics import metrics_registry
from core.scheduler_lock import synchronized_scheduler_job
import time

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

@app.middleware("http")
async def add_request_id_and_log(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    req_token = request_id_var.set(request_id)
    user_token = user_var.set("anonymous")
    route_token = route_var.set(request.url.path)
    
    auth_start_time = time.perf_counter()
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth.replace('Bearer ', '')
        if token:
            try:
                from api.users import validate_session_token
                user = validate_session_token(token)
                if user and user.get('username'):
                    user_var.set(user['username'])
            except Exception:
                pass
    auth_duration_ms = (time.perf_counter() - auth_start_time) * 1000
    handler_start_time = time.perf_counter()
    try:
        response = await call_next(request)
        handler_duration_ms = (time.perf_counter() - handler_start_time) * 1000
        duration_ms = (time.perf_counter() - start_time) * 1000
        metrics_registry.record_api_latency(duration_ms)
        request_log_level = classify_request_log_level(response.status_code, duration_ms)
        logger.log(
            request_log_level,
            f"Route: {request.method} {request.url.path} | "
            f"Status: {response.status_code} | "
            f"Duration: {duration_ms:.2f}ms | "
            f"Auth: {auth_duration_ms:.2f}ms | Handler: {handler_duration_ms:.2f}ms"
        )
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        handler_duration_ms = (time.perf_counter() - handler_start_time) * 1000
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.error(
            f"Route: {request.method} {request.url.path} | "
            f"Failed: {exc} | "
            f"Duration: {duration_ms:.2f}ms | "
            f"Auth: {auth_duration_ms:.2f}ms | Handler: {handler_duration_ms:.2f}ms",
            exc_info=True
        )
        raise exc
    finally:
        request_id_var.reset(req_token)
        user_var.reset(user_token)
        route_var.reset(route_token)

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


@app.exception_handler(AIException)
async def ai_exception_handler(request: Request, exc: AIException):
    """Return stable AI error codes without exposing provider/payload details."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": exc.request_id,
                "details": exc.details,
            },
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # 注意：Pydantic v2 的 exc.errors() 在 ctx 里可能携带原始异常对象
    # （如 ValueError），直接塞进 JSONResponse 会触发
    # "Object of type ValueError is not JSON serializable"，进而被全局
    # 异常处理器兜成 500。这里清洗成纯可序列化结构，并拼出友好的中文提示。
    raw_errors = exc.errors()
    safe_errors = []
    messages = []
    for e in raw_errors:
        loc = [str(x) for x in e.get('loc', ()) if x != 'body']
        field = loc[-1] if loc else ''
        msg = str(e.get('msg', '') or '参数校验失败')
        # 去掉 Pydantic 的 "Value error, " 前缀，让提示更简洁
        if msg.startswith('Value error, '):
            msg = msg[len('Value error, '):]
        messages.append(f"{field}：{msg}" if field else msg)
        safe_errors.append({
            'type': e.get('type'),
            'loc': loc,
            'msg': msg,
            'input': None if e.get('input') is None else str(e.get('input')),
        })
    detail_msg = '；'.join(messages) or '请求参数校验失败'
    return JSONResponse(
        status_code=422,
        content={"detail": detail_msg, "errors": safe_errors},
    )

# CORS - restrict to known origins in production; permissive in dev
_cors_origins = ["*"] if os.environ.get("NODE_ENV") == "development" else [
    f"http://localhost:{os.environ.get('PORT', '5010')}",
    f"http://127.0.0.1:{os.environ.get('PORT', '5010')}",
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
app.include_router(system_router,        prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(tags_router,          prefix="/api")

# ── 业务路由 ──
app.include_router(devices_router,       prefix="/api")
app.include_router(jobs_router,          prefix="/api")
app.include_router(templates_router,     prefix="/api")
app.include_router(config_templates_router, prefix="/api")
app.include_router(assets_router,        prefix="/api")
app.include_router(racks_router,         prefix="/api")
app.include_router(credentials_router,   prefix="/api")
app.include_router(cmdb_router,          prefix="/api")
app.include_router(ip_locator_router,    prefix="/api")
app.include_router(device_health_router, prefix="/api")
app.include_router(access_router,        prefix="/api")

app.include_router(automation_router,     prefix="/api")
app.include_router(playbooks_router,      prefix="/api")
app.include_router(scheduled_jobs_router, prefix="/api")
app.include_router(configs_router,        prefix="/api")
app.include_router(config_backup_policies_router, prefix="/api")
app.include_router(config_drift_router,   prefix="/api")
app.include_router(config_search_router,  prefix="/api")
app.include_router(config_diff_analysis_router, prefix="/api")
app.include_router(monitoring_router,     prefix="/api")
app.include_router(alerts_router,         prefix="/api")
app.include_router(topology_router,       prefix="/api")
app.include_router(ipam_router,           prefix="/api")
app.include_router(capacity_router,       prefix="/api")
app.include_router(interfaces_router,     prefix="/api")
app.include_router(discovery_router,      prefix="/api")
app.include_router(graph_router,          prefix="/api")
app.include_router(reports_router,        prefix="/api")
app.include_router(compliance_router,     prefix="/api")
app.include_router(inspections_router,    prefix="/api")
app.include_router(collection_plans_router, prefix="/api")
app.include_router(textfsm_templates_router, prefix="/api")
app.include_router(parser_templates_router, prefix="/api")
app.include_router(platform_registry_router, prefix="/api")
app.include_router(knowledge_sources_router, prefix="/api")
app.include_router(knowledge_documents_router, prefix="/api")
app.include_router(knowledge_catalog_router, prefix="/api")
app.include_router(knowledge_collections_router, prefix="/api")
app.include_router(knowledge_ingestion_router, prefix="/api")
app.include_router(device_registry_router, prefix="/api")
app.include_router(change_orders_router,  prefix="/api")
app.include_router(pam_router,            prefix="/api")
app.include_router(pam_web_router,        prefix="/api")
app.include_router(audit_router,          prefix="/api")
app.include_router(ai_router,             prefix="/api")
# Versioned contract used by API clients; its prefix already contains /api/v1.
app.include_router(ai_v1_chat_router)
# PAM WebSocket 单独注册
app.include_router(pam_ws_router,         prefix="/api")

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

from starlette.exceptions import HTTPException as StarletteHTTPException

class SPAStaticFiles(StaticFiles):
    """
    Custom StaticFiles to support Single Page Application (SPA) routing.
    If a requested path returns 404 and is not an API request, static download,
    or a request for a file with a static asset extension (e.g. .js, .css, .ico, .png),
    it falls back to serving 'index.html'.
    """
    async def get_response(self, path: str, scope):
        norm_path = path.replace("\\", "/").lstrip("/")
        try:
            response = await super().get_response(path, scope)
            if response.status_code == 404:
                if not norm_path.startswith("api/") and not norm_path.startswith("static/"):
                    filename = os.path.basename(norm_path)
                    has_extension = "." in filename and not filename.endswith(".html")
                    if not has_extension:
                        return await super().get_response("index.html", scope)
            return response
        except (HTTPException, StarletteHTTPException) as exc:
            if exc.status_code == 404:
                if not norm_path.startswith("api/") and not norm_path.startswith("static/"):
                    filename = os.path.basename(norm_path)
                    has_extension = "." in filename and not filename.endswith(".html")
                    if not has_extension:
                        return await super().get_response("index.html", scope)
            raise exc


# Serve static files from dist directory if it exists
if os.path.exists("dist"):
    logger.info("Serving static files from dist directory")
    app.mount("/", SPAStaticFiles(directory="dist", html=True), name="static")
else:
    logger.warning("dist directory not found. Frontend will not be served.")

def seed_data():
    from database import _USE_PG
    from services.tag_service import seed_builtin_tags, sync_all_device_status_tags
    if not _USE_PG and not os.path.exists(DB_PATH):
        return
    conn = get_db_connection()
    
    try:
        # Keep the tag catalog available for both Device Inventory and
        # Asset Management. The operation is idempotent and only inserts
        # missing built-in definitions.
        seed_builtin_tags(conn)
        synced_status_tags = sync_all_device_status_tags(conn)
        if synced_status_tags:
            logger.info("Synchronized system availability tags for %s device(s)", synced_status_tags)

        # Check if devices table is empty
        # Mock device seeding removed per user request
        
        # Check if users table is empty - only insert default admin if no users exist
        count = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
        if count == 0:
            import bcrypt as _bcrypt
            _hashed_default = _bcrypt.hashpw('admin'.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')
            conn.execute('INSERT INTO users (id, username, password, role, status, last_login) VALUES (?, ?, ?, ?, ?, ?)',
                         ('1', 'admin', _hashed_default, 'Administrator', 'active', 'Never'))
        
        # Check if templates table is empty (we will sync all templates instead of skipping when count != 0)
        import uuid
        from datetime import datetime
        now = datetime.now().isoformat()
        
        templates_seed = [
            # Cisco
            ('Basic SSH Setup', 'cli', 'security', 'Cisco', 
             'ip domain-name {{ domain_name | default("local.net") }}\ncrypto key generate rsa modulus {{ key_size | default(2048) }}\nip ssh version 2\nline vty 0 4\n transport input ssh\n login local', 
             'no ip domain-name {{ domain_name | default("local.net") }}\ncrypto key zeroize rsa\nline vty 0 4\n transport input all\n no login local'),
            ('Standard ACL', 'cli', 'security', 'Cisco', 
             'access-list {{ acl_number | default(10) }} permit {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\naccess-list {{ acl_number | default(10) }} deny any\ninterface {{ interface_name | default("GigabitEthernet0/1") }}\n ip access-group {{ acl_number | default(10) }} in', 
             'interface {{ interface_name | default("GigabitEthernet0/1") }}\n no ip access-group {{ acl_number | default(10) }} in\nno access-list {{ acl_number | default(10) }}'),
            ('BGP Configuration', 'cli', 'routing', 'Cisco', 
             'router bgp {{ local_as | default(65000) }}\n bgp router-id {{ router_id | default("10.0.0.1") }}\n{% if group_name is defined and group_name %}\n neighbor {{ group_name }} peer-group\n neighbor {{ group_name }} remote-as {{ peer_as | default(65001) }}\n neighbor {{ peer_ip | default("10.0.0.2") }} peer-group {{ group_name }}\n{% else %}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n{% endif %}\n{% if address_family is defined and address_family %}\n address-family {{ address_family }}\n  neighbor {{ peer_ip | default("10.0.0.2") }} activate\n  {% if network_ip is defined and network_ip %}\n  network {{ network_ip }} mask {{ network_mask | default("255.255.255.0") }}\n  {% endif %}\n{% else %}\n  {% if network_ip is defined and network_ip %}\n  network {{ network_ip }} mask {{ network_mask | default("255.255.255.0") }}\n  {% endif %}\n{% endif %}', 
             'no router bgp {{ local_as | default(65000) }}'),
            ('OSPF Single Area', 'cli', 'routing', 'Cisco', 
             'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }} area {{ area_id | default(0) }}', 
             'no router ospf {{ ospf_process_id | default(1) }}'),
            ('VLAN Creation', 'cli', 'switching', 'Cisco', 
             'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}', 
             'no vlan {{ vlan_id | default(10) }}'),
            ('Static Route', 'cli', 'routing', 'Cisco',
             'ip route {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}',
             'no ip route {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}'),
            ('AAA TACACS+ Setup', 'cli', 'security', 'Cisco',
             'tacacs server {{ server_name | default("TAC-SRV") }}\n address ipv4 {{ server_ip | default("10.0.0.100") }}\n key {{ tacacs_key | default("secret123") }}\naaa group server tacacs+ {{ group_name | default("TAC-GRP") }}\n server name {{ server_name | default("TAC-SRV") }}\naaa authentication login default group {{ group_name | default("TAC-GRP") }} local',
             'no aaa authentication login default\nno aaa group server tacacs+ {{ group_name | default("TAC-GRP") }}\nno tacacs server {{ server_name | default("TAC-SRV") }}'),
            ('SNMP Configuration', 'cli', 'management', 'Cisco',
             'snmp-server community {{ snmp_community | default("public") }} RO {{ acl_number | default(10) }}\nsnmp-server contact {{ contact_info | default("admin@local.net") }}',
             'no snmp-server community {{ snmp_community | default("public") }}'),
            ('NTP Configuration', 'cli', 'management', 'Cisco',
             'ntp server {{ ntp_server_ip | default("10.0.0.254") }}\nntp source {{ source_interface | default("Loopback0") }}',
             'no ntp server {{ ntp_server_ip | default("10.0.0.254") }}'),

            # Juniper
            ('Basic SSH Setup', 'cli', 'security', 'Juniper', 
             'set system services ssh root-login {{ root_login | default("deny") }}\nset system services ssh protocol-version v2', 
             'delete system services ssh'),
            ('Firewall Filter (ACL)', 'cli', 'security', 'Juniper', 
             'set firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 from source-address {{ source_network | default("192.168.1.0/24") }}\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 1 then accept\nset firewall family inet filter {{ filter_name | default("PROTECT") }} term 2 then reject', 
             'delete firewall family inet filter {{ filter_name | default("PROTECT") }}'),
            ('BGP Configuration', 'cli', 'routing', 'Juniper', 
             'set routing-options autonomous-system {{ local_as | default(65000) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} type external\nset protocols bgp group {{ group_name | default("EXTERNAL") }} peer-as {{ peer_as | default(65001) }}\nset protocols bgp group {{ group_name | default("EXTERNAL") }} neighbor {{ peer_ip | default("10.0.0.2") }}', 
             'delete protocols bgp group {{ group_name | default("EXTERNAL") }}\ndelete routing-options autonomous-system {{ local_as | default(65000) }}'),
            ('OSPF Single Area', 'cli', 'routing', 'Juniper', 
             'set protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}', 
             'delete protocols ospf area {{ area_id | default("0.0.0.0") }} interface {{ interface_name | default("ge-0/0/0.0") }}'),
            ('VLAN Creation', 'cli', 'switching', 'Juniper', 
             'set vlans {{ vlan_name | default("USERS") }} vlan-id {{ vlan_id | default(10) }}', 
             'delete vlans {{ vlan_name | default("USERS") }}'),
            ('Static Route', 'cli', 'routing', 'Juniper',
             'set routing-options static route {{ destination_network | default("192.168.2.0/24") }} next-hop {{ next_hop_ip | default("10.0.0.2") }}',
             'delete routing-options static route {{ destination_network | default("192.168.2.0/24") }} next-hop {{ next_hop_ip | default("10.0.0.2") }}'),
            ('System NTP', 'cli', 'management', 'Juniper',
             'set system ntp server {{ ntp_server_ip | default("10.0.0.254") }}',
             'delete system ntp server {{ ntp_server_ip | default("10.0.0.254") }}'),
            ('SNMP Server', 'cli', 'management', 'Juniper',
             'set snmp community {{ snmp_community | default("public") }} authorization read-only',
             'delete snmp community {{ snmp_community | default("public") }}'),

            # Huawei
            ('Basic SSH Setup', 'cli', 'security', 'Huawei', 
             'rsa local-key-pair create {{ key_size | default(2048) }}\nuser-interface vty 0 4\n authentication-mode aaa\n protocol inbound ssh', 
             'rsa local-key-pair destroy'),
            ('Basic ACL', 'cli', 'security', 'Huawei', 
             'acl number {{ acl_number | default(2000) }}\n rule 5 permit source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\n rule 10 deny', 
             'undo acl {{ acl_number | default(2000) }}'),
            ('Advanced ACL', 'cli', 'security', 'Huawei',
             'acl number {{ acl_number | default(3000) }}\n rule 5 permit ip source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }} destination {{ destination_network | default("10.0.0.0") }} {{ dest_wildcard_mask | default("0.0.0.255") }}\n rule 10 deny ip',
             'undo acl {{ acl_number | default(3000) }}'),
            ('BGP Configuration', 'cli', 'routing', 'Huawei', 
             'bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n peer {{ peer_ip | default("10.0.0.2") }} as-number {{ peer_as | default(65001) }}\n ipv4-family unicast\n  peer {{ peer_ip | default("10.0.0.2") }} enable\n  network {{ network_ip | default("192.168.1.0") }} {{ network_mask | default("255.255.255.0") }}', 
             'undo bgp {{ local_as | default(65000) }}'),
            ('OSPF Single Area', 'cli', 'routing', 'Huawei', 
             'ospf {{ ospf_process_id | default(1) }} router-id {{ router_id | default("10.0.0.1") }}\n area {{ area_id | default("0.0.0.0") }}\n  network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }}', 
             'undo ospf {{ ospf_process_id | default(1) }}'),
            ('VLAN Creation', 'cli', 'switching', 'Huawei', 
             'vlan {{ vlan_id | default(10) }}\n description {{ vlan_name | default("USERS") }}',
             'undo vlan {{ vlan_id | default(10) }}'),
            ('Static Route', 'cli', 'routing', 'Huawei',
             'ip route-static {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}',
             'undo ip route-static {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}'),
            ('AAA TACACS+ Setup', 'cli', 'security', 'Huawei',
             'hwtacacs-server template {{ template_name | default("TAC-TMP") }}\n hwtacacs-server authentication {{ server_ip | default("10.0.0.100") }}\n hwtacacs-server shared-key cipher {{ shared_key | default("secret123") }}\naaa\n authentication-scheme {{ auth_scheme | default("TAC-SCH") }}\n  authentication-mode hwtacacs local',
             'aaa\n undo authentication-scheme {{ auth_scheme | default("TAC-SCH") }}\nundo hwtacacs-server template {{ template_name | default("TAC-TMP") }}'),
            ('SNMP Configuration', 'cli', 'management', 'Huawei',
             'snmp-agent community read {{ snmp_community | default("public") }} acl {{ acl_number | default(2000) }}\nsnmp-agent sys-info contact {{ contact_info | default("admin@local.net") }}',
             'undo snmp-agent community {{ snmp_community | default("public") }}'),
            ('NTP Configuration', 'cli', 'management', 'Huawei',
             'ntp-service unicast-server {{ ntp_server_ip | default("10.0.0.254") }}',
             'undo ntp-service unicast-server {{ ntp_server_ip | default("10.0.0.254") }}'),

            # Arista
            ('Basic SSH Setup', 'cli', 'security', 'Arista', 
             'management ssh\n server-port {{ ssh_port | default(22) }}\n no shutdown', 
             'management ssh\n shutdown'),
            ('Standard ACL', 'cli', 'security', 'Arista', 
             'ip access-list standard {{ acl_name | default("PROTECT") }}\n permit {{ source_network | default("192.168.1.0/24") }}\n deny any', 
             'no ip access-list standard {{ acl_name | default("PROTECT") }}'),
            ('BGP Configuration', 'cli', 'routing', 'Arista', 
             'router bgp {{ local_as | default(65000) }}\n router-id {{ router_id | default("10.0.0.1") }}\n neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n network {{ network_ip | default("192.168.1.0/24") }}', 
             'no router bgp {{ local_as | default(65000) }}'),
            ('OSPF Single Area', 'cli', 'routing', 'Arista', 
             'router ospf {{ ospf_process_id | default(1) }}\n router-id {{ router_id | default("10.0.0.1") }}\n network {{ network_ip | default("10.0.0.0/24") }} area {{ area_id | default("0.0.0.0") }}', 
             'no router ospf {{ ospf_process_id | default(1) }}'),
            ('VLAN Creation', 'cli', 'switching', 'Arista', 
             'vlan {{ vlan_id | default(10) }}\n name {{ vlan_name | default("Users") }}', 
             'no vlan {{ vlan_id | default(10) }}'),
            ('Static Route', 'cli', 'routing', 'Arista',
             'ip route {{ destination_network | default("192.168.2.0/24") }} {{ next_hop_ip | default("10.0.0.2") }}',
             'no ip route {{ destination_network | default("192.168.2.0/24") }} {{ next_hop_ip | default("10.0.0.2") }}'),
            ('SNMP Server', 'cli', 'management', 'Arista',
             'snmp-server community {{ snmp_community | default("public") }} ro',
             'no snmp-server community {{ snmp_community | default("public") }}'),

            # H3C
            ('Basic SSH Setup', 'cli', 'security', 'H3C', 
             'public-key local create rsa\nuser-interface vty 0 4\n authentication-mode scheme\n protocol inbound ssh', 
             'public-key local destroy rsa'),
            ('Basic ACL', 'cli', 'security', 'H3C', 
             'acl basic {{ acl_number | default(2000) }}\n rule 5 permit source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }}\n rule 10 deny', 
             'undo acl basic {{ acl_number | default(2000) }}'),
            ('Advanced ACL', 'cli', 'security', 'H3C',
             'acl advanced {{ acl_number | default(3000) }}\n rule 5 permit ip source {{ source_network | default("192.168.1.0") }} {{ wildcard_mask | default("0.0.0.255") }} destination {{ destination_network | default("10.0.0.0") }} {{ dest_wildcard_mask | default("0.0.0.255") }}\n rule 10 deny ip',
             'undo acl advanced {{ acl_number | default(3000) }}'),
            ('Static Route', 'cli', 'routing', 'H3C',
             'ip route-static {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}',
             'undo ip route-static {{ destination_network | default("192.168.2.0") }} {{ netmask | default("255.255.255.0") }} {{ next_hop_ip | default("10.0.0.2") }}'),
            ('OSPF Single Area', 'cli', 'routing', 'H3C',
             'ospf {{ ospf_process_id | default(1) }} router-id {{ router_id | default("10.0.0.1") }}\n area {{ area_id | default(0) }}\n  network {{ network_ip | default("10.0.0.0") }} {{ wildcard_mask | default("0.0.0.255") }}',
             'undo ospf {{ ospf_process_id | default(1) }}'),
            ('VLAN Creation', 'cli', 'switching', 'H3C',
             'vlan {{ vlan_id | default(10) }}\n description {{ vlan_name | default("USERS") }}',
             'undo vlan {{ vlan_id | default(10) }}'),
            ('SNMP Configuration', 'cli', 'management', 'H3C',
             'snmp-agent community read {{ snmp_community | default("public") }} acl {{ acl_number | default(2000) }}\nsnmp-agent sys-info contact {{ contact_info | default("admin@local.net") }}',
             'undo snmp-agent community read {{ snmp_community | default("public") }}')
        ]
        
        for name, type_, category, vendor, content, rollback in templates_seed:
            row = conn.execute('SELECT id FROM templates WHERE name = ? AND vendor = ?', (name, vendor)).fetchone()
            if row:
                conn.execute('UPDATE templates SET content = ?, rollback = ? WHERE name = ? AND vendor = ?', (content, rollback, name, vendor))
            else:
                conn.execute('INSERT INTO templates (id, name, type, category, vendor, content, rollback, last_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                             (str(uuid.uuid4()), name, type_, category, vendor, content, rollback, now))

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

        # Seed demo racks if empty (mock seeding removed per user request)
        pass

        # Migrate Aliyun DNS and Tencent DNS default targets to DNS_RESOLVE
        conn.execute(
            """
            UPDATE outbound_probe_targets
            SET probe_type = 'DNS_RESOLVE'
            WHERE target_name IN ('Tencent DNS', 'Aliyun DNS') AND probe_type = 'TCP_CONNECT'
            """
        )

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

    port = int(os.environ.get("PORT", "5010"))
    workers = int(os.environ.get("WORKERS", "1"))
    is_dev = os.environ.get("NODE_ENV") == "development"

    # On modern uvicorn versions, loop must be one of: auto/asyncio/uvloop/none.
    # Windows Proactor is already enforced via event loop policy above.
    loop_type = "none" if sys.platform == "win32" else "auto"


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

    # Bind to loopback by default — production deployments should sit
    # behind Nginx (which forwards 127.0.0.1:$PORT). Override with
    # `HOST=0.0.0.0` only when the backend really must accept external
    # traffic directly (e.g. running outside a reverse proxy).
    host = os.environ.get("HOST", "127.0.0.1")

    if workers > 1:
        uvicorn.run("main:app", host=host, port=port, workers=workers, loop=loop_type, access_log=False)
    else:
        uvicorn.run("main:app", host=host, port=port, loop=loop_type, access_log=False, **reload_kwargs)

# Reloader validation check comment

