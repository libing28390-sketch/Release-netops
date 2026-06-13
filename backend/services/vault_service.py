"""
HashiCorp Vault KV v2 integration for device credential storage.

When VAULT_ENABLED=true in .env, new devices with credential_source='vault'
will store/retrieve credentials from Vault instead of the local DB.

Vault KV v2 path convention:
  {VAULT_MOUNT}/data/{VAULT_PREFIX}/{device_hostname_or_id}
  e.g. secret/data/netops/devices/core-sw-01

Each secret contains keys:
  username, password, enable_password, priv_username,
  normal_username, normal_password, admin_username, admin_password
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
            'normal_username': data.get('normal_username', ''),
            'normal_password': data.get('normal_password', ''),
            'admin_username': data.get('admin_username', ''),
            'admin_password': data.get('admin_password', ''),
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
                'normal_username': creds.get('normal_username', ''),
                'normal_password': creds.get('normal_password', ''),
                'admin_username': creds.get('admin_username', ''),
                'admin_password': creds.get('admin_password', ''),
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


def resolve_device_credentials(device: dict) -> dict[str, str]:
    """
    Unified credential resolver.
    - If credential_source='vault' and Vault is available, fetch from Vault.
    - Otherwise, decrypt from local DB fields (supporting credentials table).
    Returns dict: {username, password, enable_password, priv_username,
                    normal_username, normal_password, admin_username, admin_password}

    Enable-secret fallback policy:
      If `enable_password` is not explicitly set, fall back to the admin password
      (then the generic password). This matches the UI contract "Enable Secret
      toggle ON but blank = use admin password as enable secret".
    """
    from core.crypto import decrypt_credential

    source = (device.get('credential_source') or 'local').lower()

    resolved: dict[str, str] | None = None
    if source == 'vault' and vault_available():
        vault_path = device.get('vault_path', '')
        if vault_path:
            resolved = read_credentials(vault_path)
            if resolved is None:
                logger.warning("Vault read failed for %s, falling back to local", vault_path)

    if resolved is None:
        # Check if credential_id is set to retrieve from credentials table
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
                    logger.warning(f"Failed to fetch credentials for id {credential_id}: {e}")
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"Database error during resolve_device_credentials in vault_service: {e}")

        # Local decryption fallback
        resolved = {
            'username': db_creds.get('username') or device.get('username') or '',
            'password': decrypt_credential(db_creds.get('encrypted_password') or device.get('password')) or '',
            'enable_password': decrypt_credential(db_creds.get('enable_password') or device.get('enable_password')) or '',
            'priv_username': device.get('priv_username') or '',
            'normal_username': device.get('normal_username') or '',
            'normal_password': decrypt_credential(device.get('normal_password')) or '',
            'admin_username': device.get('admin_username') or '',
            'admin_password': decrypt_credential(device.get('admin_password')) or '',
        }

    # ── Enable-secret fallback ─────────────────────────────────────────
    # If no explicit enable_password is configured, use admin_password
    # (or the generic password as a last resort). This is what users
    # expect when the "Enable Secret" UI toggle is ON but the input is
    # left blank — the system should automatically use the admin creds.
    if not resolved.get('enable_password'):
        resolved['enable_password'] = (
            resolved.get('admin_password') or
            resolved.get('password') or
            ''
        )

    return resolved
