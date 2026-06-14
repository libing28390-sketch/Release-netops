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
from datetime import datetime, timezone

from core.crypto import encrypt_credential

logger = logging.getLogger(__name__)

# Secret columns that must be encrypted at rest and masked on read.
_SECRET_FIELDS = ('encrypted_password', 'enable_password', 'private_key', 'snmp_community')


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
        'created_at': d.get('created_at'),
        'has_password': bool(d.get('encrypted_password')),
        'has_enable_password': bool(d.get('enable_password')),
        'has_private_key': bool(d.get('private_key')),
        'has_snmp_community': bool(d.get('snmp_community')),
    }
    return safe


def list_credentials(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM credentials ORDER BY credential_name"
    ).fetchall()
    res = []
    for r in rows:
        view = _to_safe_view(r)
        view["devices"] = list_devices_using(conn, view["id"])
        res.append(view)
    return res


def get_credential(conn, cred_id: str) -> dict:
    row = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
    if not row:
        raise ValueError(f"Credential not found: {cred_id}")
    return _to_safe_view(row)


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
                      username: str = '', password: str = '', enable_password: str = '',
                      private_key: str = '', snmp_community: str = '') -> dict:
    if _name_exists(conn, credential_name):
        raise ValueError(f"Credential name already exists: {credential_name}")

    cred_id = f"cred-{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    conn.execute(
        """INSERT INTO credentials
           (id, credential_name, credential_type, username, encrypted_password,
            enable_password, private_key, snmp_community, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cred_id, credential_name, credential_type, username,
            encrypt_credential(password) or '',
            encrypt_credential(enable_password) or '',
            encrypt_credential(private_key) or '',
            encrypt_credential(snmp_community) or '',
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

    updates: list[str] = []
    params: list = []

    # Plain (non-secret) columns
    for key in ('credential_name', 'credential_type', 'username'):
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


def count_devices_using(conn, cred_id: str) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM devices WHERE credential_id = ?", (cred_id,)
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


def list_devices_using(conn, cred_id: str) -> list[dict]:
    """Return minimal device info for devices bound to this credential."""
    try:
        rows = conn.execute(
            "SELECT id, hostname, ip_address FROM devices WHERE credential_id = ? ORDER BY hostname",
            (cred_id,),
        ).fetchall()
    except Exception:
        return []
    return [_row_to_dict(r) for r in rows]
