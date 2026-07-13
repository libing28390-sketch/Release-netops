import contextvars

# HTTP request context
request_id_var = contextvars.ContextVar("request_id", default="-")
user_var = contextvars.ContextVar("user", default="-")
route_var = contextvars.ContextVar("route", default="-")

# Background job context
job_id_var = contextvars.ContextVar("job_id", default="-")
target_id_var = contextvars.ContextVar("target_id", default="-")
device_id_var = contextvars.ContextVar("device_id", default="-")
