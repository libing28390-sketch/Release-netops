"""Short-lived, administrator-controlled AI test mode.

The capability follows the normal AI enablement settings instead of the
deployment environment label. Activation remains in memory and expires
automatically, so a restart disables the mode without adding another
deployment profile or persistent switch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from core.config import settings


_MAX_TEST_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DevPassthroughController:
    def __init__(self) -> None:
        self._lock = RLock()
        self._expires_at: datetime | None = None

    def is_supported(self) -> bool:
        return bool(
            getattr(settings, "AI_ENABLED", False)
            and getattr(settings, "EXTERNAL_AI_ENABLED", False)
        )

    def is_active(self) -> bool:
        with self._lock:
            if not self.is_supported():
                self._expires_at = None
                return False
            if self._expires_at is None:
                return False
            if self._expires_at <= _now():
                self._expires_at = None
                return False
            return True

    def enable(self, duration_minutes: int | None = None) -> dict[str, Any]:
        if not self.is_supported():
            raise RuntimeError("AI temporary test mode requires AI and external AI to be enabled")
        requested = _MAX_TEST_MINUTES if duration_minutes is None else int(duration_minutes)
        if requested < 1 or requested > _MAX_TEST_MINUTES:
            raise ValueError(f"duration_minutes must be between 1 and {_MAX_TEST_MINUTES}")
        with self._lock:
            self._expires_at = _now() + timedelta(minutes=requested)
        return self.status()

    def disable(self) -> dict[str, Any]:
        with self._lock:
            self._expires_at = None
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            supported = self.is_supported()
            if not supported:
                self._expires_at = None
            elif self._expires_at is not None and self._expires_at <= _now():
                self._expires_at = None
            expires_at = self._expires_at
            remaining = max(0, int((expires_at - _now()).total_seconds())) if expires_at else 0
            return {
                "supported": supported,
                "configured": supported,
                "enabled": bool(expires_at and remaining > 0),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "remaining_seconds": remaining,
                "max_minutes": _MAX_TEST_MINUTES,
                "environment": str(getattr(settings, "ENVIRONMENT", "") or "unknown"),
            }


dev_passthrough = DevPassthroughController()
