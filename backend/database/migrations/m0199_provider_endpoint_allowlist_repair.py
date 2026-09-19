"""Repair cloud Provider rows whose endpoint allowlist is still empty."""

from __future__ import annotations

import json
from urllib.parse import urlparse


VERSION = 199
NAME = "provider_endpoint_allowlist_repair"


def _patterns(raw_patterns) -> list[str]:
    if isinstance(raw_patterns, list):
        parsed = raw_patterns
    else:
        try:
            parsed = json.loads(raw_patterns or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if item is not None and str(item).strip()]


def upgrade(cursor, use_pg: bool) -> None:
    """Persist an exact configured URL for legacy cloud Provider rows.

    m0166 handled the rows that existed when it ran.  This repair also covers
    rows created later by older admin flows, while preserving any explicit
    allowlist and leaving local Providers untouched.
    """

    del use_pg
    rows = cursor.execute(
        "SELECT id, provider_type, base_url, approved_endpoint_patterns_json FROM ai_provider"
    ).fetchall()
    for provider_id, provider_type, base_url, raw_patterns in rows:
        normalized_type = str(provider_type or "").lower().replace("-", "_")
        normalized_base_url = str(base_url or "").strip().rstrip("/")
        parsed_base_url = urlparse(normalized_base_url)
        if (
            normalized_type in {"local", "ollama"}
            or parsed_base_url.scheme.lower() != "https"
            or not parsed_base_url.hostname
        ):
            continue
        if _patterns(raw_patterns):
            continue
        cursor.execute(
            "UPDATE ai_provider SET approved_endpoint_patterns_json = ? WHERE id = ?",
            (json.dumps([normalized_base_url], ensure_ascii=False), provider_id),
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Keep repaired allowlists; rollback requires an explicit data change."""

    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
