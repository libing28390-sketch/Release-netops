"""
HashiCorp Vault KV v2 integration for device credential storage.

When VAULT_ENABLED=true in .env, new devices with credential_source='vault'
will store/retrieve credentials from Vault instead of the local DB.

Vault KV v2 path convention:
  {VAULT_MOUNT}/data/{VAULT_PREFIX}/{device_hostname_or_id}
  e.g. secret/data/netops/devices/core-sw-01

Each secret contains keys:
  username, password, enable_password, priv_username
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy-import hvac to make it an optional dependency
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    from core.config import settings
    if not settings.VAULT_ENABLED:
        return None
    try:
        import hvac
    except ImportError:
        logger.warning("hvac package not installed — Vault integration disabled. Install with: pip install hvac")
        return None
    _client = hvac.Client(url=settings.VAULT_ADDR, token=settings.VAULT_TOKEN)
    if not _client.is_authenticated():
        logger.error("Vault authentication failed — check VAULT_TOKEN")
        _client = None
        return None
    logger.info("Vault client authenticated at %s", settings.VAULT_ADDR)
    return _client


def vault_available() -> bool:
    """Check if Vault is configured and reachable."""
    from core.config import settings
    if not settings.VAULT_ENABLED:
        return False
    return _get_client() is not None


def _build_path(vault_path: str) -> str:
    """Normalise a vault_path into mount-relative path."""
    from core.config import settings
    if vault_path:
        return vault_path.strip('/')
    return settings.VAULT_PREFIX


def read_credentials(vault_path: str) -> dict[str, str] | None:
    """
    Read device credentials from Vault KV v2.
    Returns dict with keys: username, password, enable_password, priv_username
    or None on failure.
    """
    client = _get_client()
    if not client:
        return None
    from core.config import settings
    path = _build_path(vault_path)
    try:
        resp = client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point=settings.VAULT_MOUNT,
        )
        data = resp.get('data', {}).get('data', {})
        return {
            'username': data.get('username', ''),
            'password': data.get('password', ''),
            'enable_password': data.get('enable_password', ''),
            'priv_username': data.get('priv_username', ''),
        }
    except Exception as exc:
        logger.error("Failed to read Vault secret at %s: %s", path, exc)
        return None


def write_credentials(vault_path: str, creds: dict[str, str]) -> bool:
    """
    Write device credentials to Vault KV v2.
    creds should contain: username, password, enable_password, priv_username
    Returns True on success.
    """
    client = _get_client()
    if not client:
        return False
    from core.config import settings
    path = _build_path(vault_path)
    try:
        client.secrets.kv.v2.create_or_update_secret(
            path=path,
            secret={
                'username': creds.get('username', ''),
                'password': creds.get('password', ''),
                'enable_password': creds.get('enable_password', ''),
                'priv_username': creds.get('priv_username', ''),
            },
            mount_point=settings.VAULT_MOUNT,
        )
        logger.info("Wrote credentials to Vault at %s", path)
        return True
    except Exception as exc:
        logger.error("Failed to write Vault secret at %s: %s", path, exc)
        return False


def delete_credentials(vault_path: str) -> bool:
    """Delete a device's credentials from Vault."""
    client = _get_client()
    if not client:
        return False
    from core.config import settings
    path = _build_path(vault_path)
    try:
        client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path,
            mount_point=settings.VAULT_MOUNT,
        )
        logger.info("Deleted Vault secret at %s", path)
        return True
    except Exception as exc:
        logger.error("Failed to delete Vault secret at %s: %s", path, exc)
        return False


def resolve_device_credentials(device: dict[str, Any]) -> dict[str, str]:
    """
    Unified credential resolver.
    - If credential_source='vault' and Vault is available, fetch from Vault.
    - Otherwise, decrypt from local DB fields.
    Returns dict: {username, password, enable_password, priv_username}
    """
    from core.crypto import decrypt_credential

    source = (device.get('credential_source') or 'local').lower()

    if source == 'vault' and vault_available():
        vault_path = device.get('vault_path', '')
        if vault_path:
            creds = read_credentials(vault_path)
            if creds:
                return creds
            logger.warning("Vault read failed for %s, falling back to local", vault_path)

    # Local decryption fallback
    return {
        'username': device.get('username') or '',
        'password': decrypt_credential(device.get('password')) or '',
        'enable_password': decrypt_credential(device.get('enable_password')) or '',
        'priv_username': device.get('priv_username') or '',
    }
