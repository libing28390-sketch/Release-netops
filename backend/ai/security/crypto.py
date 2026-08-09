"""
AI Provider API Key AES-256-GCM Encryption, Decryption, and Masking Helpers
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional
from core.config import settings

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTOGRAPHY = False


def _get_encryption_key() -> bytes:
    """Derive 256-bit AES key from system CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY."""
    raw_secret = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", None) or getattr(settings, "SECRET_KEY", "nexora-ai-default-key")
    return hashlib.sha256(raw_secret.encode("utf-8")).digest()


def encrypt_api_key(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt plain API Key using AES-256-GCM."""
    if not plaintext:
        return None
    key = _get_encryption_key()
    if _HAS_CRYPTOGRAPHY:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ciphertext).decode("ascii")
    else:
        # A reversible XOR obfuscation is not encryption and could expose
        # provider credentials.  Refuse to persist a key until AES-GCM is
        # available instead of silently weakening the security boundary.
        raise RuntimeError("cryptography with AES-GCM is required to encrypt AI provider keys")


def decrypt_api_key(encrypted_b64: Optional[str]) -> Optional[str]:
    """Decrypt encrypted API Key back to plaintext."""
    if not encrypted_b64:
        return None
    key = _get_encryption_key()
    if _HAS_CRYPTOGRAPHY:
        try:
            raw_data = base64.b64decode(encrypted_b64.encode("ascii"))
            nonce = raw_data[:12]
            ciphertext = raw_data[12:]
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8")
        except Exception:
            return None
    return None


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """Mask sensitive API key for safe frontend display (e.g. sk-****a1b2)."""
    if not api_key:
        return None
    clean = api_key.strip()
    if len(clean) <= 8:
        return "********"
    return clean[:4] + "****" + clean[-4:]
