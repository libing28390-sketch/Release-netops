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
    Returns the SSH account fields plus ``snmp_community``. Callers must never
    log or return the resolved dictionary.

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
            'snmp_community': decrypt_credential(
                db_creds.get('snmp_community') or device.get('snmp_community')
            ) or '',
        }

    # The CMDB asset is the source of truth for the two supported SSH roles.
    # Device/credentials.username is a legacy single-account field and must
    # not override the role-specific credentials stored on physical_assets.
    asset = {}
    asset_id = str(device.get('asset_id') or '').strip()
    if asset_id:
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute(
                    '''SELECT username, password, normal_username, normal_password,
                              admin_username, admin_password, enable_password
                       FROM physical_assets WHERE id = ?''',
                    (asset_id,),
                ).fetchone()
                asset = dict(row) if row else {}
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning('Failed to load linked asset credentials for %s: %s', asset_id, exc)

    if asset:
        for role in ('normal', 'admin'):
            username_key = f'{role}_username'
            password_key = f'{role}_password'
            asset_username = str(asset.get(username_key) or '').strip()
            asset_password = decrypt_credential(asset.get(password_key)) or ''
            if asset_username:
                resolved[username_key] = asset_username
            if asset_password:
                resolved[password_key] = asset_password
        asset_enable_password = decrypt_credential(asset.get('enable_password')) or ''
        if asset_enable_password:
            resolved['enable_password'] = asset_enable_password

        # Keep the generic return keys compatible for callers that have not
        # yet been migrated, but derive them from the normal role first.
        # Never use physical_assets.username/password as an SSH fallback.
        normal_pair = (
            resolved.get('normal_username') or '',
            resolved.get('normal_password') or '',
        )
        admin_pair = (
            resolved.get('admin_username') or '',
            resolved.get('admin_password') or '',
        )
        if all(normal_pair):
            resolved['username'], resolved['password'] = normal_pair
        elif all(admin_pair):
            resolved['username'], resolved['password'] = admin_pair
        else:
            resolved['username'] = ''
            resolved['password'] = ''

    # Older Vault records may not contain SNMP fields. Keep the key stable so
    # collectors can distinguish "not configured" from an unreachable agent.
    resolved['snmp_community'] = resolved.get('snmp_community') or ''

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


def resolve_collector_credentials(device: dict, *, ssh_role: str = 'normal') -> dict[str, object]:
    """Return the stable credential contract consumed by network collectors.

    SNMPv2c is the currently supported wire driver. Keeping the version and
    configured flag explicit prevents callers from treating an empty community
    as the legacy public default and leaves a safe extension point for SNMPv3.
    """
    role = str(ssh_role or 'normal').strip().lower()
    if role not in {'normal', 'admin'}:
        raise ValueError('ssh_role must be normal or admin')

    resolved = resolve_device_credentials(device)
    role_username = resolved.get(f'{role}_username') or ''
    role_password = resolved.get(f'{role}_password') or ''
    return {
        'ssh': {
            'username': role_username,
            'password': role_password,
            'enable_password': resolved.get('enable_password') or '',
            'port': int(device.get('management_port') or device.get('port') or 22),
            'role': role,
        },
        'snmp': {
            'version': '2c',
            'community': resolved.get('snmp_community') or '',
            'port': int(device.get('snmp_port') or 161),
            'configured': bool(resolved.get('snmp_community')),
        },
    }
