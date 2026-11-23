"""Field-level encryption for AI conversation content (review item M12).

Conversation messages used to be *tokenized* at rest: identifiers were
replaced by ``[[NXA_IP_...]]`` tokens that only the in-process token vault
could map back, for at most AI_SECURITY_VAULT_TTL_SECONDS.  After a restart,
on another worker or an hour later the history showed the tokens forever.

Now the readable text is stored encrypted and tokenization happens only on
the way out, inside the security gateway, for the one provider request.  The
vault therefore only has to live for a single request.

Format: ``afc:v1:<kid>:<base64(nonce[12] || ciphertext || tag)>``
    AES-256-GCM; the data key is HKDF-SHA256 from the same master secrets as
    provider keys (``ai.security.crypto``) but with a different salt/info, so
    the two data keys are independent.  ``context`` (for example the
    conversation id) is bound as AAD: a value copied to another conversation
    does not decrypt.
"""

from __future__ import annotations

import base64
import logging
import os
import threading

from ai.security import crypto as _crypto

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

PREFIX = "afc:v1:"
_SALT = b"nexora-ai-field-v1"
_NONCE_LEN = 12
_KEY_CACHE_MAX = 16
_KEY_CACHE: dict[tuple[str, bytes], bytes] = {}
_KEY_CACHE_LOCK = threading.Lock()


class FieldDecryptError(RuntimeError):
    code = "AI_FIELD_DECRYPT_FAILED"


def available() -> bool:
    return _HAS_CRYPTOGRAPHY and _crypto.has_configured_master_key()


def _key(kid: str) -> bytes:
    master = _crypto._master_keys().get(kid)
    if master is None:
        raise FieldDecryptError(f"unknown key id {kid}")
    cache_key = (kid, master)
    with _KEY_CACHE_LOCK:
        cached = _KEY_CACHE.get(cache_key)
        if cached is not None:
            return cached
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT, info=b"ai-field:" + kid.encode("ascii")).derive(master)
    with _KEY_CACHE_LOCK:
        if len(_KEY_CACHE) >= _KEY_CACHE_MAX and cache_key not in _KEY_CACHE:
            oldest_key = next(iter(_KEY_CACHE))
            _KEY_CACHE.pop(oldest_key, None)
        _KEY_CACHE[cache_key] = derived
    return derived


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt_field(plaintext: str, *, context: str) -> str:
    if not available():
        raise RuntimeError("field encryption requires cryptography and a configured master key")
    kid = _crypto.current_kid()
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(_key(kid)).encrypt(nonce, str(plaintext).encode("utf-8"), str(context).encode("utf-8"))
    return f"{PREFIX}{kid}:{base64.b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt_field(value: str, *, context: str) -> str:
    """Decrypt an ``afc:v1:`` value; any other value is returned unchanged."""
    if not is_encrypted(value):
        return value
    try:
        kid, payload = value[len(PREFIX):].split(":", 1)
        raw = base64.b64decode(payload.encode("ascii"), validate=True)
        plain = AESGCM(_key(kid)).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], str(context).encode("utf-8"))
    except (ValueError, TypeError, InvalidTag, FieldDecryptError) as exc:
        logger.error("AI field decrypt failed code=AI_FIELD_DECRYPT_FAILED")
        raise FieldDecryptError("cannot decrypt stored conversation content") from exc
    return plain.decode("utf-8")
