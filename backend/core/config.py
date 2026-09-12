import os

from pydantic import model_validator
from pydantic_settings import BaseSettings


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
_ENV_FILE = os.path.join(PROJECT_ROOT, '.env')
_ENV_LOCAL_FILE = os.path.join(PROJECT_ROOT, '.env.local')

class Settings(BaseSettings):
    PROJECT_NAME: str = "NetOps Automation Platform"
    DATABASE_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    IP_LOCATOR_CACHE_BACKEND: str = "redis"
    IP_LOCATOR_REDIS_NAMESPACE: str = "nexora:production:locator:v1"
    IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS: float = 1.0
    IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS: float = 1.0
    IP_LOCATOR_REDIS_FAILURE_COOLDOWN_SECONDS: float = 30.0
    IP_LOCATOR_ROUTE_FRESH_SECONDS: int = 300
    IP_LOCATOR_ROUTE_RETAIN_SECONDS: int = 1800
    IP_LOCATOR_ARP_FRESH_SECONDS: int = 300
    IP_LOCATOR_ARP_RETAIN_SECONDS: int = 1800
    IP_LOCATOR_MAC_FRESH_SECONDS: int = 120
    IP_LOCATOR_MAC_RETAIN_SECONDS: int = 900
    IP_LOCATOR_RESULT_FRESH_SECONDS: int = 120
    IP_LOCATOR_RESULT_RETAIN_SECONDS: int = 900
    IP_LOCATOR_SUBNET_FRESH_SECONDS: int = 900
    IP_LOCATOR_SUBNET_RETAIN_SECONDS: int = 86400
    IP_LOCATOR_TOPOLOGY_FRESH_SECONDS: int = 172800
    IP_LOCATOR_TOPOLOGY_RETAIN_SECONDS: int = 259200
    IP_LOCATOR_NEGATIVE_CACHE_SECONDS: int = 15
    IP_LOCATOR_CLI_GLOBAL_CONCURRENCY: int = 5
    IP_LOCATOR_CLI_PER_DEVICE_CONCURRENCY: int = 1
    IP_LOCATOR_CLI_IDLE_SECONDS: int = 15
    IP_LOCATOR_TASK_DEADLINE_SECONDS: int = 180
    SECRET_KEY: str = "supersecret"
    CREDENTIAL_ENCRYPTION_KEY: str = "change-me-to-a-random-secret"
    ENVIRONMENT: str = "development"
    # Application logs keep operational summaries at INFO. Ordinary successful
    # HTTP access records are emitted at DEBUG; warnings/errors remain visible.
    LOG_LEVEL: str = "INFO"
    LOG_SLOW_REQUEST_MS: float = 500.0
    # The file logger is bounded independently from Docker's stdout/stderr
    # rotation so an application restart loop cannot fill the data volume.
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUP_COUNT: int = 5
    # Keep the application boundary aligned with nginx's 150m limit.  Route
    # models and upload handlers may impose smaller limits for their payloads.
    REQUEST_BODY_MAX_BYTES: int = 150 * 1024 * 1024
    SESSION_TTL_SECONDS: int = 7200
    TELEMETRY_RAW_RETENTION_HOURS: int = 48
    TELEMETRY_ROLLUP_RETENTION_DAYS: int = 365
    # Outbound probe samples are operational history and remain queryable for
    # one month by default, independently of the generic telemetry cleanup.
    OUTBOUND_PROBE_RETENTION_DAYS: int = 30
    PLAYBOOK_RAW_OUTPUT_RETENTION_DAYS: int = 30
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

    # MIBs can be maintained from the versioned LibreNMS catalog or uploaded
    # by an Operator.  Keep the limits configurable so a large vendor archive
    # cannot exhaust memory during parsing.
    SNMP_MIB_MANUAL_UPLOAD_ENABLED: bool = True
    SNMP_MIB_UPLOAD_MAX_BYTES: int = 150 * 1024 * 1024
    SNMP_MIB_UPLOAD_MAX_FILES: int = 20000
    SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES: int = 500 * 1024 * 1024

    # External AI is opt-in.  Security gateway failures, kill-switch state,
    # oversized payloads, and provider URL policy are all enforced before an
    # HTTP request is constructed.
    AI_ENABLED: bool = False
    EXTERNAL_AI_ENABLED: bool = False
    AI_KILL_SWITCH: bool = False
    # Kept for backwards-compatible parsing of older .env files. The
    # administrator-controlled temporary test mode is now gated by the
    # normal AI flags and does not require these deployment settings.
    AI_DEV_PASSTHROUGH_ENABLED: bool = False
    AI_DEV_PASSTHROUGH_MAX_MINUTES: int = 15
    AI_SECURITY_VAULT_TTL_SECONDS: int = 3600
    AI_MAX_PAYLOAD_BYTES: int = 256000
    AI_PROVIDER_ALLOWLIST: str = "deepseek,openai,openai_compatible,azure_openai,ollama,local,qwen"
    AI_DEBUG_PAYLOAD: bool = False
    AI_OUTBOUND_PROXY_URL: str = ""
    # One provider-agnostic, read-only web retrieval capability.  It is used
    # for explicitly current/public questions and as a fallback after a
    # network-knowledge miss; it never grants device write or tenant access.
    AI_WEB_SEARCH_ENABLED: bool = True
    AI_WEB_SEARCH_ENDPOINT: str = "https://html.duckduckgo.com/html/"
    AI_WEB_ALLOWED_HOSTS: str = ""
    AI_WEB_TIMEOUT_SECONDS: float = 8.0
    AI_WEB_MAX_RESULTS: int = 5
    AI_WEB_MAX_PAGE_FETCHES: int = 3
    AI_WEB_MAX_PAGE_CHARS: int = 6000
    AI_WEB_MAX_RESPONSE_BYTES: int = 1_000_000
    AI_WEB_USER_AGENT: str = "NexoraAIWeb/1.0"
    AI_PROVIDER_MAX_CONCURRENCY: int = 8
    AI_TENANT_MAX_CONCURRENCY: int = 4
    AI_USER_MAX_CONCURRENCY: int = 2
    AI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS: float = 10.0
    AI_CIRCUIT_FAILURE_THRESHOLD: int = 3
    AI_CIRCUIT_COOLDOWN_SECONDS: float = 30.0
    AI_HEALTH_BACKOFF_SECONDS: int = 30
    # Model probes are intentionally sparse and tiny: one probe per enabled
    # chat/reasoning model every ten minutes by default.  The gateway still
    # enforces the normal security, concurrency and circuit-breaker controls.
    AI_MODEL_HEALTH_MONITOR_ENABLED: bool = True
    AI_MODEL_HEALTH_INTERVAL_MINUTES: int = 10
    AI_MODEL_HEALTH_MAX_CONCURRENCY: int = 2
    AI_MODEL_HEALTH_MAX_TOKENS: int = 64
    AI_MODEL_HEALTH_RETENTION_DAYS: int = 90
    AI_DAILY_BUDGET_USD: float = 0.0

    # PAM Web terminal compatibility control. Host-key registration is not a
    # login prerequisite; legacy algorithms still require explicit opt-in.
    PAM_ALLOW_LEGACY_SSH: bool = False
    VAULT_ENABLED: bool = False
    VAULT_ADDR: str = "http://127.0.0.1:8200"
    VAULT_TOKEN: str = ""
    VAULT_MOUNT: str = "secret"               # KV v2 mount path
    VAULT_PREFIX: str = "netops/devices"       # key prefix under mount

    # Password rotation
    PASSWORD_ROTATION_ENABLED: bool = False
    PASSWORD_ROTATION_INTERVAL_DAYS: int = 90
    PASSWORD_ROTATION_NOTIFY_DAYS: int = 14    # warn N days before expiry
    PASSWORD_SYNC_MAX_WORKERS: int = 5
    PASSWORD_SYNC_DEVICE_TIMEOUT_SECONDS: int = 240
    PASSWORD_SYNC_CONNECT_TIMEOUT_SECONDS: int = 20
    PASSWORD_SYNC_COMMAND_READ_TIMEOUT_SECONDS: int = 60
    PASSWORD_SYNC_RETRY_LIMIT: int = 1

    class Config:
        # .env.local 优先级高于 .env（后面的文件覆盖前面的）
        # pydantic-settings 按列表顺序加载，后加载的值覆盖先加载的
        env_file = (_ENV_FILE, _ENV_LOCAL_FILE)
        env_file_encoding = 'utf-8'
        extra = "ignore"

    @model_validator(mode="after")
    def validate_ip_locator_configuration(self) -> "Settings":
        backend = str(self.IP_LOCATOR_CACHE_BACKEND or "").strip().lower()
        if backend not in {"redis", "postgres"}:
            raise ValueError("IP_LOCATOR_CACHE_BACKEND must be redis or postgres")
        namespace = str(self.IP_LOCATOR_REDIS_NAMESPACE or "").strip()
        if not namespace or any(char.isspace() for char in namespace):
            raise ValueError("IP_LOCATOR_REDIS_NAMESPACE must be non-empty and contain no whitespace")
        if len(namespace) > 128:
            raise ValueError("IP_LOCATOR_REDIS_NAMESPACE must be at most 128 characters")
        if self.IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS <= 0:
            raise ValueError("IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS must be positive")
        if self.IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS <= 0:
            raise ValueError("IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS must be positive")
        if self.IP_LOCATOR_REDIS_FAILURE_COOLDOWN_SECONDS <= 0:
            raise ValueError("IP_LOCATOR_REDIS_FAILURE_COOLDOWN_SECONDS must be positive")
        policies = (
            ("ROUTE", self.IP_LOCATOR_ROUTE_FRESH_SECONDS, self.IP_LOCATOR_ROUTE_RETAIN_SECONDS),
            ("ARP", self.IP_LOCATOR_ARP_FRESH_SECONDS, self.IP_LOCATOR_ARP_RETAIN_SECONDS),
            ("MAC", self.IP_LOCATOR_MAC_FRESH_SECONDS, self.IP_LOCATOR_MAC_RETAIN_SECONDS),
            ("RESULT", self.IP_LOCATOR_RESULT_FRESH_SECONDS, self.IP_LOCATOR_RESULT_RETAIN_SECONDS),
            ("SUBNET", self.IP_LOCATOR_SUBNET_FRESH_SECONDS, self.IP_LOCATOR_SUBNET_RETAIN_SECONDS),
            ("TOPOLOGY", self.IP_LOCATOR_TOPOLOGY_FRESH_SECONDS, self.IP_LOCATOR_TOPOLOGY_RETAIN_SECONDS),
        )
        for name, fresh, retain in policies:
            if int(fresh) <= 0 or int(retain) < int(fresh):
                raise ValueError(f"IP_LOCATOR_{name}_RETAIN_SECONDS must be >= positive FRESH_SECONDS")
        if int(self.IP_LOCATOR_NEGATIVE_CACHE_SECONDS) <= 0:
            raise ValueError("IP_LOCATOR_NEGATIVE_CACHE_SECONDS must be positive")
        if int(self.IP_LOCATOR_CLI_GLOBAL_CONCURRENCY) <= 0:
            raise ValueError("IP_LOCATOR_CLI_GLOBAL_CONCURRENCY must be positive")
        if int(self.IP_LOCATOR_CLI_PER_DEVICE_CONCURRENCY) <= 0:
            raise ValueError("IP_LOCATOR_CLI_PER_DEVICE_CONCURRENCY must be positive")
        if int(self.IP_LOCATOR_CLI_IDLE_SECONDS) <= 0:
            raise ValueError("IP_LOCATOR_CLI_IDLE_SECONDS must be positive")
        if int(self.IP_LOCATOR_TASK_DEADLINE_SECONDS) <= 0:
            raise ValueError("IP_LOCATOR_TASK_DEADLINE_SECONDS must be positive")
        return self

settings = Settings()

# 便于其他模块快速判断当前环境
IS_PRODUCTION = settings.ENVIRONMENT.lower() == "production"
IS_DEVELOPMENT = not IS_PRODUCTION


def validate_production_security() -> None:
    """Fail closed when production would start with unsafe configuration.

    Development/test callers retain the existing local defaults.  Production
    startup must receive real values through the environment/secret manager;
    the exception contains stable codes only and never echoes a secret.
    """

    if not IS_PRODUCTION:
        return
    errors: list[str] = []
    database_url = str(settings.DATABASE_URL or "").strip().lower()
    if not database_url.startswith(("postgresql://", "postgres://")):
        errors.append("PRODUCTION_POSTGRES_REQUIRED")
    forbidden = {
        "",
        "supersecret",
        "change-me-to-a-random-secret",
        "change-me-to-a-32-char-random-secret-key",
        "replace-with-a-very-secret-key",
        "replace-with-a-32-char-random-secret-key",
    }
    for field_name in ("SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY"):
        value = str(getattr(settings, field_name, "") or "").strip()
        if value.lower() in forbidden or len(value) < 16:
            errors.append(f"{field_name}_REQUIRED")
    if errors:
        raise RuntimeError("PRODUCTION_SECURITY_CONFIGURATION_INVALID:" + ",".join(errors))
