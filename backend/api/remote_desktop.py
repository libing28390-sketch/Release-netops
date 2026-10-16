"""Asset remote desktop profiles and the authenticated PAM Guacamole tunnel."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from core.rbac import require_permission
from core.tenant_policy import tenant_id_for_write
from database import get_db_connection
from services.audit_service import log_audit_event
from services.guacamole_service import (
    GuacamoleConnection,
    GuacamoleServiceError,
    build_connection_parameters,
    create_connection,
    release_authorization,
)
from services.pam_remote_desktop import (
    TICKET_TTL_SECONDS,
    build_session_id,
    build_session_ticket,
    enforce_asset_scope,
    list_asset_profiles,
    list_scoped_profiles,
    load_asset,
    resolve_remote_desktop_credentials,
    save_asset_profile,
    ticket_digest,
    utc_iso,
    utc_now,
    valid_ticket_format,
)


logger = logging.getLogger(__name__)
router = APIRouter()
ws_router = APIRouter()

REMOTE_RECORDING_SUFFIX = ".guac"
REMOTE_RECORDING_CONTENT_TYPE = "application/octet-stream"
REMOTE_DESKTOP_MAX_SECONDS = 8 * 60 * 60
REMOTE_DESKTOP_LEASE_SECONDS = 60
REMOTE_DESKTOP_LEASE_REFRESH_SECONDS = 10
REMOTE_DESKTOP_STATUS_POLL_SECONDS = 2
MAX_WS_FRAME_BYTES = 16 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _session_user_id(user: dict) -> str:
    return str(user.get("user_id") or user.get("id") or "").strip()


class RemoteDesktopProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_name: str = Field(default="", max_length=120)
    enabled: bool = True
    port: int | None = Field(default=None, ge=1, le=65535)
    normal_credential_id: str | None = Field(default=None, max_length=200)
    admin_credential_id: str | None = Field(default=None, max_length=200)
    rdp_domain: str = Field(default="", max_length=255)
    rdp_security_mode: Literal["any", "nla", "tls", "rdp"] = "nla"
    rdp_cert_fingerprint: str = Field(default="", max_length=64)
    clipboard_enabled: bool = False


class RemoteDesktopSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=200)
    protocol: Literal["rdp", "vnc"]
    access_level: Literal["normal", "admin"] = "normal"
    reason: str = Field(min_length=3, max_length=1000)
    fixed_pin: str | None = Field(default=None, max_length=16)
    mfa_code: str | None = Field(default=None, max_length=16)


@router.get("/assets/{asset_id}/remote-desktop-profiles")
def get_remote_desktop_profiles(
    asset_id: str,
    user=require_permission("asset", "view"),
):
    conn = get_db_connection()
    try:
        asset = load_asset(conn, asset_id)
        enforce_asset_scope(user, asset, "view")
        return {"success": True, "data": list_asset_profiles(conn, asset_id)}
    finally:
        conn.close()


@router.put("/assets/{asset_id}/remote-desktop-profiles/{protocol}")
def put_remote_desktop_profile(
    asset_id: str,
    protocol: Literal["rdp", "vnc"],
    payload: RemoteDesktopProfileInput,
    user=require_permission("asset", "update"),
):
    conn = get_db_connection()
    try:
        asset = load_asset(conn, asset_id)
        enforce_asset_scope(user, asset, "update")
        profile = save_asset_profile(conn, asset_id, protocol, payload.model_dump(), str(user.get("username") or ""))
        log_audit_event(
            event_type="asset.remote_desktop_profile.updated",
            category="access",
            severity="info",
            status="success",
            summary=f"Remote desktop profile updated for asset {asset_id}",
            actor_id=_session_user_id(user),
            actor_username=str(user.get("username") or ""),
            actor_role=str(user.get("role") or ""),
            target_type="asset",
            target_id=asset_id,
            target_name=str(asset.get("hostname") or asset_id),
            details={
                "profile_id": profile["id"],
                "protocol": profile["protocol"],
                "enabled": profile["enabled"],
                "port": profile["port"],
                "rdp_security_mode": profile["rdp_security_mode"],
            },
            conn=conn,
        )
        conn.commit()
        return {"success": True, "data": profile}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/pam/remote-desktop-profiles")
def get_batch_remote_desktop_profiles(
    asset_ids: str = Query(default="", max_length=12000),
    user=require_permission("asset", "view"),
):
    requested = list(dict.fromkeys(item.strip() for item in asset_ids.split(",") if item.strip()))
    if len(requested) > 200:
        raise HTTPException(status_code=422, detail="At most 200 assets may be requested")
    conn = get_db_connection()
    try:
        return {"success": True, "data": list_scoped_profiles(conn, user, requested)}
    finally:
        conn.close()


def _profile_for_session(conn, asset_id: str, protocol: str) -> dict:
    row = conn.execute(
        """SELECT * FROM asset_remote_desktop_profiles
             WHERE asset_id = ? AND protocol = ?""",
        (asset_id, protocol),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Remote desktop profile not found")
    profile = dict(row)
    if not bool(profile.get("enabled")):
        raise HTTPException(status_code=409, detail="Remote desktop profile is disabled")
    return profile


def _resolve_asset_host(asset: dict) -> str:
    host = str(asset.get("management_ip") or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="Asset has no management address configured")
    # Guacamole receives only a host and port from the database, never an URL
    # or any client-provided connection target.
    if any(char in host for char in "/?#@\r\n\t"):
        raise HTTPException(status_code=422, detail="Asset management address is invalid")
    if len(host) > 253:
        raise HTTPException(status_code=422, detail="Asset management address is invalid")
    try:
        import ipaddress

        ipaddress.ip_address(host)
    except ValueError:
        labels = host.rstrip(".").split(".")
        if not labels or any(
            not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in labels
        ):
            raise HTTPException(status_code=422, detail="Asset management address is invalid")
    return host


def _new_remote_recording_location(session_id: str) -> tuple[str, str]:
    configured_root = str(os.getenv("GUACAMOLE_RECORDING_DIR", "") or "").strip()
    if not configured_root:
        configured_root = str(Path(settings.STORAGE_SPOOL_ROOT).expanduser() / "remote_desktop_recordings")
    root = Path(configured_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = (root / session_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Recording path configuration is invalid") from exc
    directory.mkdir(mode=0o700, parents=False, exist_ok=True)
    if directory.is_symlink():
        raise HTTPException(status_code=500, detail="Recording path configuration is invalid")
    spool_path = directory / f"{session_id}{REMOTE_RECORDING_SUFFIX}"
    # guacd sees the same shared volume at /recordings while the backend sees
    # its configured mount path, so only the server-generated session suffix
    # is interpolated into the guacd path.
    guacd_root = str(os.getenv("GUACAMOLE_GUACD_RECORDING_DIR", "/recordings") or "/recordings").rstrip("/")
    if not guacd_root.startswith("/") or ".." in Path(guacd_root).parts:
        raise HTTPException(status_code=500, detail="Recording path configuration is invalid")
    return str(spool_path), f"{guacd_root}/{session_id}"


def create_remote_desktop_session(payload: RemoteDesktopSessionInput, user: dict) -> dict:
    username = str(user.get("username") or "").strip()
    requester_id = _session_user_id(user)
    if not username or not requester_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A session reason is required")
    if payload.access_level == "admin":
        if not payload.fixed_pin or not payload.mfa_code:
            raise HTTPException(status_code=403, detail="Privileged remote desktop access requires MFA")
        # Reuse the PAM PIN + TOTP verifier; do not trust role labels or UI state.
        from api.pam import _verify_mfa_totp

        verified, message = _verify_mfa_totp(username, payload.fixed_pin, payload.mfa_code)
        if not verified:
            raise HTTPException(status_code=403, detail=message)

    conn = get_db_connection()
    try:
        asset = load_asset(conn, payload.asset_id)
        enforce_asset_scope(user, asset, "view")
        profile = _profile_for_session(conn, payload.asset_id, payload.protocol)
        login_username, _resolved_password = resolve_remote_desktop_credentials(
            conn, asset, profile, payload.protocol, payload.access_level
        )  # Validate the selected role before issuing a ticket; never retain the password.
        _resolved_password = ""

        session_id = build_session_id(payload.protocol)
        ticket, ticket_hash, expires = build_session_ticket()
        target_host = _resolve_asset_host(asset)
        now = utc_iso()
        device_row = conn.execute(
            "SELECT id FROM devices WHERE asset_id = ? ORDER BY id LIMIT 1",
            (payload.asset_id,),
        ).fetchone()
        device_id = str(device_row["id"] or "") if device_row else ""
        tenant_id = tenant_id_for_write(user=user)
        target_name = str(asset.get("hostname") or target_host)
        conn.execute(
            """INSERT INTO pam_sessions (
                    id, tenant_id, asset_id, device_id, requester_username, access_level,
                    session_kind, login_username, connect_method, target_ip, target_port,
                    target_hostname, status, session_token, token_expires_at, token_consumed,
                    remote_desktop_protocol, remote_desktop_profile_id,
                    remote_desktop_ticket_hash, remote_desktop_requester_id,
                    remote_desktop_recording_closed, recording_status, storage_status,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'remote_desktop', ?, 'web', ?, ?, ?,
                    'pending', NULL, ?, 0, ?, ?, ?, ?, FALSE, 'not_started', 'LEGACY', ?, ?
                )""",
            (
                session_id,
                tenant_id,
                payload.asset_id,
                device_id,
                username,
                payload.access_level,
                login_username,
                target_host,
                int(profile["port"]),
                target_name,
                expires.isoformat(),
                payload.protocol,
                str(profile["id"]),
                ticket_hash,
                requester_id,
                now,
                now,
            ),
        )
        log_audit_event(
            event_type="pam.remote_desktop_session.created",
            category="access",
            severity="warning" if payload.access_level == "admin" else "info",
            status="open",
            summary=f"PAM {payload.protocol.upper()} session requested for {target_name}",
            actor_id=requester_id,
            actor_username=username,
            actor_role=str(user.get("role") or ""),
            target_type="asset",
            target_id=payload.asset_id,
            target_name=target_name,
            device_id=device_id or None,
            details={
                "session_id": session_id,
                "protocol": payload.protocol,
                "profile_id": str(profile["id"]),
                "access_level": payload.access_level,
                "reason": reason,
            },
            conn=conn,
        )
        conn.commit()
        return {
            "session_id": session_id,
            "session_token": ticket,
            "expires_at": expires.isoformat(),
            "protocol": payload.protocol,
            "connect": {"ws_url": f"/api/pam/remote-desktop-ws/{ticket}"},
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/pam/remote-desktop-sessions")
def post_remote_desktop_session(
    payload: RemoteDesktopSessionInput,
    user=require_permission("asset", "view"),
):
    return create_remote_desktop_session(payload, user)


def _same_origin(websocket: WebSocket) -> bool:
    origin = str(websocket.headers.get("origin") or "").strip()
    if not origin:
        return False
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return False
    request_host = str(
        websocket.headers.get("x-forwarded-host")
        or websocket.headers.get("host")
        or ""
    ).split(",", 1)[0].strip().lower()
    forwarded_proto = str(websocket.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    expected_scheme = forwarded_proto if forwarded_proto in {"http", "https"} else (
        "https" if websocket.url.scheme == "wss" else "http"
    )
    origin_host = parsed.netloc.lower()
    if origin_host == request_host and parsed.scheme == expected_scheme:
        return True
    # An explicit same-origin deployment allowlist supports TLS termination
    # where forwarded host headers are deliberately rewritten.
    configured = [item.strip().rstrip("/").lower() for item in os.getenv("CORS_ORIGINS", "").split(",") if item.strip()]
    return origin.rstrip("/").lower() in configured and "*" not in configured


def _user_for_ticket(conn, requester_id: str) -> dict:
    row = conn.execute(
        """SELECT id, username, role, role_profile, tenant_id, scope_mode, status
             FROM users WHERE id = ?""",
        (requester_id,),
    ).fetchone()
    if not row or str(row["status"] or "").strip().lower() != "active":
        raise HTTPException(status_code=404, detail="Remote desktop ticket is invalid")
    return {
        "id": str(row["id"]),
        "user_id": str(row["id"]),
        "username": str(row["username"] or ""),
        "role": str(row["role"] or ""),
        "role_profile": str(row["role_profile"] or ""),
        "tenant_id": str(row["tenant_id"] or ""),
        "scope_mode": str(row["scope_mode"] or "legacy"),
    }


def _claim_ticket(ticket: str, lease_owner: str) -> dict:
    digest = ticket_digest(ticket)
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT * FROM pam_sessions
                 WHERE session_kind = 'remote_desktop'
                   AND remote_desktop_ticket_hash = ?
                 FOR UPDATE""",
            (digest,),
        ).fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Remote desktop ticket is invalid")
        session = dict(row)
        try:
            expires = datetime.fromisoformat(str(session.get("token_expires_at") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=401, detail="Remote desktop ticket is invalid") from exc
        if int(session.get("token_consumed") or 0) != 0 or expires <= _now() or session.get("status") != "pending":
            conn.rollback()
            raise HTTPException(status_code=409, detail="Remote desktop ticket was consumed or expired")

        user = _user_for_ticket(conn, str(session.get("remote_desktop_requester_id") or ""))
        asset = load_asset(conn, str(session.get("asset_id") or ""))
        try:
            enforce_asset_scope(user, asset, "view")
        except HTTPException as exc:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Remote desktop ticket is invalid") from exc
        profile = conn.execute(
            """SELECT * FROM asset_remote_desktop_profiles
                 WHERE id = ? AND asset_id = ? AND protocol = ? FOR UPDATE""",
            (
                str(session.get("remote_desktop_profile_id") or ""),
                str(session.get("asset_id") or ""),
                str(session.get("remote_desktop_protocol") or ""),
            ),
        ).fetchone()
        if not profile or not bool(profile["enabled"]):
            conn.rollback()
            raise HTTPException(status_code=409, detail="Remote desktop profile is disabled")
        profile = dict(profile)
        protocol = str(session.get("remote_desktop_protocol") or "")
        access_level = str(session.get("access_level") or "normal")
        username, password = resolve_remote_desktop_credentials(conn, asset, profile, protocol, access_level)
        now = _now()
        updated = conn.execute(
            """UPDATE pam_sessions
                  SET token_consumed = 1,
                      status = 'connecting',
                      remote_desktop_lease_owner = ?,
                      remote_desktop_lease_until = ?,
                      last_heartbeat_at = ?,
                      updated_at = ?
                WHERE id = ? AND token_consumed = 0 AND status = 'pending'
                  AND remote_desktop_ticket_hash = ? AND token_expires_at > ?""",
            (
                lease_owner,
                (now + timedelta(seconds=REMOTE_DESKTOP_LEASE_SECONDS)).isoformat(),
                now.isoformat(),
                now.isoformat(),
                session["id"],
                digest,
                now.isoformat(),
            ),
        )
        if getattr(updated, "rowcount", 0) != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Remote desktop ticket was consumed or expired")
        conn.commit()
        return {
            "session": session,
            "asset": asset,
            "profile": profile,
            "user": user,
            "username": username,
            "password": password,
            "protocol": protocol,
            "access_level": access_level,
            "target_host": _resolve_asset_host(asset),
            "lease_owner": lease_owner,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _persist_recording_path(session_id: str, path: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE pam_sessions
                  SET recording_spool_path = ?, recording_status = 'recording',
                      storage_status = 'PENDING', storage_error = '', updated_at = ?
                WHERE id = ? AND session_kind = 'remote_desktop'""",
            (path, utc_iso(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


def _store_guacamole_connection(session_id: str, lease_owner: str, connection: GuacamoleConnection) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE pam_sessions SET remote_desktop_guac_id = ?, updated_at = ?
                 WHERE id = ? AND remote_desktop_lease_owner = ?
                   AND status IN ('connecting', 'active')""",
            (connection.connection_id, utc_iso(), session_id, lease_owner),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_session_active(session_id: str, lease_owner: str) -> bool:
    conn = get_db_connection()
    try:
        updated = conn.execute(
            """UPDATE pam_sessions
                  SET status = 'active', connected_at = COALESCE(connected_at, ?),
                      closed_at = NULL, close_reason = '', duration_seconds = 0,
                      last_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND remote_desktop_lease_owner = ? AND status = 'connecting'""",
            (utc_iso(), utc_iso(), utc_iso(), session_id, lease_owner),
        )
        conn.commit()
        return getattr(updated, "rowcount", 0) == 1
    finally:
        conn.close()


def _heartbeat_and_check(session_id: str, lease_owner: str, refresh: bool) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT status, remote_desktop_lease_owner
                 FROM pam_sessions WHERE id = ?""",
            (session_id,),
        ).fetchone()
        if not row or row["remote_desktop_lease_owner"] != lease_owner or row["status"] not in {"connecting", "active"}:
            return False
        if refresh:
            now = _now()
            conn.execute(
                """UPDATE pam_sessions SET remote_desktop_lease_until = ?, last_heartbeat_at = ?, updated_at = ?
                     WHERE id = ? AND remote_desktop_lease_owner = ? AND status IN ('connecting', 'active')""",
                (
                    (now + timedelta(seconds=REMOTE_DESKTOP_LEASE_SECONDS)).isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                    session_id,
                    lease_owner,
                ),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def _finalize_session_state(
    session_id: str,
    lease_owner: str,
    *,
    reason: str,
    connected: bool,
    recording_path: str,
    recording_ready: bool,
) -> None:
    now = _now()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT status, connected_at, close_reason FROM pam_sessions WHERE id = ?""",
            (session_id,),
        ).fetchone()
        if not row:
            return
        connected_at = row["connected_at"]
        duration = 0
        if connected_at:
            try:
                duration = max(0, int((now - datetime.fromisoformat(str(connected_at).replace("Z", "+00:00"))).total_seconds()))
            except (TypeError, ValueError):
                duration = 0
        status = str(row["status"] or "")
        if status not in {"closed", "error"}:
            status = "closed" if connected else "error"
        close_reason = str(row["close_reason"] or "") or reason[:120]
        if recording_path:
            if recording_ready:
                conn.execute(
                    """UPDATE pam_sessions
                          SET status = ?, closed_at = ?, close_reason = ?, duration_seconds = ?,
                              remote_desktop_recording_closed = TRUE,
                              recording_spool_path = ?, recording_status = 'captured',
                              storage_status = 'PENDING', storage_error = '',
                              remote_desktop_lease_until = NULL, updated_at = ?
                        WHERE id = ? AND remote_desktop_lease_owner = ?""",
                    (status, now.isoformat(), close_reason, duration, recording_path, now.isoformat(), session_id, lease_owner),
                )
            else:
                conn.execute(
                    """UPDATE pam_sessions
                          SET status = ?, closed_at = ?, close_reason = ?, duration_seconds = ?,
                              remote_desktop_recording_closed = TRUE,
                              recording_spool_path = ?, recording_status = 'captured',
                              storage_status = 'PENDING', storage_error = '',
                              storage_updated_at = ?, remote_desktop_lease_until = NULL, updated_at = ?
                        WHERE id = ? AND remote_desktop_lease_owner = ?""",
                    (status, now.isoformat(), close_reason, duration, recording_path, now.isoformat(), now.isoformat(), session_id, lease_owner),
                )
        else:
            conn.execute(
                """UPDATE pam_sessions
                      SET status = ?, closed_at = ?, close_reason = ?, duration_seconds = ?,
                          remote_desktop_recording_closed = TRUE, recording_status = 'not_started',
                          remote_desktop_lease_until = NULL, updated_at = ?
                    WHERE id = ? AND remote_desktop_lease_owner = ?""",
                (status, now.isoformat(), close_reason, duration, now.isoformat(), session_id, lease_owner),
            )
        conn.commit()
    finally:
        conn.close()


def _recording_file_ready(path: str) -> bool:
    try:
        target = Path(path)
        if target.is_symlink() or not target.is_file():
            return False
        return target.stat().st_size > 0
    except OSError:
        return False


async def _wait_for_recording_close(path: str, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    last: tuple[int, int] | None = None
    stable_checks = 0
    while time.monotonic() < deadline:
        try:
            stat = await asyncio.to_thread(Path(path).stat)
            current = (int(stat.st_size), int(stat.st_mtime_ns))
            if stat.st_size > 0 and current == last:
                stable_checks += 1
                if stable_checks >= 2:
                    return True
            else:
                stable_checks = 0
            last = current
        except OSError:
            last = None
            stable_checks = 0
        await asyncio.sleep(0.4)
    return False


async def _finalize_recording_if_ready(session_id: str, spool_path: str) -> None:
    if not spool_path or not await _wait_for_recording_close(spool_path):
        return
    from services.pam_recording_storage import finalize_pam_recording

    await asyncio.to_thread(
        finalize_pam_recording,
        session_id,
        spool_path,
        content_type=REMOTE_RECORDING_CONTENT_TYPE,
    )


def _parse_instruction_name(value: str) -> set[str]:
    """Extract complete Guacamole instruction names from one protocol frame."""
    names: set[str] = set()
    cursor = 0
    frame = value
    while cursor < len(frame):
        elements: list[str] = []
        while cursor < len(frame):
            separator = frame.find(".", cursor)
            if separator < 0 or not frame[cursor:separator].isdigit():
                return names
            try:
                length = int(frame[cursor:separator])
            except ValueError:
                return names
            cursor = separator + 1
            end = cursor + length
            if end > len(frame):
                return names
            elements.append(frame[cursor:end])
            cursor = end
            if cursor >= len(frame):
                return names
            delimiter = frame[cursor]
            cursor += 1
            if delimiter == ";":
                if elements:
                    names.add(elements[0])
                break
            if delimiter != ",":
                return names
    return names


_DIAGNOSTIC_GUACAMOLE_INSTRUCTIONS = frozenset({
    "ack",
    "args",
    "audio",
    "connect",
    "disconnect",
    "error",
    "image",
    "nop",
    "ready",
    "select",
    "size",
    "sync",
    "timezone",
    "video",
})


def _record_instruction_diagnostics(counts: dict[str, int], value: str) -> None:
    """Record only known Guacamole opcodes; never retain protocol arguments."""
    for name in _parse_instruction_name(value):
        label = "internal" if not name else (
            name if name in _DIAGNOSTIC_GUACAMOLE_INSTRUCTIONS else "other"
        )
        counts[label] = counts.get(label, 0) + 1


def _is_interactive_session_instruction(instruction_names: set[str]) -> bool:
    """Recognize Guac readiness or the first server screen synchronization."""
    return bool({"ready", "sync"} & instruction_names)


def _supports_guacamole_subprotocol(header_value: str | None) -> bool:
    """Return whether the WebSocket client requested the required subprotocol."""
    return "guacamole" in {
        protocol.strip()
        for protocol in str(header_value or "").split(",")
        if protocol.strip()
    }


async def _send_client_error(websocket: WebSocket, status: int, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "status": status, "message": message})
    except Exception:
        pass


async def _proxy_tunnel(websocket: WebSocket, claimed: dict, lease_owner: str) -> None:
    session = claimed["session"]
    asset = claimed["asset"]
    profile = claimed["profile"]
    protocol = claimed["protocol"]
    session_id = str(session["id"])
    username = str(claimed["username"] or "")
    password = str(claimed["password"] or "")
    target_host = str(claimed["target_host"])
    target_port = int(profile["port"])
    spool_path = ""
    connection: GuacamoleConnection | None = None
    upstream = None
    ready_event = asyncio.Event()
    client_task: asyncio.Task | None = None
    server_task: asyncio.Task | None = None
    relay_started = False
    close_reason = "client_disconnect"
    error: Exception | None = None
    client_instruction_counts: dict[str, int] = {}
    server_instruction_counts: dict[str, int] = {}
    client_frame_count = 0
    server_frame_count = 0
    try:
        spool_path, guac_recording_dir = _new_remote_recording_location(session_id)
        parameters = build_connection_parameters(
            protocol=protocol,
            hostname=target_host,
            port=target_port,
            username=username,
            password=password,
            profile=profile,
            guac_recording_dir=guac_recording_dir,
            recording_name=session_id,
        )
        if protocol == "rdp":
            logger.info(
                "Remote desktop session %s: RDP certificate fingerprint pin %s",
                session_id,
                "configured" if parameters.get("cert-fingerprints") else "not configured",
            )
        connection = await create_connection(
            session_id=session_id,
            protocol=protocol,
            parameters=parameters,
        )
        await asyncio.to_thread(_persist_recording_path, session_id, spool_path)
        await asyncio.to_thread(_store_guacamole_connection, session_id, lease_owner, connection)

        try:
            upstream = await _connect_guacamole_tunnel(connection)
        except Exception as exc:
            raise GuacamoleServiceError("GUACAMOLE_TUNNEL_FAILED") from exc

        if not _supports_guacamole_subprotocol(
            websocket.headers.get("sec-websocket-protocol")
        ):
            raise RuntimeError("REMOTE_DESKTOP_SUBPROTOCOL_REQUIRED")
        await websocket.accept(subprotocol="guacamole")
        relay_started = True
        opened_at = time.monotonic()
        last_refresh = 0.0
        session_active = False

        async def client_to_guacamole() -> None:
            nonlocal client_frame_count
            while True:
                incoming = await websocket.receive()
                if incoming.get("type") == "websocket.disconnect":
                    return
                data = incoming.get("text")
                if data is None:
                    data = incoming.get("bytes")
                if data is None:
                    continue
                if len(data) > MAX_WS_FRAME_BYTES:
                    raise RuntimeError("REMOTE_DESKTOP_FRAME_TOO_LARGE")
                client_frame_count += 1
                if isinstance(data, str):
                    _record_instruction_diagnostics(client_instruction_counts, data)
                await upstream.send(data)

        async def guacamole_to_client() -> None:
            nonlocal session_active, server_frame_count
            async for message in upstream:
                server_frame_count += 1
                diagnostic_message: str | None = None
                if isinstance(message, str):
                    diagnostic_message = message
                elif isinstance(message, bytes):
                    try:
                        diagnostic_message = message.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                if diagnostic_message is not None:
                    instruction_names = _parse_instruction_name(diagnostic_message)
                    _record_instruction_diagnostics(server_instruction_counts, diagnostic_message)
                    if _is_interactive_session_instruction(instruction_names) and not session_active:
                        session_active = await asyncio.to_thread(_mark_session_active, session_id, lease_owner)
                        ready_event.set()
                if isinstance(message, str):
                    await websocket.send_text(message)
                else:
                    await websocket.send_bytes(message)

        client_task = asyncio.create_task(client_to_guacamole(), name=f"rdp-client-{session_id}")
        server_task = asyncio.create_task(guacamole_to_client(), name=f"rdp-guac-{session_id}")
        deadline = opened_at + REMOTE_DESKTOP_MAX_SECONDS
        while True:
            if client_task.done() or server_task.done():
                for completed in (client_task, server_task):
                    if completed.done() and not completed.cancelled():
                        try:
                            completed.result()
                        except WebSocketDisconnect:
                            pass
                        except Exception as exc:
                            error = exc
                close_reason = "upstream_closed" if server_task.done() else "client_disconnect"
                break
            if time.monotonic() >= deadline:
                close_reason = "maximum_duration"
                break
            current = time.monotonic()
            if current - last_refresh >= REMOTE_DESKTOP_LEASE_REFRESH_SECONDS:
                alive = await asyncio.to_thread(
                    _heartbeat_and_check, session_id, lease_owner, True
                )
                if not alive:
                    close_reason = "session_revoked"
                    break
                last_refresh = current
            await asyncio.sleep(REMOTE_DESKTOP_STATUS_POLL_SECONDS)

        if not ready_event.is_set() and error is None:
            try:
                await asyncio.wait_for(ready_event.wait(), timeout=20)
            except asyncio.TimeoutError:
                error = RuntimeError("REMOTE_DESKTOP_CONNECT_TIMEOUT")
                close_reason = "connect_timeout"
    except Exception as exc:
        error = exc
        if isinstance(exc, GuacamoleServiceError):
            close_reason = exc.code.lower()
        else:
            close_reason = "remote_desktop_error"
    finally:
        for task in (client_task, server_task):
            if task and not task.done():
                task.cancel()
        for task in (client_task, server_task):
            if task:
                try:
                    await task
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception:
                    pass
        if upstream is not None:
            try:
                await upstream.close(code=1000, reason="session closed")
            except Exception:
                pass
        if connection is not None:
            await release_authorization(connection)

        recording_ready = False
        if spool_path and relay_started:
            recording_ready = await _wait_for_recording_close(spool_path)
        await asyncio.to_thread(
            _finalize_session_state,
            session_id,
            lease_owner,
            reason=close_reason if error is None else "connection_error",
            connected=ready_event.is_set(),
            recording_path=spool_path if relay_started else "",
            recording_ready=recording_ready,
        )
        if recording_ready:
            await _finalize_recording_if_ready(session_id, spool_path)
        if error is not None:
            if isinstance(error, GuacamoleServiceError):
                safe_message = "Remote desktop gateway could not establish the session"
            elif str(error) == "REMOTE_DESKTOP_CONNECT_TIMEOUT":
                safe_message = "Remote desktop connection timed out"
            elif str(error) == "REMOTE_DESKTOP_FRAME_TOO_LARGE":
                safe_message = "Remote desktop message exceeded the allowed size"
            else:
                safe_message = "Remote desktop connection failed"
            if relay_started:
                await _send_client_error(websocket, 519, safe_message)
                try:
                    await websocket.close(code=1011, reason=safe_message)
                except Exception:
                    pass
        if relay_started and (error is not None or not ready_event.is_set()):
            logger.warning(
                "Remote desktop session %s tunnel handshake diagnostics: "
                "client_frames=%s client_opcodes=%s server_frames=%s server_opcodes=%s ready=%s",
                session_id,
                client_frame_count,
                sorted(client_instruction_counts.items()),
                server_frame_count,
                sorted(server_instruction_counts.items()),
                ready_event.is_set(),
            )
        if password:
            password = ""
        if username:
            username = ""
        try:
            await asyncio.to_thread(_audit_remote_desktop_closed, session_id, close_reason, error)
        except Exception:
            logger.warning("Remote desktop close audit write failed for session %s", session_id)


def _guacamole_origin(websocket_url: str) -> str:
    parsed = urlsplit(websocket_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{scheme}://{parsed.netloc}"


async def _connect_guacamole_tunnel(connection: GuacamoleConnection):
    """Connect directly to the internal Guacamole service, bypassing HTTP proxies."""
    return await websockets.connect(
        connection.websocket_url,
        subprotocols=["guacamole"],
        origin=_guacamole_origin(connection.websocket_url),
        proxy=None,
        open_timeout=10,
        close_timeout=3,
        max_size=MAX_WS_FRAME_BYTES,
        ping_interval=20,
        ping_timeout=20,
    )


def _audit_remote_desktop_closed(session_id: str, reason: str, error: Exception | None) -> None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT asset_id, device_id, target_hostname, requester_username, access_level, remote_desktop_protocol FROM pam_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return
        protocol = str(row["remote_desktop_protocol"] or "")
        log_audit_event(
            event_type="pam.remote_desktop_session.closed" if error is None else "pam.remote_desktop_session.failed",
            category="access",
            severity="warning" if error is not None or reason in {"admin_kill", "session_revoked"} else "info",
            status="closed" if error is None else "error",
            summary=f"PAM {protocol.upper()} session {'closed' if error is None else 'failed'} for session {session_id}",
            actor_username=str(row["requester_username"] or ""),
            target_type="asset",
            target_id=str(row["asset_id"] or ""),
            target_name=str(row["target_hostname"] or ""),
            device_id=str(row["device_id"] or "") or None,
            details={
                "session_id": session_id,
                "protocol": protocol,
                "access_level": str(row["access_level"] or "normal"),
                "close_reason": reason,
                "error_code": getattr(error, "code", "REMOTE_DESKTOP_ERROR") if error else "",
            },
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()


@ws_router.websocket("/pam/remote-desktop-ws/{ticket}")
async def remote_desktop_websocket(websocket: WebSocket, ticket: str):
    if not _same_origin(websocket) or not valid_ticket_format(ticket):
        await websocket.close(code=1008, reason="Invalid remote desktop session")
        return
    lease_owner = secrets.token_urlsafe(18)
    try:
        claimed = await asyncio.to_thread(_claim_ticket, ticket, lease_owner)
    except HTTPException as exc:
        await websocket.close(code=1008, reason="Remote desktop ticket is invalid or expired")
        return
    try:
        await _proxy_tunnel(websocket, claimed, lease_owner)
    finally:
        # Clear only this worker's lease. Persisted session state remains the
        # cross-worker authority used by kill polling and stale-lease repair.
        conn = get_db_connection()
        try:
            conn.execute(
                """UPDATE pam_sessions SET remote_desktop_lease_until = NULL, updated_at = ?
                     WHERE id = ? AND remote_desktop_lease_owner = ?""",
                (utc_iso(), claimed["session"]["id"], lease_owner),
            )
            conn.commit()
        finally:
            conn.close()


__all__ = [
    "RemoteDesktopProfileInput",
    "RemoteDesktopSessionInput",
    "create_remote_desktop_session",
    "get_batch_remote_desktop_profiles",
    "get_remote_desktop_profiles",
    "post_remote_desktop_session",
    "put_remote_desktop_profile",
    "remote_desktop_websocket",
    "router",
    "ws_router",
]
