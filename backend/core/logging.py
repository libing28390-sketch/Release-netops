import gzip
import shutil
import logging
import sys
import os
import re
from logging.handlers import TimedRotatingFileHandler
from core.config import settings

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] (PID:%(process)d) [%(context)s] %(name)s: %(message)s"

# 三方库噪声压制：只保留 WARNING 及以上
_NOISY_LIBS = [
    "uvicorn.access",
    "uvicorn.error",
    "apscheduler",
    "netmiko",
    "scrapli",
    "paramiko",
    "asyncssh",
]

# ── Log sanitization filter ──
_SENSITIVE_PATTERNS = re.compile(
    r'(password|passwd|secret|community|token|auth_pass|priv_pass|credential)'
    r'[\s]*[=:]\s*["\']?([^\s"\'&,;]+)',
    re.IGNORECASE,
)

class SanitizeFilter(logging.Filter):
    """Redact sensitive values (passwords, tokens, communities) from log messages."""
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _SENSITIVE_PATTERNS.sub(r'\1=***', record.msg)
        if record.args:
            sanitized = []
            for arg in record.args if isinstance(record.args, tuple) else (record.args,):
                if isinstance(arg, str):
                    sanitized.append(_SENSITIVE_PATTERNS.sub(r'\1=***', arg))
                else:
                    sanitized.append(arg)
            record.args = tuple(sanitized) if isinstance(record.args, tuple) else sanitized[0]
        return True

class ContextFormatter(logging.Formatter):
    """Formatter that ensures the request/job context variables are present on the record."""
    def format(self, record):
        if not hasattr(record, "context"):
            try:
                from core.context import request_id_var, user_var, job_id_var, target_id_var, device_id_var
                req_id = request_id_var.get()
                user = user_var.get()
                job_id = job_id_var.get()
                target_id = target_id_var.get()
                device_id = device_id_var.get()
                
                ctx_parts = []
                if req_id and req_id != "-":
                    ctx_parts.append(f"req:{req_id}")
                if user and user != "-":
                    ctx_parts.append(f"user:{user}")
                if job_id and job_id != "-":
                    ctx_parts.append(f"job:{job_id}")
                if target_id and target_id != "-":
                    ctx_parts.append(f"target:{target_id}")
                if device_id and device_id != "-":
                    ctx_parts.append(f"device:{device_id}")
                    
                record.context = ", ".join(ctx_parts) if ctx_parts else "-"
            except Exception:
                record.context = "-"
        return super().format(record)

def classify_request_log_level(status_code: int, duration_ms: float) -> int:
    """Keep routine 2xx requests quiet while retaining operational signals."""
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400 or duration_ms >= float(settings.LOG_SLOW_REQUEST_MS):
        return logging.WARNING
    return logging.DEBUG


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "netops.log")

    root = logging.getLogger()
    if root.handlers:
        return
    configured_level = str(settings.LOG_LEVEL or "INFO").strip().upper()
    root.setLevel(getattr(logging, configured_level, logging.INFO))
    root.addFilter(SanitizeFilter())

    fmt = ContextFormatter(LOG_FORMAT)

    # stdout handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 按天轮转：每天午夜切割，保留 90 天，旧日志自动 gzip 压缩
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=90,
        encoding="utf-8",
    )
    
    def namer(name):
        return name + ".gz"

    def rotator(source, dest):
        with open(source, 'rb') as f_in:
            with gzip.open(dest, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(source)

    file_handler.namer = namer
    file_handler.rotator = rotator
    file_handler.suffix = "%Y-%m-%d"      # netops.log.2026-03-07
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 压制三方库噪声
    for lib in _NOISY_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)
