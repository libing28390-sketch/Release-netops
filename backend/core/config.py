import os

from pydantic_settings import BaseSettings


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
DEFAULT_DATABASE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'data', 'netops.db').replace(os.sep, '/')}"
_ENV_FILE = os.path.join(PROJECT_ROOT, '.env')
_ENV_LOCAL_FILE = os.path.join(PROJECT_ROOT, '.env.local')

class Settings(BaseSettings):
    PROJECT_NAME: str = "NetOps Automation Platform"
    DATABASE_URL: str = DEFAULT_DATABASE_URL
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "supersecret"
    CREDENTIAL_ENCRYPTION_KEY: str = "change-me-to-a-random-secret"
    ENVIRONMENT: str = "development"
    TELEMETRY_RAW_RETENTION_HOURS: int = 48
    TELEMETRY_ROLLUP_RETENTION_DAYS: int = 365
    # Outbound probe samples are operational history and remain queryable for
    # one month by default, independently of the generic telemetry cleanup.
    OUTBOUND_PROBE_RETENTION_DAYS: int = 30
    ALERT_INTERFACE_DOWN_ENABLED: bool = True
    ALERT_INTERFACE_UTIL_THRESHOLD: float = 85.0
    ALERT_CPU_THRESHOLD: float = 90.0
    ALERT_MEMORY_THRESHOLD: float = 90.0
    ALERT_NOTIFY_WEBHOOK_URL: str = ""
    # Unified network access budgets.  SSH/CLI and SNMP are intentionally
    # separate because SNMP is UDP polling rather than a login session.
    NETWORK_SSH_GLOBAL_CONCURRENCY: int = 20
    NETWORK_SSH_PER_DEVICE_CONCURRENCY: int = 1
    NETWORK_SNMP_GLOBAL_CONCURRENCY: int = 30
    NETWORK_PROBE_GLOBAL_CONCURRENCY: int = 50
    NETWORK_ACCESS_ACQUIRE_TIMEOUT: float = 120.0
    NETWORK_INSPECTION_CONCURRENCY: int = 10
    # Idle SSH sessions are reused briefly to reduce login churn, then closed
    # automatically so long-running collectors do not leak device sessions.
    NETWORK_POOL_IDLE_SECONDS: int = 300
    NETWORK_POOL_MAX_SIZE: int = 100
    INSPECTION_MASTER_CRON: str = "30 2,14 * * *"
    # 「前往平台处理」按钮跳转地址，留空则不显示按钮
    PLATFORM_URL: str = ""
    # 外部配置管理 API
    # Optional external configuration-management API. Keep it disabled by
    # default so standalone and Docker installations read the local database
    # without waiting for an unreachable private-network endpoint.
    CONFIG_MANAGEMENT_URL: str = ""
    CONFIG_MANAGEMENT_TIMEOUT_SECONDS: float = 1.0

    # HashiCorp Vault integration
    VAULT_ENABLED: bool = False
    VAULT_ADDR: str = "http://127.0.0.1:8200"
    VAULT_TOKEN: str = ""
    VAULT_MOUNT: str = "secret"               # KV v2 mount path
    VAULT_PREFIX: str = "netops/devices"       # key prefix under mount

    # Password rotation
    PASSWORD_ROTATION_ENABLED: bool = False
    PASSWORD_ROTATION_INTERVAL_DAYS: int = 90
    PASSWORD_ROTATION_NOTIFY_DAYS: int = 14    # warn N days before expiry

    class Config:
        # .env.local 优先级高于 .env（后面的文件覆盖前面的）
        # pydantic-settings 按列表顺序加载，后加载的值覆盖先加载的
        env_file = (_ENV_FILE, _ENV_LOCAL_FILE)
        env_file_encoding = 'utf-8'
        extra = "ignore"

settings = Settings()

# 便于其他模块快速判断当前环境
IS_PRODUCTION = settings.ENVIRONMENT.lower() == "production"
IS_DEVELOPMENT = not IS_PRODUCTION
