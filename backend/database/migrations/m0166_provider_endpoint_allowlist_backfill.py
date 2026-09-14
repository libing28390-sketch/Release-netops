"""Backfill the provider endpoint allow-list from existing configured URLs."""

from __future__ import annotations

import json


VERSION = 166
NAME = "provider_endpoint_allowlist_backfill"


def upgrade(cursor, use_pg: bool) -> None:
    # m0165 owns the column.  Keep this migration harmless on a partially
    # upgraded legacy database so the normal migration runner can retry it.
    try:
        rows = cursor.execute(
            "SELECT id, provider_type, base_url, approved_endpoint_patterns_json FROM ai_provider"
        ).fetchall()
    except Exception:
        return

    for row in rows:
        provider_id, provider_type, base_url, raw_patterns = row
        if not base_url or str(provider_type or "").lower() in {"local", "ollama"}:
            continue
        try:
            current = raw_patterns if isinstance(raw_patterns, list) else json.loads(raw_patterns or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            current = []
        if isinstance(current, list) and any(str(item).strip() for item in current):
            continue
        cursor.execute(
            "UPDATE ai_provider SET approved_endpoint_patterns_json = ? WHERE id = ?",
            (json.dumps([str(base_url).rstrip("/")], ensure_ascii=False), provider_id),
        )


__all__ = ["VERSION", "NAME", "upgrade"]

