"""Persistence helpers shared by asset CRUD and the PAM Web API."""

from __future__ import annotations

import uuid
from collections.abc import Iterable


def _as_dict(profile):
    if hasattr(profile, "model_dump"):
        return profile.model_dump()
    return dict(profile)


def replace_asset_web_profiles(conn, asset_id: str, profiles: Iterable) -> list[dict]:
    """Replace an asset's Web entries inside the caller's transaction."""
    normalized: list[dict] = []
    seen: set[tuple[str, int, str]] = set()
    for profile in profiles or []:
        item = _as_dict(profile)
        scheme = str(item.get("scheme") or "https").lower()
        if scheme not in {"http", "https"}:
            raise ValueError("Web scheme must be http or https")
        port = int(item.get("port") or (443 if scheme == "https" else 80))
        if not 1 <= port <= 65535:
            raise ValueError("Web port must be between 1 and 65535")
        path = str(item.get("path") or "/")
        if not path.startswith("/") or path.startswith("//") or any(ord(char) < 0x20 for char in path):
            raise ValueError("Web path must be a relative path")
        key = (scheme, port, path)
        if key in seen:
            raise ValueError(f"Duplicate Web profile: {scheme}://:{port}{path}")
        seen.add(key)
        profile_id = str(item.get("id") or f"web-profile-{uuid.uuid4().hex[:12]}")
        normalized.append({
            "id": profile_id,
            "asset_id": asset_id,
            "profile_name": str(item.get("profile_name") or "Web management")[:100],
            "scheme": scheme,
            "port": port,
            "path": path,
            "enabled": 1 if item.get("enabled", True) else 0,
        })

    conn.execute("DELETE FROM asset_web_access_profiles WHERE asset_id = ?", (asset_id,))
    for item in normalized:
        conn.execute(
            """
            INSERT INTO asset_web_access_profiles
                (id, asset_id, profile_name, scheme, port, path, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"], item["asset_id"], item["profile_name"], item["scheme"],
                item["port"], item["path"], item["enabled"], _now(), _now(),
            ),
        )
    return normalized


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
