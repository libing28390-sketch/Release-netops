import gzip
import shutil
import logging
import sys
import os
import re
from pathlib import Path
from logging.handlers import RotatingFileHandler
from core.config import settings

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs")
LOG_FORMAT = "%(asctime)s [%(levelname)s] (PID:%(process)d) [%(context)s] %(name)s: %(message)s"
_MIN_LOG_FILE_BYTES = 1024 * 1024
_MAX_LOG_FILE_BYTES = 50 * 1024 * 1024
_MIN_LOG_BACKUP_COUNT = 1
_MAX_LOG_BACKUP_COUNT = 10
_LEGACY_TIMED_ARCHIVE = re.compile(r"^netops\.log\.20\d{2}-\d{2}-\d{2}\.gz$")

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
    r'(api[_ -]?key|access[_ -]?token|password|passwd|secret|community|token|auth_pass|priv_pass|credential|authorization|cookie|private[_ -]?key)'
    r'[\s]*[=:]\s*["\']?([^\s"\'&,;}]+)',
    re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+')
_PRIVATE_KEY_PATTERN = re.compile(r'(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----')


def _sanitize_log_value(value):
    if isinstance(value, BaseException):
        return type(value).__name__
    if not isinstance(value, str):
        return value
    sanitized = _PRIVATE_KEY_PATTERN.sub('<REDACTED_PRIVATE_KEY>', value)
    sanitized = _BEARER_PATTERN.sub('Bearer <REDACTED>', sanitized)
    return _SENSITIVE_PATTERNS.sub(r'\1=***', sanitized)

class SanitizeFilter(logging.Filter):
    """Redact sensitive values (passwords, tokens, communities) from log messages."""
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _sanitize_log_value(record.msg)
        elif isinstance(record.msg, BaseException):
            record.msg = type(record.msg).__name__
        if record.args:
            original_args = record.args if isinstance(record.args, tuple) else (record.args,)
            sanitized = [_sanitize_log_value(arg) for arg in original_args]
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


def _bounded_int(value, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(parsed, upper))


class SizeBoundedRotatingFileHandler(RotatingFileHandler):
    """Rotate by encoded byte size so multibyte messages cannot bypass the cap."""

    def shouldRollover(self, record):
        if self.maxBytes <= 0:
            return 0
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, os.SEEK_END)
        message = self.format(record) + self.terminator
        encoding = self.encoding or sys.getdefaultencoding()
        message_bytes = len(message.encode(encoding, errors="replace"))
        return int(self.stream.tell() + message_bytes >= self.maxBytes)


def _prune_legacy_timed_archives(log_file: str, max_bytes: int, backup_count: int) -> None:
    """Drop oversized dated archives left by the old unbounded handler."""
    log_path = Path(log_file)
    try:
        archives = [
            (path.stat().st_mtime, path.stat().st_size, path)
            for path in log_path.parent.iterdir()
            if path.is_file() and _LEGACY_TIMED_ARCHIVE.fullmatch(path.name)
        ]
    except OSError:
        return

    # Keep the legacy files inside the same rough budget as the new archive
    # set. This cleanup runs only for dated archives created by the previous
    # handler; numeric .1.gz/.2.gz files are managed by RotatingFileHandler.
    archive_budget = max_bytes * backup_count
    kept_bytes = 0
    kept_count = 0
    for _mtime, size, path in sorted(archives, key=lambda item: item[0], reverse=True):
        if kept_count < backup_count and kept_bytes + size <= archive_budget:
            kept_count += 1
            kept_bytes += size
            continue
        try:
            path.unlink()
        except OSError:
            pass


def _trim_oversized_active_log(log_file: str, max_bytes: int) -> None:
    """Keep the newest tail when an old unbounded active log already exists."""
    log_path = Path(log_file)
    marker = b"\n[previous log truncated to enforce the file-size limit]\n"
    try:
        if not log_path.is_file() or log_path.stat().st_size <= max_bytes:
            return
        tail_bytes = max(0, max_bytes - len(marker))
        with log_path.open("r+b") as stream:
            stream.seek(-tail_bytes, os.SEEK_END) if tail_bytes else stream.seek(0)
            tail = stream.read(tail_bytes)
            stream.seek(0)
            stream.write(marker)
            stream.write(tail)
            stream.truncate()
    except OSError:
        # Logging must never prevent the service from starting. The rotating
        # handler will still enforce the limit on the next emitted record.
        pass


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
    console.addFilter(SanitizeFilter())
    console.setFormatter(fmt)
    root.addHandler(console)

    max_bytes = _bounded_int(
        getattr(settings, "LOG_FILE_MAX_BYTES", 10 * 1024 * 1024),
        default=10 * 1024 * 1024,
        lower=_MIN_LOG_FILE_BYTES,
        upper=_MAX_LOG_FILE_BYTES,
    )
    backup_count = _bounded_int(
        getattr(settings, "LOG_FILE_BACKUP_COUNT", 5),
        default=5,
        lower=_MIN_LOG_BACKUP_COUNT,
        upper=_MAX_LOG_BACKUP_COUNT,
    )
    _trim_oversized_active_log(log_file, max_bytes)
    _prune_legacy_timed_archives(log_file, max_bytes, backup_count)

    # Size-based rotation is the hard safety limit. The active file is capped
    # at max_bytes and backupCount compressed archives are retained.
    file_handler = SizeBoundedRotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
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
    file_handler.setFormatter(fmt)
    file_handler.addFilter(SanitizeFilter())
    root.addHandler(file_handler)

    # 压制三方库噪声
    for lib in _NOISY_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)
