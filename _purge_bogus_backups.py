"""Purge config_snapshots whose content is effectively a CLI error message
(e.g. "% Invalid input detected ...") and are < 500 bytes.

A valid Cisco running-config is typically > 2 KB even on a minimal device; any
snapshot with only tens of bytes is certainly the stored error output from the
pre-fix manual backup path. This script lists them, asks for confirmation, then
deletes both the DB row and the file on disk.
"""
from __future__ import annotations
import os
import sys
import gzip
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('.env')
import psycopg2
import psycopg2.extras

DSN = os.environ.get('DATABASE_URL', '')
BACKUP_ROOT = Path('backup')

SIZE_THRESHOLD = 500  # bytes – anything smaller than this on a network device
                     # is almost certainly garbage

conn = psycopg2.connect(DSN)
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

cur.execute(
    """
    SELECT id, hostname, vendor, timestamp, size, file_path, trigger
    FROM config_snapshots
    WHERE size < %s
    ORDER BY timestamp DESC
    """,
    (SIZE_THRESHOLD,),
)
rows = cur.fetchall()

if not rows:
    print('No suspiciously small snapshots found. Nothing to do.')
    sys.exit(0)

print(f'Found {len(rows)} snapshot(s) smaller than {SIZE_THRESHOLD} bytes:')
for r in rows:
    print(f"  {r['timestamp']} | {r['hostname']:<20} | {r['size']:>6} B | trigger={r['trigger']:<10} | {r['file_path']}")

confirm = input('\nDelete these snapshots (DB rows + files)? [y/N]: ').strip().lower()
if confirm != 'y':
    print('Cancelled.')
    sys.exit(0)

deleted_files = 0
deleted_rows = 0
for r in rows:
    # Delete file
    try:
        abs_path = BACKUP_ROOT / r['file_path']
        if abs_path.exists():
            abs_path.unlink()
            deleted_files += 1
    except Exception as e:
        print(f"  WARN could not delete {r['file_path']}: {e}")
    # Delete row
    cur.execute("DELETE FROM config_snapshots WHERE id = %s", (r['id'],))
    deleted_rows += 1

conn.commit()
cur.close()
conn.close()

print(f"Done: {deleted_rows} rows, {deleted_files} files removed.")
