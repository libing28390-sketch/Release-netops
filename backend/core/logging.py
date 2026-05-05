import gzip
import shutil
import logging
import sys
import os
import re
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] (PID:%(process)d) %(name)s: %(message)s"

# 三方库噪声压制：只保留 WARNING 及以上
_NOISY_LIBS = [
    # "uvicorn.access",
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

def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "netops.log")

    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    root.addFilter(SanitizeFilter())

    fmt = logging.Formatter(LOG_FORMAT)

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
