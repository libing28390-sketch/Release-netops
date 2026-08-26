import contextvars
import re
import uuid


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def new_request_id(prefix: str = "req") -> str:
    """Create a bounded, log/header-safe correlation identifier."""

    safe_prefix = re.sub(r"[^A-Za-z0-9]+", "-", str(prefix or "req")).strip("-") or "req"
    return f"{safe_prefix}_{uuid.uuid4().hex[:20]}"


def resolve_request_id(value: object = None, *, prefix: str = "req") -> str:
    """Accept a safe caller id or issue a new one.

    Request IDs cross HTTP headers, logs, traces, and provider headers.  Keep
    them deliberately opaque and bounded so a caller cannot inject newlines,
    unbounded data, or structured log content through the correlation field.
    """

    candidate = str(value or "").strip()
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return new_request_id(prefix)

# HTTP request context
request_id_var = contextvars.ContextVar("request_id", default="-")
user_var = contextvars.ContextVar("user", default="-")
route_var = contextvars.ContextVar("route", default="-")

# Background job context
job_id_var = contextvars.ContextVar("job_id", default="-")
target_id_var = contextvars.ContextVar("target_id", default="-")
device_id_var = contextvars.ContextVar("device_id", default="-")
