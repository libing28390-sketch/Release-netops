"""PAM control plane for user-operated HTTP(S) asset sessions.

This API deliberately does not resolve or return device credentials.  It only
authorizes an asset entry point and hands a short-lived, single-use token to a
trusted workstation Agent.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from database import get_db_connection
from schemas.web import WebSessionCreateInput, WebSessionExchangeInput, WebSessionStatusInput
from services.audit_service import log_audit_event


router = APIRouter()
TOKEN_TTL_MINUTES = 10
MAX_RECORDING_BYTES = 50 * 1024 * 1024
_RECORDING_TYPES = {
    ".gif": "image/gif",
    ".apng": "image/apng",
    ".mp4": "video/mp4",
    ".zip": "application/zip",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _expires_at(minutes: int = TOKEN_TTL_MINUTES) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def _authenticated_requester(request: Request) -> dict:
    from api.users import validate_session_token

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    session = validate_session_token(token)
    if not session or not session.get("username"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


def _target_url(ip: str, scheme: str, port: int, path: str) -> str:
    scheme = str(scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="Web scheme must be http or https")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid Web port") from exc
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=422, detail="Invalid Web port")
    path = str(path or "/").strip()
    if not path.startswith("/") or any(ord(char) < 0x20 for char in path):
        raise HTTPException(status_code=422, detail="Invalid Web path")
    host = str(ip or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="Asset has no management IP configured")
    try:
        parsed = ipaddress.ip_address(host)
        if parsed.version == 6:
            host = f"[{host}]"
    except ValueError:
        # Existing assets may use an internal management DNS name.  Keep it
        # constrained to a hostname rather than accepting arbitrary URL text.
        if any(char in host for char in "/?#@"):
            raise HTTPException(status_code=422, detail="Invalid asset management address")
    default_port = 443 if scheme == "https" else 80
    authority = host if port == default_port else f"{host}:{port}"
    return f"{scheme}://{authority}{path}"


def _callback_session(conn, session_id: str, callback_token: str, agent_id: str = "") -> dict:
    """Load and authenticate a Web session callback without exposing secrets."""
    row = conn.execute(
        """SELECT id, agent_id, agent_token_hash, status, connected_at, created_at
             FROM pam_sessions WHERE id = ? AND session_kind = 'device_web'""",
        (session_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Web session not found")
    session = dict(row)
    supplied_hash = hashlib.sha256(str(callback_token or "").encode("utf-8")).hexdigest()
    if not session.get("agent_token_hash") or not hmac.compare_digest(
        str(session["agent_token_hash"]), supplied_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid Agent callback token")
    stored_agent = str(session.get("agent_id") or "")
    supplied_agent = str(agent_id or "")[:128]
    if stored_agent and (not supplied_agent or not hmac.compare_digest(stored_agent, supplied_agent)):
        raise HTTPException(status_code=401, detail="Invalid Agent identity")
    return session


@router.post("/pam/web-sessions")
def create_web_session(payload: WebSessionCreateInput, request: Request):
    requester = _authenticated_requester(request)
    tenant_id = str(requester.get("tenant_id") or "tenant-default")
    username = str(requester.get("username") or "unknown")
    now = _now()

    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT pa.id AS asset_id, pa.hostname, pa.management_ip, pa.asset_type,
                      d.id AS device_id,
                      wp.id AS web_profile_id, wp.profile_name, wp.scheme, wp.port, wp.path, wp.enabled
               FROM physical_assets pa
               JOIN asset_web_access_profiles wp ON wp.asset_id = pa.id
               LEFT JOIN devices d ON d.asset_id = pa.id
               WHERE pa.id = ? AND wp.id = ?""",
            (payload.asset_id, payload.web_profile_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Asset Web profile not found")
        target = dict(row)
        if not bool(target.get("enabled")):
            raise HTTPException(status_code=409, detail="Asset Web profile is disabled")

        # Validate all target components before creating durable audit rows.
        _target_url(
            target.get("management_ip") or "",
            str(target.get("scheme") or "https"),
            int(target.get("port") or 443),
            str(target.get("path") or "/"),
        )

        request_id = f"pam-web-req-{uuid.uuid4().hex[:12]}"
        session_id = f"pam-web-{uuid.uuid4().hex[:12]}"
        session_token = f"pam-web-token-{secrets.token_urlsafe(32)}"
        expires_at = _expires_at()

        # In phase one normal/admin are audit labels only.  Both are approved
        # immediately; stricter workflows can be layered on later without
        # changing the session contract.
        conn.execute(
            """INSERT INTO pam_access_requests
                   (id, asset_id, device_id, requester_user_id, requester_username,
                    access_level, session_kind, web_profile_id, reason, status,
                    expires_at, created_at, updated_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, 'device_web', ?, ?, 'approved', ?, ?, ?, ?)""",
            (
                request_id, payload.asset_id, target.get("device_id") or "",
                str(requester.get("user_id") or requester.get("id") or ""), username,
                payload.access_level, payload.web_profile_id, payload.reason.strip(),
                expires_at, now, now, session_id,
            ),
        )
        conn.execute(
            """INSERT INTO pam_sessions
                   (id, tenant_id, request_id, asset_id, device_id, requester_username,
                    access_level, session_kind, connect_method, target_ip, target_port,
                    target_scheme, target_path, web_profile_id, target_hostname, status,
                    session_token, token_expires_at, token_consumed, recording_status,
                    created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'device_web', 'web', ?, ?, ?, ?, ?, ?,
                       'connecting', ?, ?, 0, 'not_started', ?, ?)""",
            (
                session_id, tenant_id, request_id, payload.asset_id,
                target.get("device_id") or "", username, payload.access_level,
                target.get("management_ip") or "", int(target.get("port") or 443),
                target.get("scheme") or "https", target.get("path") or "/",
                payload.web_profile_id, target.get("hostname") or target.get("management_ip") or "",
                session_token, expires_at, now, now,
            ),
        )
        log_audit_event(
            event_type="pam.web_session.created",
            category="access",
            severity="info",
            status="open",
            summary=f"PAM Web session created for {target.get('hostname') or target.get('management_ip')}",
            actor_id=str(requester.get("user_id") or requester.get("id") or ""),
            actor_username=username,
            actor_role=str(requester.get("role") or ""),
            target_type="asset",
            target_id=payload.asset_id,
            target_name=target.get("hostname") or target.get("management_ip") or "",
            device_id=target.get("device_id") or None,
            request_id=request_id,
            details={
                "session_id": session_id,
                "session_kind": "device_web",
                "access_level": payload.access_level,
                "web_profile_id": payload.web_profile_id,
                "scheme": target.get("scheme"),
                "port": target.get("port"),
            },
            conn=conn,
        )
        conn.commit()
        return {
            "session_id": session_id,
            "request_id": request_id,
            "session_token": session_token,
            "expires_at": expires_at,
            "access_level": payload.access_level,
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/pam/web-sessions/exchange")
def exchange_web_session(payload: WebSessionExchangeInput):
    now = _now()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT ps.*, pa.asset_type, wp.profile_name, wp.enabled
               FROM pam_sessions ps
               JOIN physical_assets pa ON pa.id = ps.asset_id
               JOIN asset_web_access_profiles wp ON wp.id = ps.web_profile_id
               WHERE ps.session_token = ? AND ps.session_kind = 'device_web'""",
            (payload.session_token,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Web session token not found")
        session = dict(row)
        if int(session.get("token_consumed") or 0) != 0:
            raise HTTPException(status_code=409, detail="Web session token already consumed")
        try:
            expires = datetime.fromisoformat(str(session.get("token_expires_at") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid Web session token") from exc
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Web session token expired")
        if not bool(session.get("enabled")):
            raise HTTPException(status_code=409, detail="Asset Web profile is disabled")

        callback_token = secrets.token_urlsafe(32)
        callback_hash = hashlib.sha256(callback_token.encode("utf-8")).hexdigest()
        updated = conn.execute(
            """UPDATE pam_sessions
               SET token_consumed = 1, agent_id = ?, agent_token_hash = ?, last_heartbeat_at = ?, updated_at = ?
               WHERE id = ? AND token_consumed = 0""",
            (payload.agent_id[:128], callback_hash, now, now, session["id"]),
        )
        if getattr(updated, "rowcount", 1) != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Web session token already consumed")
        conn.commit()
        return {
            "success": True,
            "session_id": session["id"],
            "callback_token": callback_token,
            "target_url": _target_url(
                session.get("target_ip") or "",
                session.get("target_scheme") or "https",
                int(session.get("target_port") or 443),
                session.get("target_path") or "/",
            ),
            "display_name": session.get("target_hostname") or session.get("target_ip") or "Web management",
            "profile_name": session.get("profile_name") or "Web management",
            "asset_type": session.get("asset_type") or "",
            "access_level": session.get("access_level") or "normal",
        }
    finally:
        conn.close()


@router.post("/pam/web-sessions/{session_id}/status")
def update_web_session_status(session_id: str, payload: WebSessionStatusInput):
    now = _now()
    conn = get_db_connection()
    try:
        session = _callback_session(conn, session_id, payload.callback_token, payload.agent_id)
        if payload.status == "active" and session.get("status") in {"closed", "interrupted"}:
            raise HTTPException(status_code=409, detail="Web session is already closed")

        if payload.status == "active":
            conn.execute(
                """UPDATE pam_sessions SET status = 'active', agent_id = ?, connected_at = COALESCE(connected_at, ?),
                       closed_at = NULL, close_reason = '', duration_seconds = 0,
                       last_heartbeat_at = ?, recording_status = ?, updated_at = ? WHERE id = ?""",
                (payload.agent_id[:128], now, now, payload.recording_status[:40], now, session_id),
            )
        else:
            start_raw = session.get("connected_at") or session.get("created_at") or now
            try:
                start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
                duration = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
            except ValueError:
                duration = 0
            conn.execute(
                """UPDATE pam_sessions SET status = ?, agent_id = ?, closed_at = ?, close_reason = ?,
                       duration_seconds = ?, last_heartbeat_at = ?, recording_status = ?, updated_at = ? WHERE id = ?""",
                (
                    payload.status, payload.agent_id[:128], now, payload.reason[:200], duration,
                    now, payload.recording_status[:40], now, session_id,
                ),
            )
        conn.commit()
        return {"ok": True, "session_id": session_id, "status": payload.status}
    finally:
        conn.close()


@router.post("/pam/web-sessions/{session_id}/recording")
async def upload_web_recording(
    session_id: str,
    callback_token: str = Form(...),
    agent_id: str = Form(""),
    file: UploadFile = File(...),
):
    """Store a system-browser window recording uploaded by the local Agent.

    The callback token is the only credential accepted here.  The browser UI
    never handles this endpoint, and the uploaded filename is ignored so a
    workstation cannot choose a path outside the PAM recording directory.
    """
    suffix = Path(str(file.filename or "")).suffix.lower()
    if suffix not in _RECORDING_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported Web recording format")

    conn = get_db_connection()
    temp_path: str | None = None
    try:
        session = _callback_session(conn, session_id, callback_token, agent_id)
        recordings_dir = Path("data") / "pam_recordings"
        recordings_dir.mkdir(parents=True, exist_ok=True)
        safe_session_id = "".join(char for char in session_id if char.isalnum() or char in {"-", "_"})[:100]
        if not safe_session_id:
            raise HTTPException(status_code=422, detail="Invalid Web session id")

        digest = hashlib.sha256()
        size = 0
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{safe_session_id}-",
            suffix=".upload",
            dir=str(recordings_dir),
        )
        try:
            with os.fdopen(fd, "wb") as destination:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_RECORDING_BYTES:
                        raise HTTPException(status_code=413, detail="Web recording exceeds the 50 MB limit")
                    digest.update(chunk)
                    destination.write(chunk)
        except Exception:
            # fdopen owns the descriptor after entering the context.  The
            # finally block below removes the temporary file on every error.
            raise

        final_path = recordings_dir / f"{safe_session_id}{suffix}"
        os.replace(temp_path, final_path)
        temp_path = None
        now = _now()
        conn.execute(
            """UPDATE pam_sessions
               SET recording_path = ?, recording_status = 'uploaded', updated_at = ?
               WHERE id = ? AND session_kind = 'device_web'""",
            (str(final_path), now, session_id),
        )
        log_audit_event(
            event_type="pam.web_recording.uploaded",
            category="access",
            severity="info",
            status="closed" if session.get("status") in {"closed", "interrupted", "error"} else "open",
            summary=f"PAM Web recording uploaded for session {session_id}",
            target_type="session",
            target_id=session_id,
            details={
                "session_kind": "device_web",
                "format": suffix.lstrip("."),
                "size": size,
                "sha256": digest.hexdigest(),
            },
            conn=conn,
        )
        conn.commit()
        return {
            "success": True,
            "session_id": session_id,
            "recording_status": "uploaded",
            "size": size,
            "sha256": digest.hexdigest(),
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
        await file.close()
        conn.close()
