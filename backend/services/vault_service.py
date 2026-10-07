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


def credential_is_shared(
    conn,
    credential_id: str | None,
    credential_row: dict | None = None,
    *,
    device_hostname: str | None = None,
) -> bool:
    """Return whether a credential is a shared credential-center binding.

    ``credentials.id`` is also used for device-local records created from a
    password typed in the asset form.  Those records intentionally have the
    ``unbound`` role and must continue to resolve from the device/asset cache.
    For legacy rows without an explicit role, more than one device reference
    is treated as shared.
    """
    if not credential_id:
        return False
    row = credential_row
    if row is None:
        fetched = conn.execute(
            'SELECT account_role, credential_name FROM credentials WHERE id = ?',
            (credential_id,),
        ).fetchone()
        row = dict(fetched) if fetched else {}
    role = str(row.get('account_role') or 'unbound').strip().lower()
    if role != 'unbound':
        return True
    name = str(row.get('credential_name') or '').strip().lower()
    hostname = str(device_hostname or '').strip().lower()
    is_generated_device_record = name.startswith('cred-device-') or (
        hostname and name.startswith(f'cred-{hostname}-')
    )
    if not is_generated_device_record:
        # Explicitly referenced, named credentials from older schemas did not
        # always carry account_role. Treat them as shared unless they match the
        # device-local naming convention used by asset-form password entry.
        return True
    count_row = conn.execute(
        'SELECT COUNT(*) AS reference_count FROM devices '
        'WHERE credential_id = ? OR admin_credential_id = ?',
        (credential_id, credential_id),
    ).fetchone()
    return int((dict(count_row).get('reference_count') if count_row else 0) or 0) > 1

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

    Enable-secret policy:
      `enable_password` is independent from SSH login credentials. It is
      returned only when explicitly configured and is never inferred from an
      admin or normal login password.
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

    # Resolve the linked asset before reading the credential vault.  A device
    # row normally carries these IDs, but callers such as the terminal launch
    # path may pass a physical_assets row directly.
    asset = {}
    asset_id = str(device.get('asset_id') or '').strip()
    if asset_id:
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute(
                    '''SELECT credential_id, admin_credential_id, snmp_credential_id,
                              username, password, normal_username, normal_password,
                              admin_username, admin_password, enable_password,
                              snmp_community, auth_model
                       FROM physical_assets WHERE id = ?''',
                    (asset_id,),
                ).fetchone()
                asset = dict(row) if row else {}
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning('Failed to load linked asset credentials for %s: %s', asset_id, exc)

    credential_id = device.get('credential_id') or asset.get('credential_id')
    admin_credential_id = device.get('admin_credential_id') or asset.get('admin_credential_id')
    snmp_credential_id = device.get('snmp_credential_id') or asset.get('snmp_credential_id')
    normal_bound = False
    admin_bound = False
    db_snmp_creds = {}
    db_creds = {}
    db_admin_creds = {}
    linked_role_cache_authoritative = False

    if snmp_credential_id:
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                row = conn.execute('SELECT * FROM credentials WHERE id = ?', (snmp_credential_id,)).fetchone()
                if row:
                    db_snmp_creds = dict(row)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning('Failed to fetch SNMP credential for %s: %s', device.get('hostname') or device.get('id'), exc)

    if resolved is None:
        # A bound credential is the authority for that account role.  The
        # asset/device password columns remain only a legacy fallback for
        # unbound records and must not override a newer vault value.
        if credential_id or admin_credential_id:
            try:
                from database import get_db_connection
                conn = get_db_connection()
                try:
                    if credential_id:
                        row = conn.execute('SELECT * FROM credentials WHERE id = ?', (credential_id,)).fetchone()
                        if row:
                            db_creds = dict(row)
                    if admin_credential_id:
                        row = conn.execute('SELECT * FROM credentials WHERE id = ?', (admin_credential_id,)).fetchone()
                        if row:
                            db_admin_creds = dict(row)
                except Exception as e:
                    logger.warning(f"Failed to fetch credentials in resolve_device_credentials: {e}")
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"Database error during resolve_device_credentials in vault_service: {e}")

        # A device-local record also has a credentials.id, but its explicit
        # ``unbound`` role means the device/asset password remains authoritative.
        # Only shared credential-center records may suppress that fallback.
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                normal_bound = credential_is_shared(conn, credential_id, db_creds, device_hostname=device.get('hostname')) if credential_id else False
                admin_bound = credential_is_shared(conn, admin_credential_id, db_admin_creds, device_hostname=device.get('hostname')) if admin_credential_id else False
            finally:
                conn.close()
        except Exception as exc:
            logger.warning('Failed to classify credential binding for %s: %s', device.get('hostname') or device.get('id'), exc)
            normal_bound = False
            admin_bound = False

        # A legacy generic credential_id must not collapse an explicitly
        # modelled dual-account asset back into one account. Only credentials
        # whose account_role is declared may override the linked asset's
        # normal/admin pairs.
        linked_role_cache_authoritative = (
            str(asset.get('auth_model') or '').strip().lower() == 'dual'
            and bool(db_creds)
            and str(db_creds.get('account_role') or 'unbound').strip().lower() == 'unbound'
            and not admin_credential_id
        )
        if linked_role_cache_authoritative:
            normal_bound = False
            admin_bound = False

        # Local decryption fallback.  Prefer the vault username/password for
        # a bound role; otherwise use the legacy device fields.
        resolved = {
            'username': db_creds.get('username') or device.get('username') or '',
            'password': decrypt_credential(db_creds.get('encrypted_password') or device.get('password')) or '',
            'enable_password': decrypt_credential(
                db_admin_creds.get('enable_password')
                or db_creds.get('enable_password')
                or device.get('enable_password')
            ) or '',
            'priv_username': device.get('priv_username') or '',
            'normal_username': db_creds.get('username') if normal_bound and db_creds else device.get('normal_username') or '',
            'normal_password': decrypt_credential(
                db_creds.get('encrypted_password') if normal_bound and db_creds else device.get('normal_password')
            ) or '',
            'admin_username': (
                db_admin_creds.get('username') if admin_bound and db_admin_creds
                else (db_creds.get('username') if normal_bound and db_creds else device.get('admin_username') or '')
            ),
            'admin_password': decrypt_credential(
                (db_admin_creds.get('encrypted_password') if admin_bound and db_admin_creds
                 else (db_creds.get('encrypted_password') if normal_bound and db_creds else device.get('admin_password')))
            ) or '',
            'snmp_community': decrypt_credential(
                db_snmp_creds.get('snmp_community')
                or db_creds.get('snmp_community')
                or device.get('snmp_community')
            ) or '',
            'snmp_server': str(
                db_snmp_creds.get('snmp_server')
                or db_creds.get('snmp_server')
                or device.get('snmp_server')
                or ''
            ).strip(),
        }

    # Vault-backed records still need the same shared-vs-device-local
    # classification before deciding whether the linked asset cache may be
    # used below.
    if resolved is not None and (credential_id or admin_credential_id) and not (normal_bound or admin_bound):
        try:
            from database import get_db_connection
            conn = get_db_connection()
            try:
                normal_bound = credential_is_shared(conn, credential_id, device_hostname=device.get('hostname')) if credential_id else False
                admin_bound = credential_is_shared(conn, admin_credential_id, device_hostname=device.get('hostname')) if admin_credential_id else False
            finally:
                conn.close()
        except Exception as exc:
            logger.warning('Failed to classify vault credential binding for %s: %s', device.get('hostname') or device.get('id'), exc)
        if linked_role_cache_authoritative:
            normal_bound = False
            admin_bound = False

    if asset:
        # Only unbound roles may read the legacy asset cache.  This is the
        # critical anti-stale rule: editing a shared credential in the vault
        # must take effect for every bound asset without a fan-out copy.
        for role in ('normal', 'admin'):
            role_bound = normal_bound if role == 'normal' else (admin_bound or normal_bound)
            if role_bound:
                continue
            username_key = f'{role}_username'
            password_key = f'{role}_password'
            asset_username = str(asset.get(username_key) or '').strip()
            asset_password = decrypt_credential(asset.get(password_key)) or ''
            if asset_username:
                resolved[username_key] = asset_username
            if asset_password:
                resolved[password_key] = asset_password

        if not normal_bound and not admin_bound:
            asset_enable_password = decrypt_credential(asset.get('enable_password')) or ''
            if asset_enable_password:
                resolved['enable_password'] = asset_enable_password

        # SNMP is independent from the SSH account binding. A shared SSH
        # credential may have no SNMP secret while the linked asset has a
        # device-local community. A configured credential-center value wins.
        if asset.get('snmp_community') and not resolved.get('snmp_community'):
            resolved['snmp_community'] = decrypt_credential(asset.get('snmp_community')) or ''

    # SNMP bindings are independent from Vault/SSH account resolution.
    if db_snmp_creds:
        resolved['snmp_community'] = decrypt_credential(db_snmp_creds.get('snmp_community')) or resolved.get('snmp_community') or ''
        resolved['snmp_server'] = str(db_snmp_creds.get('snmp_server') or resolved.get('snmp_server') or '').strip()

    # Keep the generic return keys compatible for callers that have not yet
    # been migrated, but derive them from the explicit role pairs.
    normal_pair = (resolved.get('normal_username') or '', resolved.get('normal_password') or '')
    admin_pair = (resolved.get('admin_username') or '', resolved.get('admin_password') or '')
    legacy_pair = (resolved.get('username') or '', resolved.get('password') or '')
    if all(normal_pair):
        resolved['username'], resolved['password'] = normal_pair
    elif all(admin_pair):
        resolved['username'], resolved['password'] = admin_pair
    elif all(legacy_pair):
        resolved['username'], resolved['password'] = legacy_pair
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
    # Enable Secret is independent from both SSH login roles. An empty value
    # means the device does not require privilege escalation; never turn a
    # normal/admin login password into an implicit Enable secret.

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
    has_explicit_role_fields = any(
        resolved.get(key)
        for key in (
            'normal_username', 'normal_password',
            'admin_username', 'admin_password',
        )
    )
    if not has_explicit_role_fields:
        role_username = resolved.get('username') or ''
        role_password = resolved.get('password') or ''
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
            'server': resolved.get('snmp_server') or str(device.get('ip_address') or '').strip(),
            'community': resolved.get('snmp_community') or '',
            'port': int(device.get('snmp_port') or 161),
            'configured': bool(resolved.get('snmp_community')),
        },
    }
