"""Persistence helpers shared by asset CRUD and the PAM Web API."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from core.crypto import encrypt_credential


def _as_dict(profile):
    if hasattr(profile, "model_dump"):
        return profile.model_dump()
    return dict(profile)


def replace_asset_web_profiles(conn, asset_id: str, profiles: Iterable) -> list[dict]:
    """Replace an asset's Web entries inside the caller's transaction."""
    existing_rows = conn.execute(
        """SELECT id, normal_password, admin_password
           FROM asset_web_access_profiles WHERE asset_id = ?""",
        (asset_id,),
    ).fetchall()
    existing_secrets = {str(row["id"]): dict(row) for row in existing_rows}
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
        credential_mode = str(item.get("credential_mode") or "inherit_asset").lower()
        if credential_mode not in {"inherit_asset", "independent"}:
            raise ValueError("Web credential mode must be inherit_asset or independent")
        credential_id = _resolve_credential_reference(conn, item.get("credential_id"))
        admin_credential_id = _resolve_credential_reference(conn, item.get("admin_credential_id"))
        previous = existing_secrets.get(profile_id, {})
        normal_password = item.get("normal_password")
        admin_password = item.get("admin_password")
        normalized.append({
            "id": profile_id,
            "asset_id": asset_id,
            "profile_name": str(item.get("profile_name") or "Web management")[:100],
            "scheme": scheme,
            "port": port,
            "path": path,
            "enabled": 1 if item.get("enabled", True) else 0,
            "credential_mode": credential_mode,
            "normal_username": str(item.get("normal_username") or "")[:255],
            "normal_password": (
                encrypt_credential(str(normal_password))
                if normal_password not in (None, "")
                else str(previous.get("normal_password") or "")
            ),
            "admin_username": str(item.get("admin_username") or "")[:255],
            "admin_password": (
                encrypt_credential(str(admin_password))
                if admin_password not in (None, "")
                else str(previous.get("admin_password") or "")
            ),
            "credential_id": credential_id,
            "admin_credential_id": admin_credential_id,
        })

    conn.execute("DELETE FROM asset_web_access_profiles WHERE asset_id = ?", (asset_id,))
    for item in normalized:
        conn.execute(
            """
            INSERT INTO asset_web_access_profiles
                (id, asset_id, profile_name, scheme, port, path, enabled,
                 credential_mode, normal_username, normal_password,
                 admin_username, admin_password, credential_id, admin_credential_id,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"], item["asset_id"], item["profile_name"], item["scheme"],
                item["port"], item["path"], item["enabled"], item["credential_mode"],
                item["normal_username"], item["normal_password"],
                item["admin_username"], item["admin_password"],
                item["credential_id"], item["admin_credential_id"], _now(), _now(),
            ),
        )
    return normalized


def _resolve_credential_reference(conn, value) -> str:
    reference = str(value or "").strip()
    if not reference:
        return ""
    row = conn.execute(
        "SELECT id FROM credentials WHERE id = ? OR credential_name = ?",
        (reference, reference),
    ).fetchone()
    if not row:
        raise ValueError(f"Web credential does not exist: {reference}")
    return str(row["id"])


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
