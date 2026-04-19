#!/usr/bin/env python
from backend.database import get_db_connection

conn = get_db_connection()
count = conn.execute('SELECT COUNT(*) FROM physical_assets').fetchone()[0]
print(f'Asset count: {count}')
print('\nFirst 5 assets:')
rows = conn.execute('SELECT id, asset_tag, hostname, vendor, model, serial_number, status FROM physical_assets LIMIT 5').fetchall()
for r in rows:
    print(dict(r))
conn.close()
