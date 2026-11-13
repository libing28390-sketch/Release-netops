"""Database and credential helpers for PAM RDP/VNC sessions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from core.crypto import decrypt_credential
from core.rbac import is_global_administrator
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from database import get_db_connection
from services.audit_service import log_audit_event
from services.rack_scope_service import allowed_resource_scope, enforce_loaded_resource


REMOTE_DESKTOP_PROTOCOLS = {"rdp", "vnc"}
RDP_SECURITY_MODES = {"any", "nla", "tls", "rdp"}
TICKET_TTL_SECONDS = 90
MAX_BATCH_ASSETS = 200


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def ticket_digest(ticket: str) -> str:
    return hashlib.sha256(str(ticket or "").encode("utf-8")).hexdigest()


def load_asset(conn, asset_id: str) -> dict:
    row = conn.execute(
        """SELECT pa.*, s.tenant_id AS site_tenant_id
             FROM physical_assets pa
             LEFT JOIN sites s ON s.id = pa.site_id
            WHERE pa.id = ?""",
        (asset_id,),
    ).fetchone()
    return dict(row) if row else {}


def enforce_asset_scope(user: dict, asset: dict, action: str = "view") -> None:
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if (
        not str(asset.get("site_id") or "").strip()
        and not is_global_administrator(user)
        and (
            (TENANT_ISOLATION_ENABLED and tenant_scope_for_user(user))
            or user.get("scope_mode") == "restricted"
        )
    ):
        raise HTTPException(status_code=404, detail="Asset not found")
    try:
        enforce_loaded_resource(user, asset, "asset", action)
    except HTTPException as exc:
        # Keep foreign-tenant and foreign-site asset IDs indistinguishable.
        if exc.status_code == 403:
            raise HTTPException(status_code=404, detail="Asset not found") from exc
        raise


def public_profile(row: Any) -> dict:
    profile = dict(row) if hasattr(row, "keys") else dict(row or {})
    return {
        "id": profile.get("id"),
        "asset_id": profile.get("asset_id"),
        "protocol": profile.get("protocol"),
        "profile_name": profile.get("profile_name") or "",
        "enabled": bool(profile.get("enabled")),
        "port": int(profile.get("port") or (3389 if profile.get("protocol") == "rdp" else 5900)),
        "normal_credential_id": profile.get("normal_credential_id") or "",
        "admin_credential_id": profile.get("admin_credential_id") or "",
        "rdp_domain": profile.get("rdp_domain") or "",
        "rdp_security_mode": profile.get("rdp_security_mode") or "nla",
        "rdp_cert_fingerprint": profile.get("rdp_cert_fingerprint") or "",
        "clipboard_enabled": bool(profile.get("clipboard_enabled")),
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }


def validate_credential_reference(
    conn,
    credential_id: str | None,
    *,
    protocol: str,
    access_level: str,
) -> None:
    if not credential_id:
        return
    row = conn.execute(
        """SELECT id, credential_type, account_role, username, encrypted_password
             FROM credentials WHERE id = ?""",
        (credential_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=422, detail="Credential reference is invalid")
    credential = dict(row)
    kind = str(credential.get("credential_type") or "").strip().lower()
    if kind.startswith("snmp") or kind in {"api_token", "ssh_key"}:
        raise HTTPException(status_code=422, detail="Credential type is not valid for remote desktop")
    role = str(credential.get("account_role") or "unbound").strip().lower()
    if role in {"normal", "admin"} and role != access_level:
        raise HTTPException(status_code=422, detail="Credential account role does not match access level")
    if not str(credential.get("encrypted_password") or "").strip():
        raise HTTPException(status_code=422, detail="Credential password is not configured")
    if protocol == "rdp" and not str(credential.get("username") or "").strip():
        raise HTTPException(status_code=422, detail="RDP credentials require a username")


def normalize_profile_payload(protocol: str, payload: dict) -> dict:
    normalized_protocol = str(protocol or "").strip().lower()
    if normalized_protocol not in REMOTE_DESKTOP_PROTOCOLS:
        raise HTTPException(status_code=422, detail="Protocol must be rdp or vnc")
    default_port = 3389 if normalized_protocol == "rdp" else 5900
    port = payload.get("port")
    try:
        normalized_port = default_port if port is None else int(port)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid remote desktop port") from exc
    if not 1 <= normalized_port <= 65535:
        raise HTTPException(status_code=422, detail="Remote desktop port must be between 1 and 65535")

    security_mode = str(payload.get("rdp_security_mode") or "nla").strip().lower()
    if security_mode not in RDP_SECURITY_MODES:
        raise HTTPException(status_code=422, detail="Unsupported RDP security mode")

    def credential_ref(key: str) -> str | None:
        value = str(payload.get(key) or "").strip()
        if len(value) > 200:
            raise HTTPException(status_code=422, detail="Credential reference is too long")
        return value or None

    profile_name = str(payload.get("profile_name") or "").strip()
    domain = str(payload.get("rdp_domain") or "").strip()
    cert_fingerprint = str(payload.get("rdp_cert_fingerprint") or "").strip()
    if len(profile_name) > 120 or len(domain) > 255 or len(cert_fingerprint) > 64:
        raise HTTPException(status_code=422, detail="Remote desktop profile field is too long")
    if cert_fingerprint and not re.fullmatch(r"[0-9A-Fa-f]{64}", cert_fingerprint):
        raise HTTPException(status_code=422, detail="RDP certificate fingerprint must be 64 hexadecimal characters")
    if any(ord(char) < 0x20 for char in profile_name + domain + cert_fingerprint):
        raise HTTPException(status_code=422, detail="Remote desktop profile field contains control characters")
    return {
        "protocol": normalized_protocol,
        "profile_name": profile_name or ("RDP" if normalized_protocol == "rdp" else "VNC"),
        "enabled": bool(payload.get("enabled", True)),
        "port": normalized_port,
        "normal_credential_id": credential_ref("normal_credential_id"),
        "admin_credential_id": credential_ref("admin_credential_id"),
        "rdp_domain": domain if normalized_protocol == "rdp" else "",
        "rdp_security_mode": security_mode if normalized_protocol == "rdp" else "nla",
        "rdp_cert_fingerprint": cert_fingerprint.upper() if normalized_protocol == "rdp" else "",
        "clipboard_enabled": bool(payload.get("clipboard_enabled", False)),
    }


def list_asset_profiles(conn, asset_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM asset_remote_desktop_profiles
             WHERE asset_id = ? ORDER BY protocol""",
        (asset_id,),
    ).fetchall()
    return [public_profile(row) for row in rows]


def save_asset_profile(conn, asset_id: str, protocol: str, payload: dict, actor: str) -> dict:
    normalized = normalize_profile_payload(protocol, payload)
    for level, key in (("normal", "normal_credential_id"), ("admin", "admin_credential_id")):
        validate_credential_reference(
            conn,
            normalized[key],
            protocol=normalized["protocol"],
            access_level=level,
        )
    now = utc_iso()
    existing = conn.execute(
        "SELECT id, created_at FROM asset_remote_desktop_profiles WHERE asset_id = ? AND protocol = ?",
        (asset_id, normalized["protocol"]),
    ).fetchone()
    profile_id = str(existing["id"]) if existing else f"rdp-{uuid.uuid4().hex}"
    created_at = existing["created_at"] if existing else now
    conn.execute(
        """INSERT INTO asset_remote_desktop_profiles
               (id, asset_id, protocol, profile_name, enabled, port,
                normal_credential_id, admin_credential_id, rdp_domain,
                rdp_security_mode, rdp_cert_fingerprint, clipboard_enabled, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (asset_id, protocol) DO UPDATE SET
                profile_name = EXCLUDED.profile_name,
                enabled = EXCLUDED.enabled,
                port = EXCLUDED.port,
                normal_credential_id = EXCLUDED.normal_credential_id,
                admin_credential_id = EXCLUDED.admin_credential_id,
                rdp_domain = EXCLUDED.rdp_domain,
                rdp_security_mode = EXCLUDED.rdp_security_mode,
                rdp_cert_fingerprint = EXCLUDED.rdp_cert_fingerprint,
                clipboard_enabled = EXCLUDED.clipboard_enabled,
                updated_at = EXCLUDED.updated_at""",
        (
            profile_id,
            asset_id,
            normalized["protocol"],
            normalized["profile_name"],
            normalized["enabled"],
            normalized["port"],
            normalized["normal_credential_id"],
            normalized["admin_credential_id"],
            normalized["rdp_domain"],
            normalized["rdp_security_mode"],
            normalized["rdp_cert_fingerprint"],
            normalized["clipboard_enabled"],
            created_at,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM asset_remote_desktop_profiles WHERE asset_id = ? AND protocol = ?",
        (asset_id, normalized["protocol"]),
    ).fetchone()
    return public_profile(row)


def list_scoped_profiles(conn, user: dict, asset_ids: list[str]) -> list[dict]:
    """Return only profiles whose parent asset is visible to the caller."""
    if len(asset_ids) > MAX_BATCH_ASSETS:
        raise HTTPException(status_code=422, detail="At most 200 assets may be requested")
    if not asset_ids:
        return []
    scope = allowed_resource_scope(conn, user, "asset", "view")
    clauses = ["pa.id = ANY(?)"]
    parameters: list[Any] = [asset_ids]
    if scope.site_ids is not None:
        if not scope.site_ids:
            return []
        clauses.append("pa.site_id = ANY(?)")
        parameters.append(list(scope.site_ids))
    if scope.tenant_id:
        clauses.append("s.tenant_id = ?")
        parameters.append(scope.tenant_id)
    rows = conn.execute(
        f"""SELECT p.*, pa.site_id, s.tenant_id AS site_tenant_id
              FROM asset_remote_desktop_profiles p
              JOIN physical_assets pa ON pa.id = p.asset_id
              LEFT JOIN sites s ON s.id = pa.site_id
             WHERE {' AND '.join(clauses)}
             ORDER BY p.asset_id, p.protocol""",
        parameters,
    ).fetchall()
    # The tenant/site/resource scope is compiled once above and applied by
    # the single profile query. Re-authorizing each returned row would open a
    # database connection per protocol profile and turn this bounded batch
    # endpoint into an N+1 query path.
    return [public_profile(row) for row in rows]


def _credential_for_ref(conn, credential_id: str) -> dict | None:
    if not credential_id:
        return None
    row = conn.execute(
        """SELECT id, credential_type, account_role, username, encrypted_password
             FROM credentials WHERE id = ?""",
        (credential_id,),
    ).fetchone()
    return dict(row) if row else None


def _usable_credential(credential: dict | None, protocol: str, access_level: str) -> tuple[str, str]:
    if not credential:
        raise HTTPException(status_code=422, detail="Configured remote desktop credential is unavailable")
    kind = str(credential.get("credential_type") or "").strip().lower()
    if kind.startswith("snmp") or kind in {"api_token", "ssh_key"}:
        raise HTTPException(status_code=422, detail="Configured credential cannot be used for remote desktop")
    account_role = str(credential.get("account_role") or "unbound").strip().lower()
    if account_role in {"normal", "admin"} and account_role != access_level:
        raise HTTPException(status_code=422, detail="Configured credential role does not match access level")
    username = str(credential.get("username") or "").strip()
    encrypted_password = str(credential.get("encrypted_password") or "")
    password = decrypt_credential(encrypted_password) or ""
    if not password:
        raise HTTPException(status_code=422, detail="Configured remote desktop password is unavailable")
    if protocol == "rdp" and not username:
        raise HTTPException(status_code=422, detail="RDP credentials require a username")
    return username, password


def resolve_remote_desktop_credentials(
    conn,
    asset: dict,
    profile: dict,
    protocol: str,
    access_level: str,
) -> tuple[str, str]:
    """Resolve profile credentials, inheriting the corresponding asset role only if unset."""
    explicit_ref = str(profile.get(f"{access_level}_credential_id") or "").strip()
    inherited_ref = ""
    if not explicit_ref:
        inherited_ref = str(asset.get(f"{access_level}_credential_id") or "").strip()
        if not inherited_ref:
            inherited_ref = str(asset.get("credential_id") or "").strip() if access_level == "normal" else ""
    credential_id = explicit_ref or inherited_ref
    if credential_id:
        credential = _credential_for_ref(conn, credential_id)
        # A reference that became stale must fail closed instead of silently
        # falling through to legacy asset fields.
        if not credential:
            raise HTTPException(status_code=422, detail="Configured remote desktop credential is unavailable")
        return _usable_credential(credential, protocol, access_level)

    # Keep inheritance aligned with the established Nexora vault resolver.
    # Device rows can own the normal/admin binding even when the physical
    # asset has no duplicate credential_id; the resolver also applies the
    # shared-vault versus legacy asset-cache rules used by PAM SSH.
    device_row = conn.execute(
        "SELECT * FROM devices WHERE asset_id = ? ORDER BY id LIMIT 1",
        (str(asset.get("id") or ""),),
    ).fetchone()
    if device_row:
        from services.vault_service import resolve_device_credentials

        resolved = resolve_device_credentials(dict(device_row))
        username = str(resolved.get(f"{access_level}_username") or "").strip()
        password = str(resolved.get(f"{access_level}_password") or "")
        if password:
            if protocol == "rdp" and not username:
                raise HTTPException(status_code=422, detail="RDP credentials require a username")
            # VNC servers often authenticate with a password alone.
            return username, password

    if access_level == "admin":
        username = str(asset.get("admin_username") or "").strip()
        raw_password = str(asset.get("admin_password") or "")
    else:
        username = str(asset.get("normal_username") or asset.get("username") or "").strip()
        raw_password = str(asset.get("normal_password") or asset.get("password") or "")
    password = decrypt_credential(raw_password) or ""
    if protocol == "rdp" and not username:
        raise HTTPException(status_code=422, detail="RDP credentials require a username")
    if not password:
        raise HTTPException(status_code=422, detail="Remote desktop password is not configured")
    return username, password


def build_session_ticket() -> tuple[str, str, datetime]:
    ticket = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(seconds=TICKET_TTL_SECONDS)
    return ticket, ticket_digest(ticket), expires


def build_session_id(protocol: str) -> str:
    return f"pam-{protocol}-{uuid.uuid4().hex}"


def valid_ticket_format(ticket: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{32,100}", str(ticket or "")))


def compare_ticket(stored_hash: str, provided_hash: str) -> bool:
    return bool(stored_hash) and hmac.compare_digest(stored_hash, provided_hash)


def recover_expired_remote_desktop_sessions(limit: int = 100) -> dict[str, int]:
    """Close expired tickets and leases left behind by a crashed proxy worker."""
    now = utc_now()
    now_iso = now.isoformat()
    conn = get_db_connection()
    result = {"attempted": 0, "closed": 0}
    try:
        rows = conn.execute(
            """SELECT id, asset_id, device_id, target_hostname, requester_username,
                      remote_desktop_protocol, access_level, status, connected_at,
                      recording_spool_path
                 FROM pam_sessions
                WHERE remote_desktop_protocol <> ''
                  AND ((status = 'pending' AND token_expires_at < ?)
                       OR (status IN ('connecting', 'active')
                           AND (remote_desktop_lease_until IS NULL OR remote_desktop_lease_until < ?)))
                ORDER BY created_at ASC
                LIMIT ? FOR UPDATE SKIP LOCKED""",
            (now_iso, now_iso, max(1, min(int(limit), 500))),
        ).fetchall()
        for row in rows:
            result["attempted"] += 1
            item = dict(row)
            was_pending = item.get("status") == "pending"
            reason = "ticket_expired" if was_pending else "worker_lease_expired"
            connected_at = item.get("connected_at")
            duration = 0
            if connected_at:
                try:
                    duration = max(0, int((now - datetime.fromisoformat(str(connected_at).replace("Z", "+00:00"))).total_seconds()))
                except (TypeError, ValueError):
                    duration = 0
            has_recording_path = bool(str(item.get("recording_spool_path") or "").strip())
            conn.execute(
                """UPDATE pam_sessions
                      SET status = ?, token_consumed = 1, closed_at = ?, close_reason = ?,
                          duration_seconds = ?, remote_desktop_recording_closed = TRUE,
                          remote_desktop_lease_until = NULL,
                          recording_status = CASE WHEN recording_spool_path <> '' THEN 'captured' ELSE 'not_started' END,
                          storage_status = CASE WHEN recording_spool_path <> '' THEN 'PENDING' ELSE storage_status END,
                          updated_at = ?
                    WHERE id = ? AND status = ?""",
                (
                    "error" if was_pending else "closed",
                    now_iso,
                    reason,
                    duration,
                    now_iso,
                    item["id"],
                    item["status"],
                ),
            )
            log_audit_event(
                event_type="pam.remote_desktop_session.expired",
                category="access",
                severity="warning",
                status="error" if was_pending else "closed",
                summary=f"PAM {str(item.get('remote_desktop_protocol') or '').upper()} session recovered after {reason}",
                actor_username=str(item.get("requester_username") or ""),
                target_type="asset",
                target_id=str(item.get("asset_id") or ""),
                target_name=str(item.get("target_hostname") or ""),
                device_id=str(item.get("device_id") or "") or None,
                details={
                    "session_id": str(item.get("id") or ""),
                    "protocol": str(item.get("remote_desktop_protocol") or ""),
                    "access_level": str(item.get("access_level") or "normal"),
                    "close_reason": reason,
                    "recording_pending": has_recording_path,
                },
                conn=conn,
            )
            result["closed"] += 1
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "MAX_BATCH_ASSETS",
    "REMOTE_DESKTOP_PROTOCOLS",
    "RDP_SECURITY_MODES",
    "TICKET_TTL_SECONDS",
    "allowed_resource_scope",
    "build_session_id",
    "build_session_ticket",
    "compare_ticket",
    "enforce_asset_scope",
    "list_asset_profiles",
    "list_scoped_profiles",
    "load_asset",
    "normalize_profile_payload",
    "public_profile",
    "recover_expired_remote_desktop_sessions",
    "resolve_remote_desktop_credentials",
    "save_asset_profile",
    "ticket_digest",
    "utc_iso",
    "utc_now",
    "valid_ticket_format",
]
