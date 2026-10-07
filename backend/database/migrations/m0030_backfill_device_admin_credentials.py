"""Create missing device-local privileged credential records for dual-account devices."""

import uuid
from datetime import datetime, timezone


VERSION = 30
NAME = "backfill_device_admin_credentials"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade(cursor, _use_pg: bool) -> None:
    """Backfill metadata only; existing encrypted password values are reused."""
    rows = cursor.execute(
        """
        SELECT d.id, d.asset_id, d.hostname, d.admin_username, d.admin_password,
               d.enable_password
        FROM devices d
        WHERE COALESCE(d.admin_credential_id, '') = ''
          AND LOWER(COALESCE(d.auth_model, '')) = 'dual'
          AND COALESCE(d.admin_username, '') <> ''
        """
    ).fetchall()

    for row in rows:
        device_id, asset_id, hostname, username, encrypted_password, encrypted_enable = row
        credential_name = f"cred-{hostname or 'device'}-{str(device_id)[:8]}-admin"
        existing = cursor.execute(
            "SELECT id FROM credentials WHERE credential_name = ?",
            (credential_name,),
        ).fetchone()
        credential_id = existing[0] if existing else f"cred-{uuid.uuid4().hex[:12]}"

        if not existing:
            cursor.execute(
                """
                INSERT INTO credentials
                    (id, credential_name, credential_type, username, account_role,
                     encrypted_password, enable_password, snmp_community, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    credential_id,
                    credential_name,
                    'ssh_password',
                    username or '',
                    'unbound',
                    encrypted_password or '',
                    encrypted_enable or '',
                    '',
                    _now(),
                ),
            )

        cursor.execute(
            "UPDATE devices SET admin_credential_id = ? WHERE id = ?",
            (credential_id, device_id),
        )
        cursor.execute(
            "UPDATE physical_assets SET admin_credential_id = ? WHERE id = ?",
            (credential_id, asset_id),
        )
