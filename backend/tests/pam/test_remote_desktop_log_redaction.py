from __future__ import annotations

import logging

from core.request_log_redaction import (
    UvicornAccessTicketRedactionFilter,
    redact_remote_desktop_ticket_path,
)


def test_ticket_is_redacted_from_route_path_and_uvicorn_access_record():
    ticket = "single-use-ticket-value-1234567890"
    path = f"/api/pam/remote-desktop-ws/{ticket}"
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="uvicorn/protocols/http/h11_impl.py",
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", path, "1.1", 101),
        exc_info=None,
    )

    assert redact_remote_desktop_ticket_path(path) == "/api/pam/remote-desktop-ws/[REDACTED]"
    assert UvicornAccessTicketRedactionFilter().filter(record)
    assert ticket not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
