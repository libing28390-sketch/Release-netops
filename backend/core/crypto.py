"""
Credential encryption/decryption.

Primary algorithm: AES-256-GCM (authenticated encryption), matching the CMDB
design specification. The 256-bit key is derived from
settings.CREDENTIAL_ENCRYPTION_KEY via PBKDF2-HMAC-SHA256.

Ciphertext format:
    enc:v2:<base64(nonce[12] || ciphertext || tag)>   ← AES-256-GCM (current)
    enc:v1:<fernet-token>                              ← legacy Fernet (read-only)

Legacy `enc:v1:` (Fernet / AES-128-CBC) tokens are still decrypted transparently
for backward compatibility, but all new writes use AES-256-GCM. Any value without
a recognised prefix is treated as legacy plaintext and returned unchanged.
"""

import os
import base64
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Module-level caches for derived keys
_aes_key: bytes | None = None
_fernet: Fernet | None = None

# Fixed salt — acceptable for symmetric key derivation from a strong master key.
_SALT = b'netops-credential-salt-v1'
_PBKDF2_ITERATIONS = 480_000
_NONCE_LEN = 12  # 96-bit nonce, recommended for GCM

_PREFIX_V2 = 'enc:v2:'  # AES-256-GCM (current)
_PREFIX_V1 = 'enc:v1:'  # Fernet (legacy, decrypt-only)


def _derive_key() -> bytes:
    """Derive a 32-byte (256-bit) key from the configured master secret."""
    from core.config import settings
    key_material = settings.CREDENTIAL_ENCRYPTION_KEY
    if not key_material or key_material == 'change-me-to-a-random-secret':
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is not configured. "
            "Set it in .env or environment variables before starting the application."
        )
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(key_material.encode('utf-8'))


def _get_aes_key() -> bytes:
    global _aes_key
    if _aes_key is None:
        _aes_key = _derive_key()
    return _aes_key


def _get_fernet() -> Fernet:
    """Lazy Fernet instance for decrypting legacy enc:v1: tokens."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(base64.urlsafe_b64encode(_get_aes_key()))
    return _fernet


def encrypt_credential(plaintext: str | None) -> str | None:
    """Encrypt a credential string using AES-256-GCM. Returns prefixed ciphertext."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_PREFIX_V2) or plaintext.startswith(_PREFIX_V1):
        return plaintext  # Already encrypted
    aesgcm = AESGCM(_get_aes_key())
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    blob = base64.b64encode(nonce + ciphertext).decode('ascii')
    return _PREFIX_V2 + blob


def decrypt_credential(stored: str | None) -> str | None:
    """Decrypt a credential string. Handles AES-GCM, legacy Fernet, and plaintext."""
    if not stored:
        return stored

    if stored.startswith(_PREFIX_V2):
        try:
            raw = base64.b64decode(stored[len(_PREFIX_V2):].encode('ascii'))
            nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
            aesgcm = AESGCM(_get_aes_key())
            return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
        except Exception:
            logger.error("Failed to decrypt AES-256-GCM credential — key mismatch or data corruption")
            return None

    if stored.startswith(_PREFIX_V1):
        token = stored[len(_PREFIX_V1):].encode('ascii')
        try:
            return _get_fernet().decrypt(token).decode('utf-8')
        except InvalidToken:
            logger.error("Failed to decrypt legacy Fernet credential — key mismatch or data corruption")
            return None

    # Legacy plaintext — return as-is (will be re-encrypted with AES-GCM on next update)
    return stored


def resolve_device_credentials(device: dict) -> tuple[str, str, int]:
    """
    统一解析设备的登录用户名、解密后的密码以及SSH端口。
    采用多级回退策略：优先 normal_username -> 回退 username -> 最终 admin_username。
    自动处理解密并集成凭据中心（credentials表）。
    """
    if not isinstance(device, dict):
        return 'root', '', 22

    credential_id = device.get('credential_id')
    db_creds = {}
    if credential_id:
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute('SELECT * FROM credentials WHERE id = ?', (credential_id,)).fetchone()
                if row:
                    db_creds = dict(row)
            except Exception as e:
                logger.warning(f"Failed to query credentials for id {credential_id}: {e}")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Database error during resolve_device_credentials: {e}")

    # Use database credentials if present, else fallback to device dict
    username = db_creds.get('username') or device.get('username') or ''
    encrypted_password = (
        db_creds.get('encrypted_password') or 
        device.get('normal_password') or 
        device.get('password') or 
        device.get('admin_password') or 
        ''
    ).strip()

    if username and encrypted_password:
        try:
            password = decrypt_credential(encrypted_password) or encrypted_password
        except Exception:
            password = encrypted_password
    else:
        # Fallback to legacy device-embedded credentials
        normal_user = (device.get('normal_username') or '').strip()
        normal_pass = (device.get('normal_password') or '').strip()
        if normal_user and normal_pass:
            username = normal_user
            try:
                password = decrypt_credential(normal_pass) or normal_pass
            except Exception:
                password = normal_pass
        else:
            username = (device.get('username') or '').strip()
            raw_password = (device.get('password') or '').strip()
            if not username or not raw_password:
                username = (device.get('admin_username') or '').strip() or username
                raw_password = (device.get('admin_password') or '').strip() or raw_password
            try:
                password = decrypt_credential(raw_password) or raw_password
            except Exception:
                password = raw_password

    if not username:
        username = 'root'

    try:
        port = int(device.get('port') or device.get('management_port') or 22)
    except Exception:
        port = 22

    return username, password, port
