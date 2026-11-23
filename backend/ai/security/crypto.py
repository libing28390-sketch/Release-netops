"""AI provider API key encryption (review item M14).

Ciphertext formats
------------------
``aik:v2:<kid>:<base64(nonce[12] || ciphertext || tag)>``  current
    AES-256-GCM.  The data key is derived with HKDF-SHA256 from a master
    secret selected by ``kid``; the provider id is bound as AAD, so a
    ciphertext copied to another provider row does not decrypt.
``<base64(nonce || ciphertext || tag)>``                     legacy (v1)
    AES-256-GCM with ``sha256(CREDENTIAL_ENCRYPTION_KEY or SECRET_KEY)`` and
    no AAD.  Read-only: decrypted for compatibility and re-encrypted as v2 on
    the next read through the gateway or by
    ``scripts/ai_provider_key_reencrypt.py``.

Master keys
-----------
``AI_PROVIDER_KEY_ENCRYPTION_KEYS``  ``kid:secret[,kid:secret...]``; several
    keys allow rotation of the master key (old ciphertexts keep their kid).
``AI_PROVIDER_KEY_ID``               kid used for new ciphertexts.
When no AI-specific key is configured, kid ``c1`` is derived from
``CREDENTIAL_ENCRYPTION_KEY`` with a distinct HKDF ``info``.  That keeps one
secret to manage for existing deployments while the AI data key is still
separate from the device-credential key (core/crypto.py derives its own with
PBKDF2 and another salt).  ``SECRET_KEY`` (the session-signing key) is never
used for new ciphertexts.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Dict, Optional

from core.config import settings

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    _HAS_CRYPTOGRAPHY = True
except ImportError:  # pragma: no cover
    _HAS_CRYPTOGRAPHY = False
    InvalidTag = Exception  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

PREFIX_V2 = "aik:v2:"
DERIVED_KID = "c1"
_HKDF_SALT = b"nexora-ai-provider-key-v2"
_NONCE_LEN = 12
_PLACEHOLDERS = {"change-me-to-a-random-secret", "supersecret", "nexora-ai-default-key"}


class ProviderKeyDecryptError(RuntimeError):
    """A stored provider key exists but cannot be decrypted.

    Raised instead of returning ``None`` so that a wrong or missing master
    key is reported as ``AI_KEY_DECRYPT_FAILED`` rather than looking like a
    provider without a key (``401``).
    """

    def __init__(self, reason: str, kid: str | None = None) -> None:
        super().__init__(f"AI provider key decryption failed ({reason})")
        self.code = "AI_KEY_DECRYPT_FAILED"
        self.reason = reason
        self.kid = kid


def _usable_secret(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in _PLACEHOLDERS or len(text) < 16:
        return ""
    return text


def _master_keys() -> Dict[str, bytes]:
    keys: Dict[str, bytes] = {}
    raw = str(getattr(settings, "AI_PROVIDER_KEY_ENCRYPTION_KEYS", "") or os.environ.get("AI_PROVIDER_KEY_ENCRYPTION_KEYS", "") or "")
    for item in raw.split(","):
        if ":" not in item:
            continue
        kid, secret = item.split(":", 1)
        kid, secret = kid.strip(), _usable_secret(secret)
        if kid and secret and kid != DERIVED_KID and all(ch.isalnum() or ch in "-_" for ch in kid):
            keys[kid] = secret.encode("utf-8")
    credential = _usable_secret(getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", ""))
    if credential:
        keys.setdefault(DERIVED_KID, credential.encode("utf-8"))
    return keys


def current_kid() -> str:
    keys = _master_keys()
    configured = str(getattr(settings, "AI_PROVIDER_KEY_ID", "") or os.environ.get("AI_PROVIDER_KEY_ID", "") or "").strip()
    if configured and configured in keys:
        return configured
    explicit = [kid for kid in keys if kid != DERIVED_KID]
    if explicit:
        return sorted(explicit)[-1]
    return DERIVED_KID


def _derive(kid: str) -> bytes:
    master = _master_keys().get(kid)
    if master is None:
        raise ProviderKeyDecryptError("unknown_kid", kid)
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=b"ai-provider-key:" + kid.encode("ascii")).derive(master)


def _legacy_key() -> bytes:
    raw = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", None) or getattr(settings, "SECRET_KEY", "nexora-ai-default-key")
    return hashlib.sha256(str(raw).encode("utf-8")).digest()


def has_configured_master_key() -> bool:
    """Whether a non-placeholder master secret exists for provider keys."""
    return bool(_master_keys())


def require_configured_master_key() -> None:
    if not has_configured_master_key():
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY (or AI_PROVIDER_KEY_ENCRYPTION_KEYS) must be configured before storing AI provider keys"
        )


def is_current_format(token: Optional[str]) -> bool:
    return bool(token) and str(token).startswith(PREFIX_V2 + current_kid() + ":")


def encrypt_api_key(plaintext: Optional[str], *, provider_id: str) -> Optional[str]:
    """Encrypt a provider API key, bound to ``provider_id``."""
    if not plaintext:
        return None
    if not _HAS_CRYPTOGRAPHY:
        raise RuntimeError("cryptography with AES-GCM is required to encrypt AI provider keys")
    if not provider_id:
        raise ValueError("provider_id is required to encrypt a provider key")
    require_configured_master_key()
    kid = current_kid()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(_derive(kid)).encrypt(nonce, plaintext.encode("utf-8"), str(provider_id).encode("utf-8"))
    return f"{PREFIX_V2}{kid}:{base64.b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt_api_key(token: Optional[str], *, provider_id: str) -> Optional[str]:
    """Decrypt a stored key.  ``None`` only when nothing is stored.

    Raises :class:`ProviderKeyDecryptError` when a key is stored but cannot
    be decrypted (wrong master key, unknown kid, other provider's row,
    corrupted value).
    """
    if not token:
        return None
    if not _HAS_CRYPTOGRAPHY:
        raise ProviderKeyDecryptError("cryptography_unavailable")
    text = str(token)
    if text.startswith(PREFIX_V2):
        try:
            kid, payload = text[len(PREFIX_V2):].split(":", 1)
            raw = base64.b64decode(payload.encode("ascii"), validate=True)
        except (ValueError, TypeError) as exc:
            raise ProviderKeyDecryptError("malformed") from exc
        try:
            plain = AESGCM(_derive(kid)).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], str(provider_id).encode("utf-8"))
        except InvalidTag as exc:
            logger.error("AI provider key decrypt failed kid=%s code=AI_KEY_DECRYPT_FAILED", kid)
            raise ProviderKeyDecryptError("invalid_tag", kid) from exc
        return plain.decode("utf-8")
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
        plain = AESGCM(_legacy_key()).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], None)
    except (ValueError, TypeError, InvalidTag) as exc:
        logger.error("AI provider key decrypt failed kid=legacy code=AI_KEY_DECRYPT_FAILED")
        raise ProviderKeyDecryptError("legacy_invalid") from exc
    return plain.decode("utf-8")


def reencrypt_if_needed(token: Optional[str], *, provider_id: str) -> tuple[Optional[str], bool]:
    """Return ``(token, changed)``; upgrades legacy or old-kid ciphertexts."""
    if not token or is_current_format(token):
        return token, False
    plain = decrypt_api_key(token, provider_id=provider_id)
    return encrypt_api_key(plain, provider_id=provider_id), True


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """Display form: only the last four characters (``****a1b2``)."""
    if not api_key:
        return None
    clean = api_key.strip()
    if len(clean) < 12:
        return "********"
    return "****" + clean[-4:]
