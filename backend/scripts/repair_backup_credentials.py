"""
One-time repair: re-sync the credential vault to the privileged device account.

Background
----------
An earlier credential-decoupling migration captured the non-privileged "user"
account into the credentials vault and then wiped the device password columns,
which broke config backup (the user account lands at user-EXEC and cannot run
`show running-config`). After the operator manually reset the devices' admin/user
passwords on the equipment, the vault still held the old (rotated) values.

This script points every device's vault credential at the privileged account so
backups log in at privileged EXEC again — no enable step required.

Usage
-----
    python backend/scripts/repair_backup_credentials.py            # dry run
    python backend/scripts/repair_backup_credentials.py --apply    # write changes

Adjust the constants below if your privileged account differs.
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DATABASE_URL', '')

import database
from core.crypto import encrypt_credential

# ── Adjust these to match your environment ───────────────
PRIV_USERNAME = 'admin'      # privileged (priv-15) account used for backups
PRIV_PASSWORD = '123456'     # its password
ENABLE_PASSWORD = ''         # leave '' if the privileged account needs no enable
# ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write changes (default: dry run)')
    args = parser.parse_args()

    enc_pwd = encrypt_credential(PRIV_PASSWORD)
    enc_en = encrypt_credential(ENABLE_PASSWORD) if ENABLE_PASSWORD else ''

    conn = database.get_db_connection()
    try:
        rows = conn.execute(
            "SELECT d.id, d.hostname, d.credential_id, c.username AS cur_user "
            "FROM devices d LEFT JOIN credentials c ON d.credential_id = c.id"
        ).fetchall()

        updated, created, skipped = 0, 0, 0
        for r in rows:
            d = dict(r)
            host = d.get('hostname')
            cid = d.get('credential_id')

            if cid:
                if args.apply:
                    conn.execute(
                        "UPDATE credentials SET username = ?, encrypted_password = ?, "
                        "enable_password = ? WHERE id = ?",
                        (PRIV_USERNAME, enc_pwd, enc_en, cid),
                    )
                updated += 1
                print(f"  [update] {host:<8} cred={cid} {d.get('cur_user')!r} -> {PRIV_USERNAME!r}")
            else:
                # No credential yet — create one and bind it.
                import uuid
                from datetime import datetime, timezone
                new_id = f"cred-{uuid.uuid4().hex[:12]}"
                if args.apply:
                    conn.execute(
                        "INSERT INTO credentials (id, credential_name, credential_type, username, "
                        "encrypted_password, enable_password, snmp_community, created_at) "
                        "VALUES (?, ?, 'ssh_password', ?, ?, ?, '', ?)",
                        (new_id, f"cred-{host}-{d['id'][:8]}", PRIV_USERNAME, enc_pwd, enc_en,
                         datetime.now(timezone.utc).isoformat()),
                    )
                    conn.execute("UPDATE devices SET credential_id = ? WHERE id = ?", (new_id, d['id']))
                created += 1
                print(f"  [create] {host:<8} -> new cred {new_id} user={PRIV_USERNAME!r}")

        if args.apply:
            conn.commit()
            print(f"\nAPPLIED: {updated} updated, {created} created.")
        else:
            print(f"\nDRY RUN: would update {updated}, create {created}. "
                  f"Re-run with --apply to write.")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
