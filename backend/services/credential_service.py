"""
credential_service.py — 凭据中心服务层 (Credential Vault)

Provides CRUD for the `credentials` table that backs the CMDB credential vault.

Security:
  - All secret columns (password, enable_password, private_key, snmp_community)
    are encrypted with AES-256-GCM via core.crypto before being written.
  - Secret values are NEVER returned in plaintext from list/get endpoints; instead
    boolean "has_*" flags indicate whether a secret is set.
  - Devices reference credentials by `credential_id` foreign key.
"""

import uuid
import logging
import hmac
from datetime import datetime, timezone

from core.crypto import decrypt_credential, encrypt_credential

logger = logging.getLogger(__name__)

# Secret columns that must be encrypted at rest and masked on read.
_SECRET_FIELDS = ('encrypted_password', 'enable_password', 'private_key', 'snmp_community')

_ACCOUNT_ROLE_LABELS = {
    'normal': '普通账号',
    'admin': '特权账号',
    'login': '登录账号',
    'mixed': '多角色',
    'shared': '通用账号',
    'unbound': '未关联',
}
_EXPLICIT_ACCOUNT_ROLES = {'normal', 'admin', 'shared', 'unbound'}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def _to_safe_view(row) -> dict:
    """Strip secret material, exposing only presence flags."""
    d = _row_to_dict(row)
    safe = {
        'id': d.get('id'),
        'credential_name': d.get('credential_name'),
        'credential_type': d.get('credential_type'),
        'username': d.get('username') or '',
        'account_role': d.get('account_role') or 'unbound',
        'created_at': d.get('created_at'),
        'has_password': bool(d.get('encrypted_password')),
        'has_enable_password': bool(d.get('enable_password')),
        'has_private_key': bool(d.get('private_key')),
        'has_snmp_community': bool(d.get('snmp_community')),
        'snmp_server': d.get('snmp_server') or '',
    }
    return safe


def _normalize_username(value: str | None) -> str:
    return (value or '').strip().lower()


def _infer_device_account_role(credential_id: str, credential_username: str, device: dict) -> str:
    """Infer how the credential username is used by a linked device.

    The credential vault stores the actual login username, not a role. For legacy
    single-account devices or incomplete dual-account data, keep the role generic.
    """
    dev_cred_id = device.get('credential_id')
    dev_admin_cred_id = device.get('admin_credential_id')

    if dev_admin_cred_id == credential_id:
        return 'admin'
    if dev_cred_id == credential_id:
        return 'normal'

    username = _normalize_username(credential_username)
    normal_username = _normalize_username(device.get('normal_username'))
    admin_username = _normalize_username(device.get('admin_username'))

    if username and admin_username and username == admin_username:
        return 'admin'
    if username and normal_username and username == normal_username:
        return 'normal'
    return 'login'


def _account_role_from_devices(credential_id: str, credential_username: str, devices: list[dict]) -> str:
    if not devices:
        return 'unbound'

    roles = {
        _infer_device_account_role(credential_id, credential_username, device)
        for device in devices
    }
    if len(roles) > 1:
        return 'mixed'
    return next(iter(roles))


def _with_account_role(view: dict, devices: list[dict]) -> dict:
    stored_role = str(view.get('account_role') or '').strip().lower()
    role = stored_role if stored_role in _EXPLICIT_ACCOUNT_ROLES else ''
    if role == 'unbound' and devices:
        role = _account_role_from_devices(view.get('id') or '', view.get('username') or '', devices)
    if not role:
        role = _account_role_from_devices(view.get('id') or '', view.get('username') or '', devices)

    # Device-local rows created by asset entry historically stored the generic
    # device username (often ``admin``), even when the row was referenced by
    # the normal-account slot.  The binding slot is authoritative for the
    # public view, so expose the username that is actually used by that slot.
    # This changes display metadata only; it never changes the encrypted secret.
    if stored_role == 'unbound' and devices and role in ('normal', 'admin'):
        credential_id = str(view.get('id') or '')
        candidates = []
        for device in devices:
            binding_role = _infer_device_account_role(credential_id, view.get('username') or '', device)
            username_key = 'normal_username' if binding_role == 'normal' else 'admin_username'
            username = str(device.get(username_key) or '').strip()
            if username:
                candidates.append(username)
        if candidates and len(set(candidates)) == 1:
            view['username'] = candidates[0]

    view['account_role'] = role
    view['account_role_label'] = _ACCOUNT_ROLE_LABELS.get(role, role)
    return view


def _public_device_refs(devices: list[dict], credential_id: str | None = None) -> list[dict]:
    return [
        {
            'id': d.get('id'),
            'hostname': d.get('hostname'),
            'ip_address': d.get('ip_address'),
            'binding_role': (
                'admin' if credential_id and str(d.get('admin_credential_id') or '') == str(credential_id)
                else 'normal'
            ),
        }
        for d in devices
    ]


def list_credentials(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM credentials ORDER BY credential_name"
    ).fetchall()
    res = []
    for r in rows:
        view = _to_safe_view(r)
        device_rows = _list_devices_using_rows(conn, view["id"])
        view["device_count"] = len(device_rows)
        view["devices"] = _public_device_refs(device_rows[:5], view["id"])
        view["devices_truncated"] = len(device_rows) > 5
        _with_account_role(view, device_rows)
        res.append(view)
    return res


def get_credential(conn, cred_id: str) -> dict:
    row = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if not row:
        raise ValueError(f"Credential not found: {cred_id}")
    view = _to_safe_view(row)
    device_rows = _list_devices_using_rows(conn, cred_id)
    view["device_count"] = len(device_rows)
    view["devices"] = _public_device_refs(device_rows, cred_id)
    return _with_account_role(view, device_rows)


def _name_exists(conn, name: str, exclude_id: str | None = None) -> bool:
    if exclude_id:
        row = conn.execute(
            "SELECT 1 FROM credentials WHERE credential_name = ? AND id != ?",
            (name, exclude_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM credentials WHERE credential_name = ?", (name,)
        ).fetchone()
    return row is not None


def create_credential(conn, *, credential_name: str, credential_type: str = 'ssh_password',
                      username: str = '', account_role: str = 'normal', password: str = '', enable_password: str = '',
                      private_key: str = '', snmp_community: str = '', snmp_server: str = '') -> dict:
    if _name_exists(conn, credential_name):
        raise ValueError(f"Credential name already exists: {credential_name}")
    if credential_type == 'snmpv2' and not str(snmp_community or '').strip():
        raise ValueError('SNMPv2 credentials require an SNMP Community')

    cred_id = f"cred-{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    conn.execute(
        """INSERT INTO credentials
           (id, credential_name, credential_type, username, account_role, encrypted_password,
            enable_password, private_key, snmp_community, snmp_server, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cred_id, credential_name, credential_type, username, account_role,
            encrypt_credential(password) or '',
            encrypt_credential(enable_password) or '',
            encrypt_credential(private_key) or '',
            encrypt_credential(snmp_community) or '',
            str(snmp_server or '').strip(),
            now,
        ),
    )
    conn.commit()
    logger.info(f"[CredentialService] Created credential '{credential_name}'")
    return get_credential(conn, cred_id)


def update_credential(conn, cred_id: str, **fields) -> dict:
    existing = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if not existing:
        raise ValueError(f"Credential not found: {cred_id}")

    if 'credential_name' in fields and fields['credential_name'] is not None:
        if _name_exists(conn, fields['credential_name'], exclude_id=cred_id):
            raise ValueError(f"Credential name already exists: {fields['credential_name']}")

    if fields.get('credential_type') == 'snmpv2':
        community = fields.get('snmp_community')
        if community is None:
            community = decrypt_credential(_row_to_dict(existing).get('snmp_community')) or ''
        if not str(community or '').strip():
            raise ValueError('SNMPv2 credentials require an SNMP Community')

    updates: list[str] = []
    params: list = []

    # Plain (non-secret) columns
    for key in ('credential_name', 'credential_type', 'username', 'account_role', 'snmp_server'):
        if key in fields and fields[key] is not None:
            updates.append(f"{key} = ?")
            params.append(fields[key])

    # Secret columns: only overwrite when a non-None value is supplied; encrypt it.
    # An empty string explicitly clears the secret; None leaves it untouched.
    secret_map = {
        'password': 'encrypted_password',
        'enable_password': 'enable_password',
        'private_key': 'private_key',
        'snmp_community': 'snmp_community',
    }
    for in_key, col in secret_map.items():
        if in_key in fields and fields[in_key] is not None:
            updates.append(f"{col} = ?")
            params.append(encrypt_credential(fields[in_key]) or '')

    if not updates:
        return get_credential(conn, cred_id)

    params.append(cred_id)
    conn.execute(f"UPDATE credentials SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    logger.info(f"[CredentialService] Updated credential {cred_id}")
    return get_credential(conn, cred_id)


def validate_secret_change_confirmation(
    conn,
    cred_id: str,
    *,
    old_password: str | None = None,
    old_enable_password: str | None = None,
    new_password: str | None = None,
    new_enable_password: str | None = None,
) -> dict:
    """Validate the old secret before a password change is accepted.

    The comparison happens server-side against the encrypted vault value.  The
    returned record is only the raw database row for internal callers; secret
    values must never be returned from an API response or written to logs.
    """
    row = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if not row:
        raise ValueError(f"Credential not found: {cred_id}")

    checks = (
        (new_password, old_password, 'encrypted_password', 'old_password'),
        (new_enable_password, old_enable_password, 'enable_password', 'old_enable_password'),
    )
    for new_value, old_value, column, field_name in checks:
        if new_value is None:
            continue
        if old_value is None:
            raise ValueError(f"{field_name} is required when changing the credential secret")
        stored_value = decrypt_credential(row[column] or '')
        if not stored_value or not hmac.compare_digest(stored_value, old_value):
            raise ValueError(f"{field_name} is incorrect")
    return dict(row)


def count_devices_using(conn, cred_id: str) -> int:
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS cnt
               FROM devices
               WHERE credential_id = ? OR admin_credential_id = ?""",
            (cred_id, cred_id),
        ).fetchone()
    except Exception:
        return 0
    if row is None:
        return 0
    if hasattr(row, 'keys') and 'cnt' in row.keys():
        return int(row['cnt'] or 0)
    return int(row[0] or 0)


def delete_credential(conn, cred_id: str) -> None:
    existing = conn.execute("SELECT id FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if not existing:
        raise ValueError(f"Credential not found: {cred_id}")

    in_use = count_devices_using(conn, cred_id)
    if in_use > 0:
        raise ValueError(
            f"Cannot delete credential: it is still referenced by {in_use} device(s). "
            "Reassign or clear those devices first."
        )
    conn.execute("DELETE FROM credentials WHERE id = ?", (cred_id,))
    conn.commit()
    logger.info(f"[CredentialService] Deleted credential {cred_id}")


def _list_devices_using_rows(conn, cred_id: str) -> list[dict]:
    """Return device info needed for safe credential metadata inference."""
    try:
        rows = conn.execute(
            """SELECT id, hostname, ip_address, username, normal_username, admin_username, auth_model, credential_id, admin_credential_id
               FROM devices
               WHERE credential_id = ? OR admin_credential_id = ?
               ORDER BY hostname""",
            (cred_id, cred_id),
        ).fetchall()
    except Exception:
        return []
    return [_row_to_dict(r) for r in rows]


def list_devices_using(conn, cred_id: str) -> list[dict]:
    """Return minimal device info for devices bound to this credential."""
    return _public_device_refs(_list_devices_using_rows(conn, cred_id))
