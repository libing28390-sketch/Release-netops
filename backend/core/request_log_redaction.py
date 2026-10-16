"""Redact bearer capabilities from request and Uvicorn access logs."""

from __future__ import annotations

import logging
import re
from typing import Any


_REMOTE_DESKTOP_TICKET_PATH = re.compile(r"(/api/pam/remote-desktop-ws/)[A-Za-z0-9_-]+")


def redact_remote_desktop_ticket_path(path: str) -> str:
    """Replace the one-time WebSocket ticket while preserving route shape."""

    return _REMOTE_DESKTOP_TICKET_PATH.sub(r"\1[REDACTED]", str(path or ""))


class UvicornAccessTicketRedactionFilter(logging.Filter):
    """Redact the URL argument in Uvicorn's standard access-log tuple."""

    def filter(self, record: logging.LogRecord) -> bool:
        args: Any = record.args
        # Uvicorn's AccessLogger tuple is (client, method, path+query, version,
        # status). Leave unfamiliar records unchanged instead of guessing.
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], redact_remote_desktop_ticket_path(args[2]), *args[3:])
        return True


__all__ = ["UvicornAccessTicketRedactionFilter", "redact_remote_desktop_ticket_path"]
