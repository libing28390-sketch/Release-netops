"""
license/api.py — License 管理 API 端点
========================================
Provides REST endpoints for:
  • GET  /api/license/status      — Query current license status
  • POST /api/license/upload      — Upload/replace license file (rate-limited)
  • GET  /api/license/features    — List licensed features
  • GET  /api/license/device-usage — Device limit vs. current usage
  • GET  /api/license/audit-log   — License operation audit trail

Security:
  • Upload endpoint is rate-limited to 5 requests/minute per IP
  • All operations are audit-logged with source IP
  • Consecutive invalid upload attempts trigger progressive lockout
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status, Depends

from core.rbac import require_role
from services.audit_service import log_audit_event

from .models import LicenseStatus
from .verifier import LicenseVerifier, get_license_verifier

logger = logging.getLogger("license.api")

router = APIRouter(prefix="/license", tags=["License Management"])

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_LICENSE_PATH = _BACKEND_DIR.parent / "data" / "license.json"


# ── Audit Log ─────────────────────────────────────────────────────────

class LicenseAuditLog:
    """Thread-safe in-memory audit log for license operations."""

    _instance: Optional["LicenseAuditLog"] = None
    _lock = threading.Lock()

    def __init__(self, max_entries: int = 500):
        self._entries: list[dict] = []
        self._max = max_entries

    @classmethod
    def get_instance(cls) -> "LicenseAuditLog":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def log(self, action: str, detail: str, ip: str = "", username: str = "system"):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "detail": detail,
            "ip": ip,
        }
        with self._lock:
            self._entries.insert(0, entry)
            if len(self._entries) > self._max:
                self._entries = self._entries[:self._max]
        logger.info(f"[License Audit] {action}: {detail} (IP: {ip})")
        
        # Async persist to DB for write/fail operations
        if action in ("upload", "rejected", "upload_failed"):
            try:
                status_map = {"upload": "success", "upload_failed": "failed", "rejected": "failed"}
                event_status = status_map.get(action, "success")
                
                # Use threading to prevent blocking
                def _persist():
                    try:
                        log_audit_event(
                            event_type=f"LICENSE_{action.upper()}",
                            category="system",
                            severity="high" if action == "upload_failed" else "medium",
                            status=event_status,
                            summary=f"License {action}: {detail}",
                            actor_username=username,
                            source_ip=ip,
                            target_type="license",
                            target_name="platform_license"
                        )
                    except Exception as e:
                        logger.error(f"Failed to persist license audit log: {e}")
                
                threading.Thread(target=_persist, daemon=True).start()
            except Exception as e:
                logger.error(f"Error launching audit log thread: {e}")

    def get_entries(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return self._entries[:limit]


# ── Anti Brute-Force ──────────────────────────────────────────────────

class UploadRateLimiter:
    """
    Per-IP rate limiter and progressive lockout for license upload.
    
    Rules:
      • Max 5 upload attempts per minute per IP
      • 3 consecutive invalid uploads → 5-minute cooldown
      • 5 consecutive invalid uploads → 30-minute lockout
      • 10 consecutive invalid uploads → 2-hour lockout
    """

    _instance: Optional["UploadRateLimiter"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._attempts: dict[str, list[float]] = defaultdict(list)  # IP → timestamps
        self._failures: dict[str, int] = defaultdict(int)           # IP → consecutive fails
        self._lockout_until: dict[str, float] = {}                  # IP → lockout expiry

    @classmethod
    def get_instance(cls) -> "UploadRateLimiter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def check(self, ip: str) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        If not allowed, reason explains why.
        """
        now = time.time()

        # Check lockout
        if ip in self._lockout_until:
            if now < self._lockout_until[ip]:
                remaining = int(self._lockout_until[ip] - now)
                mins = remaining // 60
                secs = remaining % 60
                return False, f"Too many invalid attempts. Locked out for {mins}m {secs}s."
            else:
                # Lockout expired
                del self._lockout_until[ip]
                self._failures[ip] = 0

        # Check rate limit (5/minute)
        window = 60.0
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < window]
        if len(self._attempts[ip]) >= 5:
            return False, "Rate limit exceeded. Max 5 uploads per minute."

        return True, ""

    def record_attempt(self, ip: str):
        self._attempts[ip].append(time.time())

    def record_failure(self, ip: str):
        self._failures[ip] += 1
        fails = self._failures[ip]
        now = time.time()

        if fails >= 10:
            self._lockout_until[ip] = now + 7200  # 2 hours
            logger.warning(f"[License Security] IP {ip} locked out for 2 hours after {fails} failures")
        elif fails >= 5:
            self._lockout_until[ip] = now + 1800   # 30 minutes
            logger.warning(f"[License Security] IP {ip} locked out for 30 minutes after {fails} failures")
        elif fails >= 3:
            self._lockout_until[ip] = now + 300    # 5 minutes
            logger.warning(f"[License Security] IP {ip} locked out for 5 minutes after {fails} failures")

    def record_success(self, ip: str):
        self._failures[ip] = 0
        if ip in self._lockout_until:
            del self._lockout_until[ip]


# ── Helpers ───────────────────────────────────────────────────────────

def _get_device_count() -> int:
    """Get the current total device count from database."""
    try:
        import sys
        sys.path.insert(0, str(_BACKEND_DIR))
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM devices").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[License] Failed to count devices: {e}")
        return 0


def _get_server_count() -> int:
    """Get the current total server count from database."""
    try:
        import sys
        if str(_BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(_BACKEND_DIR))
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT COUNT(*) FROM physical_assets WHERE asset_type = 'server'").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[License] Failed to count servers: {e}")
        return 0


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/machine-id", summary="Get Server Machine ID")
async def get_machine_id_endpoint(request: Request):
    """Returns the unique machine ID for license binding."""
    from .verifier import get_machine_id
    return {"machine_id": get_machine_id()}

@router.get("/status", response_model=LicenseStatus, summary="Get License Status")
async def get_license_status(request: Request):
    """
    Returns the current license validation status including:
    - Validity, company, type, expiry
    - Device limit and current usage
    - Enabled features
    - Warnings (e.g. expiring soon)
    """
    verifier = get_license_verifier()
    lic_status = verifier.validate(force=True)

    # Enrich with device count
    if lic_status.valid or (lic_status.error and "expired" in lic_status.error.lower()):
        lic_status.device_current = _get_device_count()
        lic_status.server_current = _get_server_count()

    # Audit log
    audit = LicenseAuditLog.get_instance()
    audit.log("validate", f"Status check: valid={lic_status.valid}", _get_client_ip(request))

    return lic_status


@router.post("/upload", summary="Upload License File")
async def upload_license(request: Request, file: UploadFile = File(...)):
    """
    Upload a new license.json file.
    
    The file is validated before being saved. If validation fails,
    the old license is preserved.
    
    Rate limited: 5 attempts/minute per IP.
    Progressive lockout on consecutive failures.
    """
    from api.users import validate_session_token
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
    user = validate_session_token(token)
    if not user or user.get("role") != "Administrator":
        raise HTTPException(status_code=403, detail="Administrator permissions required")
    client_ip = _get_client_ip(request)
    audit = LicenseAuditLog.get_instance()
    limiter = UploadRateLimiter.get_instance()

    # Rate limit check
    allowed, reason = limiter.check(client_ip)
    if not allowed:
        audit.log("rejected", f"Upload blocked: {reason}", client_ip, username=user.get('username', 'system'))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=reason,
        )
    limiter.record_attempt(client_ip)

    if not file.filename or not file.filename.endswith(".json"):
        limiter.record_failure(client_ip)
        audit.log("rejected", "Upload rejected: not a .json file", client_ip, username=user.get('username', 'system'))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="License file must be a .json file",
        )

    content = await file.read()
    if len(content) > 1024 * 100:  # 100KB limit
        limiter.record_failure(client_ip)
        audit.log("rejected", "Upload rejected: file too large", client_ip, username=user.get('username', 'system'))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="License file too large (max 100KB)",
        )

    # Validate the uploaded license before saving
    temp_verifier = LicenseVerifier.__new__(LicenseVerifier)
    temp_verifier._license = None
    temp_verifier._payload = None
    temp_verifier._file_hash = None
    temp_verifier._last_validated = 0.0
    temp_verifier._cached_status = None

    # Load the public key from the active verifier
    active_verifier = get_license_verifier()
    temp_verifier._public_key_pem = active_verifier._public_key_pem
    temp_verifier._license_path = active_verifier._license_path
    temp_verifier._public_key_path = active_verifier._public_key_path

    if not temp_verifier.load_from_bytes(content):
        limiter.record_failure(client_ip)
        audit.log("rejected", "Upload rejected: invalid file format", client_ip, username=user.get('username', 'system'))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid license file format",
        )

    # Verify signature
    from .crypto import verify_signature
    payload_dict = temp_verifier._payload.model_dump(mode="json")
    if not verify_signature(payload_dict, temp_verifier._license.signature, temp_verifier._public_key_pem):
        limiter.record_failure(client_ip)
        audit.log("rejected", f"Upload rejected: signature verification FAILED (possible forgery attempt)", client_ip, username=user.get('username', 'system'))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="License signature verification failed — invalid or tampered file",
        )

    # ── Signature valid — proceed with save ──
    limiter.record_success(client_ip)

    # Backup existing license
    license_path = Path(os.environ.get("LICENSE_FILE_PATH", str(_DEFAULT_LICENSE_PATH)))
    license_path.parent.mkdir(parents=True, exist_ok=True)

    if license_path.exists():
        backup_name = f"license.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak.json"
        backup_path = license_path.parent / backup_name
        shutil.copy2(str(license_path), str(backup_path))
        logger.info(f"[License] Backed up old license to {backup_path}")

    # Save new license
    license_path.write_bytes(content)
    logger.info(f"[License] New license saved to {license_path}")

    # Reload the global verifier
    LicenseVerifier.reset_instance()
    verifier = get_license_verifier()
    verifier.load()
    new_status = verifier.validate(force=True)
    new_status.device_current = _get_device_count()

    audit.log(
        "upload",
        f"License activated: {new_status.license_id} for {new_status.company} "
        f"(type={new_status.license_type}, devices={new_status.device_limit}, "
        f"features={len(new_status.features)}, expires={new_status.expire_at})",
        client_ip,
        username=user.get('username', 'system')
    )

    return {
        "message": "License uploaded and activated successfully",
        "status": new_status.model_dump(),
    }


@router.get("/features", summary="List Licensed Features")
async def get_licensed_features():
    """Return the list of features enabled in the current license."""
    verifier = get_license_verifier()
    lic_status = verifier.validate()

    return {
        "valid": lic_status.valid,
        "features": lic_status.features,
        "license_type": lic_status.license_type,
    }


@router.get("/device-usage", summary="Device Limit Usage")
async def get_device_usage():
    """Return device and server limit and current usage statistics."""
    verifier = get_license_verifier()
    lic_status = verifier.validate()
    current_count = _get_device_count()
    server_count = _get_server_count()

    return {
        "valid": lic_status.valid,
        "device_limit": lic_status.device_limit or 0,
        "device_current": current_count,
        "utilization_percent": round(
            (current_count / max(lic_status.device_limit or 1, 1)) * 100, 1
        ),
        "remaining": max((lic_status.device_limit or 0) - current_count, 0),
        "exceeded": current_count > (lic_status.device_limit or 0),
        
        "server_limit": lic_status.server_limit or 0,
        "server_current": server_count,
        "server_utilization_percent": round(
            (server_count / max(lic_status.server_limit or 1, 1)) * 100, 1
        ),
        "server_remaining": max((lic_status.server_limit or 0) - server_count, 0),
        "server_exceeded": server_count > (lic_status.server_limit or 0),
    }


@router.get("/audit-log", summary="License Audit Log")
async def get_audit_log(limit: int = 100):
    """
    Return the license operation audit trail.
    Records all license validations, uploads, and rejections.
    """
    audit = LicenseAuditLog.get_instance()
    return {
        "entries": audit.get_entries(limit=min(limit, 500)),
    }
