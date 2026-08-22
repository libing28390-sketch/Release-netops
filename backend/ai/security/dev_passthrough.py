"""Development-only, time-limited AI egress passthrough state.

The feature gate comes from configuration, while activation is deliberately
kept in memory so a process restart disables the mode automatically. This is
not a production override and never enables itself from an environment flag.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from core.config import settings


_DEV_ENVIRONMENTS = {"development", "dev", "test"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DevPassthroughController:
    def __init__(self) -> None:
        self._lock = RLock()
        self._expires_at: datetime | None = None

    def is_supported(self) -> bool:
        environment = str(getattr(settings, "ENVIRONMENT", "") or "").strip().lower()
        return environment in _DEV_ENVIRONMENTS and bool(getattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", False))

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
            raise RuntimeError("AI development passthrough is unavailable outside a configured development environment")
        configured_max = max(1, int(getattr(settings, "AI_DEV_PASSTHROUGH_MAX_MINUTES", 15) or 15))
        requested = configured_max if duration_minutes is None else int(duration_minutes)
        if requested < 1 or requested > configured_max:
            raise ValueError(f"duration_minutes must be between 1 and {configured_max}")
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
            max_minutes = max(1, int(getattr(settings, "AI_DEV_PASSTHROUGH_MAX_MINUTES", 15) or 15))
            return {
                "supported": supported,
                "configured": bool(getattr(settings, "AI_DEV_PASSTHROUGH_ENABLED", False)),
                "enabled": bool(expires_at and remaining > 0),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "remaining_seconds": remaining,
                "max_minutes": max_minutes,
                "environment": str(getattr(settings, "ENVIRONMENT", "") or "unknown"),
            }


dev_passthrough = DevPassthroughController()
