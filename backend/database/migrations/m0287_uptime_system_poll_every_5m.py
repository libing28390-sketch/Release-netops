"""Reduce the built-in sysUpTime collection interval to five minutes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


VERSION = 287
NAME = "uptime_system_poll_every_5m"

_BASELINE_PLAN_ID = "plan-generic-ifmib"
_SYSTEM_MODULE = "generic_system"
_SYSTEM_VARIANT = "generic_system_std"


def _set_builtin_system_interval(cursor, *, old_interval: str, new_interval: str) -> None:
    row = cursor.execute(
        "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
        (_BASELINE_PLAN_ID,),
    ).fetchone()
    if not row:
        return

    raw: Any = row[0] if not hasattr(row, "get") else row.get("config_json")
    try:
        config = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        return

    modules = config.get("modules")
    if not isinstance(modules, list):
        return

    changed = False
    for entry in modules:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("module") == _SYSTEM_MODULE
            and entry.get("variant") == _SYSTEM_VARIANT
            and str(entry.get("interval") or "").strip() == old_interval
        ):
            entry["interval"] = new_interval
            changed = True

    if changed:
        cursor.execute(
            "UPDATE monitoring_collection_plans SET config_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(config, ensure_ascii=False, separators=(",", ":")),
                datetime.now(timezone.utc).isoformat(),
                _BASELINE_PLAN_ID,
            ),
        )


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    _set_builtin_system_interval(cursor, old_interval="900s", new_interval="300s")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    _set_builtin_system_interval(cursor, old_interval="300s", new_interval="900s")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
