"""
Credential encryption/decryption using Fernet (AES-128-CBC).
The encryption key is derived from settings.CREDENTIAL_ENCRYPTION_KEY via PBKDF2.
"""

import base64
import logging
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Module-level cache for the Fernet instance
_fernet: Fernet | None = None
_SALT = b'netops-credential-salt-v1'  # Fixed salt — acceptable for symmetric key derivation from a strong master key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    from core.config import settings
    key_material = settings.CREDENTIAL_ENCRYPTION_KEY

    # Reject obvious unsafe defaults / placeholders. The startup must hard-fail
    # so an operator can never run production with an unconfigured key — losing
    # this key after data is encrypted means losing every stored credential.
    _bad_values = {
        '',
        'change-me-to-a-random-secret',
        'replace-with-a-32-char-random-secret-key',
    }
    if (
        key_material is None
        or key_material in _bad_values
        or '__CHANGE_ME__' in (key_material or '')
    ):
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is not configured.\n"
            "Generate a real value and put it in your .env before starting:\n"
            "    openssl rand -hex 32\n"
            "Then set:\n"
            "    CREDENTIAL_ENCRYPTION_KEY=<the-generated-value>\n"
        )
    if len(key_material) < 24:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is too short (< 24 chars). "
            "Use `openssl rand -hex 32` to generate a stronger key."
        )

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480_000,
    )
    derived = kdf.derive(key_material.encode('utf-8'))
    _fernet = Fernet(base64.urlsafe_b64encode(derived))
    return _fernet


_ENCRYPTED_PREFIX = 'enc:v1:'


def encrypt_credential(plaintext: str | None) -> str | None:
    """Encrypt a credential string. Returns prefixed ciphertext."""
    if not plaintext:
        return plaintext
    if plaintext.startswith(_ENCRYPTED_PREFIX):
        return plaintext  # Already encrypted
    f = _get_fernet()
    token = f.encrypt(plaintext.encode('utf-8'))
    return _ENCRYPTED_PREFIX + token.decode('ascii')


def decrypt_credential(stored: str | None) -> str | None:
    """Decrypt a credential string. Handles legacy plaintext gracefully."""
    if not stored:
        return stored
    if not stored.startswith(_ENCRYPTED_PREFIX):
        # Legacy plaintext — return as-is (will be encrypted on next update)
        return stored
    f = _get_fernet()
    token = stored[len(_ENCRYPTED_PREFIX):].encode('ascii')
    try:
        return f.decrypt(token).decode('utf-8')
    except InvalidToken:
        logger.error("Failed to decrypt credential — key mismatch or data corruption")
        return None


def resolve_device_credentials(device: dict) -> tuple[str, str, int]:
    """
    统一解析设备的登录用户名、解密后的密码以及SSH端口。
    采用多级回退策略：优先 normal_username -> 回退 username -> 最终 admin_username。
    自动处理解密。
    """
    if not isinstance(device, dict):
        return 'root', '', 22

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

