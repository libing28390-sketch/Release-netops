"""
license/verifier.py — License 验证引擎
========================================
Thread-safe, singleton license verifier with multi-point validation:
  • Startup validation
  • Runtime periodic re-validation
  • Critical operation gate checks

Implements:
  • RSA signature verification
  • Expiry / grace-period logic (7-day warning)
  • Device limit enforcement
  • Feature flag gating
  • In-memory hash cache for tamper detection
  • Structured audit logging
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .crypto import verify_signature, load_public_key_from_file
from .models import LicenseFile, LicensePayload, LicenseStatus

logger = logging.getLogger("license.verifier")

def get_machine_id() -> str:
    """Generate a unique machine ID based on MAC address."""
    mac = uuid.getnode()
    h = hashlib.sha256(str(mac).encode("utf-8")).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

# ── Constants ─────────────────────────────────────────────────────────

_WARN_DAYS = 7          # days before expiry to start warning
_GRACE_PERIOD_DAYS = 0  # hard cutoff: no grace period by default

# Resolve paths relative to backend/ directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_LICENSE_PATH = _BACKEND_DIR.parent / "data" / "license.json"
_DEFAULT_PUBLIC_KEY_PATH = _BACKEND_DIR / "license" / "keys" / "public.pem"


class LicenseVerifier:
    """
    Singleton license validation engine.
    
    Usage:
        verifier = LicenseVerifier.get_instance()
        verifier.load()
        status = verifier.validate()
    """

    _instance: Optional["LicenseVerifier"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        license_path: Optional[str] = None,
        public_key_path: Optional[str] = None,
    ):
        self._license_path = Path(license_path or os.environ.get(
            "LICENSE_FILE_PATH", str(_DEFAULT_LICENSE_PATH)
        ))
        self._public_key_path = Path(public_key_path or os.environ.get(
            "LICENSE_PUBLIC_KEY_PATH", str(_DEFAULT_PUBLIC_KEY_PATH)
        ))

        # In-memory state
        self._license: Optional[LicenseFile] = None
        self._payload: Optional[LicensePayload] = None
        self._file_hash: Optional[str] = None       # SHA-256 of the raw file
        self._last_validated: float = 0.0
        self._cached_status: Optional[LicenseStatus] = None
        self._public_key_pem: Optional[bytes] = None

    @classmethod
    def get_instance(cls, **kwargs) -> "LicenseVerifier":
        """Thread-safe singleton accessor."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton (for testing or hot-reload)."""
        with cls._lock:
            cls._instance = None

    # ── Loading ───────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Load the license file and public key from disk.
        Returns True if loaded successfully (does NOT validate yet).
        """
        # Load public key
        if not self._public_key_path.exists():
            logger.error(f"[License] Public key not found: {self._public_key_path}")
            self._cached_status = LicenseStatus(valid=False, error="Public key not found")
            return False
        self._public_key_pem = load_public_key_from_file(str(self._public_key_path))

        # Load license file
        if not self._license_path.exists():
            logger.warning(f"[License] License file not found: {self._license_path}")
            self._cached_status = LicenseStatus(valid=False, error="License file not found")
            return False

        try:
            raw = self._license_path.read_text(encoding="utf-8")
            self._file_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            data = json.loads(raw)
            self._license = LicenseFile(**data)
            self._payload = self._license.payload
            logger.info(f"[License] Loaded license {self._payload.license_id} for {self._payload.company}")
            return True
        except json.JSONDecodeError as e:
            logger.error(f"[License] Corrupted license file: {e}")
            self._cached_status = LicenseStatus(valid=False, error="License file is corrupted (invalid JSON)")
            return False
        except Exception as e:
            logger.error(f"[License] Failed to load license: {e}")
            self._cached_status = LicenseStatus(valid=False, error=f"License load error: {e}")
            return False

    def load_from_bytes(self, content: bytes) -> bool:
        """Load license from raw bytes (for API upload)."""
        try:
            raw = content.decode("utf-8")
            self._file_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            data = json.loads(raw)
            self._license = LicenseFile(**data)
            self._payload = self._license.payload
            return True
        except Exception as e:
            logger.error(f"[License] Failed to parse uploaded license: {e}")
            return False

    # ── Tamper Detection ──────────────────────────────────────────────

    def _check_file_integrity(self) -> bool:
        """
        Verify that the on-disk file has not been modified since last load.
        If modified, force a reload + re-validate.
        """
        if not self._license_path.exists():
            return False
        try:
            raw = self._license_path.read_text(encoding="utf-8")
            current_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            if current_hash != self._file_hash:
                logger.warning("[License] File hash mismatch — file was modified on disk, reloading")
                self.load()
                self._cached_status = None  # force re-validation
                return True
            return True
        except Exception:
            return False

    # ── Core Validation ───────────────────────────────────────────────

    def validate(self, force: bool = False) -> LicenseStatus:
        """
        Full license validation with caching.
        Re-validates every 60 seconds or when forced.
        
        Checks:
          1. License loaded
          2. File integrity (hash)
          3. RSA signature
          4. Expiry date
          5. Warning period (7 days)
        """
        now = time.time()

        # Return cached result if recent enough
        if not force and self._cached_status and (now - self._last_validated) < 60:
            return self._cached_status

        # Pre-flight
        if self._license is None or self._payload is None:
            if not self.load():
                return self._cached_status or LicenseStatus(valid=False, error="No license loaded")

        # Integrity check
        self._check_file_integrity()

        warnings: List[str] = []
        payload = self._payload
        assert payload is not None

        # 1. Signature verification
        payload_dict = payload.model_dump(mode="json")
        if not verify_signature(payload_dict, self._license.signature, self._public_key_pem):
            status = LicenseStatus(
                valid=False,
                license_id=payload.license_id,
                company=payload.company,
                error="Invalid license signature — file may have been tampered with",
            )
            self._cached_status = status
            self._last_validated = now
            logger.error(f"[License] SIGNATURE INVALID for {payload.license_id}")
            return status

        # 2. Expiry check
        try:
            expire_dt = datetime.fromisoformat(payload.expire_at)
            if expire_dt.tzinfo is None:
                expire_dt = expire_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            delta = expire_dt - now_dt
            days_remaining = delta.days

            if days_remaining < 0:
                status = LicenseStatus(
                    valid=False,
                    license_id=payload.license_id,
                    company=payload.company,
                    license_type=payload.license_type.value,
                    issued_at=payload.issued_at,
                    expire_at=payload.expire_at,
                    days_remaining=days_remaining,
                    device_limit=payload.device_limit,
                    server_limit=payload.server_limit,
                    features=payload.features,
                    error=f"License expired {abs(days_remaining)} days ago",
                )
                self._cached_status = status
                self._last_validated = now
                logger.warning(f"[License] EXPIRED: {payload.license_id}, expired {abs(days_remaining)} days ago")
                return status

            if days_remaining <= _WARN_DAYS:
                warn_msg = f"License expires in {days_remaining} day(s) — please renew soon"
                warnings.append(warn_msg)
                logger.warning(f"[License] {warn_msg}")

        except Exception as e:
            status = LicenseStatus(valid=False, error=f"Invalid expiry date format: {e}")
            self._cached_status = status
            self._last_validated = now
            return status

        # 3. Machine ID Binding Check
        if payload.machine_id:
            current_machine_id = get_machine_id()
            if payload.machine_id != current_machine_id:
                status = LicenseStatus(
                    valid=False,
                    license_id=payload.license_id,
                    company=payload.company,
                    license_type=payload.license_type.value,
                    issued_at=payload.issued_at,
                    expire_at=payload.expire_at,
                    days_remaining=days_remaining,
                    device_limit=payload.device_limit,
                    server_limit=payload.server_limit,
                    features=payload.features,
                    error=f"License is bound to machine '{payload.machine_id}', but current machine is '{current_machine_id}'.",
                )
                self._cached_status = status
                self._last_validated = now
                logger.error(f"[License] MACHINE ID MISMATCH for {payload.license_id}")
                return status

        # 4. Build success status
        status = LicenseStatus(
            valid=True,
            license_id=payload.license_id,
            company=payload.company,
            license_type=payload.license_type.value,
            issued_at=payload.issued_at,
            expire_at=payload.expire_at,
            days_remaining=days_remaining,
            device_limit=payload.device_limit,
            server_limit=payload.server_limit,
            features=payload.features,
            warnings=warnings,
        )
        self._cached_status = status
        self._last_validated = now

        logger.debug(
            f"[License] Validated OK: {payload.license_id}, "
            f"company={payload.company}, "
            f"expires_in={days_remaining}d, "
            f"devices={payload.device_limit}, "
            f"features={payload.features}"
        )
        return status

    # ── Feature & Device Checks ───────────────────────────────────────

    def check_feature(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled in the license."""
        status = self.validate()
        if not status.valid:
            return False
        return feature_name in status.features

    def check_device_limit(self, current_count: int) -> bool:
        """
        Check if the current device count is within the licensed limit.
        Returns True if within limit, False if exceeded.
        """
        status = self.validate()
        if not status.valid:
            return False
        return current_count <= (status.device_limit or 0)

    def get_device_limit(self) -> int:
        """Return the device limit from the license."""
        status = self.validate()
        return status.device_limit or 0

    def check_server_limit(self, current_count: int) -> bool:
        """
        Check if the current server count is within the licensed limit.
        Returns True if within limit, False if exceeded.
        """
        status = self.validate()
        if not status.valid:
            return False
        return current_count <= (status.server_limit or 0)

    def get_server_limit(self) -> int:
        """Return the server limit from the license."""
        status = self.validate()
        return status.server_limit or 0

    def is_expired(self) -> bool:
        """Quick check: is the license expired?"""
        status = self.validate()
        return not status.valid and "expired" in (status.error or "").lower()

    def is_expiring_soon(self) -> bool:
        """Quick check: is the license expiring within the warning window?"""
        status = self.validate()
        return status.valid and len(status.warnings) > 0

    @property
    def payload(self) -> Optional[LicensePayload]:
        return self._payload

    @property
    def status(self) -> LicenseStatus:
        return self.validate()


# ── Module-level convenience ──────────────────────────────────────────

def get_license_verifier(**kwargs) -> LicenseVerifier:
    """Get the global LicenseVerifier singleton."""
    return LicenseVerifier.get_instance(**kwargs)
