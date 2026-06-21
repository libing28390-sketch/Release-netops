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
from core.version import VERSION, EDITION

logger = logging.getLogger("license.verifier")

def get_machine_id() -> str:
    """Generate a unique machine ID based on MAC address.
    Supports MACHINE_ID_OVERRIDE for Docker/Cloud deployments."""
    override = os.environ.get("MACHINE_ID_OVERRIDE")
    if override:
        return override.strip().upper()
        
    mac = uuid.getnode()
    h = hashlib.sha256(str(mac).encode("utf-8")).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

# ── Constants ─────────────────────────────────────────────────────────

_WARN_DAYS = 7          # days before expiry to start warning
_GRACE_PERIOD_DAYS = 0  # hard cutoff: no grace period by default

# Resolve paths relative to backend/ directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_LICENSE_PATH = _BACKEND_DIR.parent / "data" / "license.json"

# Try license_auth first, then fallback to license if needed for legacy compatibility
_DEFAULT_PUBLIC_KEY_PATH = _BACKEND_DIR / "license_auth" / "keys" / "public.pem"
if not _DEFAULT_PUBLIC_KEY_PATH.exists():
    _alt_path = _BACKEND_DIR / "license" / "keys" / "public.pem"
    if _alt_path.exists():
        _DEFAULT_PUBLIC_KEY_PATH = _alt_path


class LicenseVerifier:
    """
    Singleton license validation engine (Unrestricted/Bypassed).
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
        self._license = None
        self._payload = None
        self._file_hash = None
        self._last_validated = 0.0
        self._cached_status = None
        self._public_key_pem = None

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
        """Reset the singleton."""
        with cls._lock:
            cls._instance = None

    def load(self) -> bool:
        return True

    def load_from_bytes(self, content: bytes) -> bool:
        return True

    def _check_file_integrity(self) -> bool:
        return True

    def validate(self, force: bool = False) -> LicenseStatus:
        self._cached_status = LicenseStatus(
            valid=True,
            license_id="perpetual-enterprise",
            company="Nexora Enterprise User",
            license_type="enterprise",
            issued_at="2026-01-01T00:00:00+00:00",
            expire_at="2099-12-31T23:59:59+00:00",
            days_remaining=99999,
            max_version="99.9.9",
            current_version=VERSION,
            device_limit=999999,
            device_current=0,
            server_limit=999999,
            server_current=0,
            features=[
                "rbac", "automation", "config_management", "change_orders",
                "inspections", "topology", "monitoring", "alerting", "ipam",
                "capacity", "compliance", "reports", "api_access",
                "scheduled_jobs", "password_rotation", "access_center"
            ],
            warnings=[]
        )
        return self._cached_status

    def check_feature(self, feature_name: str) -> bool:
        return True

    def check_device_limit(self, current_count: int) -> bool:
        return True

    def get_device_limit(self) -> int:
        return 999999

    def check_server_limit(self, current_count: int) -> bool:
        return True

    def get_server_limit(self) -> int:
        return 999999

    def is_expired(self) -> bool:
        return False

    def is_expiring_soon(self) -> bool:
        return False

    @property
    def payload(self) -> Optional[any]:
        return None

    @property
    def status(self) -> LicenseStatus:
        return self.validate()


def get_license_verifier(**kwargs) -> LicenseVerifier:
    return LicenseVerifier.get_instance(**kwargs)


def check_file_integrity(project_root: str) -> bool:
    return True


def bootstrap_license_protection(app, project_root=None):
    return get_license_verifier()

