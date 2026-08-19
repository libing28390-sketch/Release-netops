import sqlite3, os

for db_path in ['netops.db', 'data/netops.db']:
    if os.path.exists(db_path):
        print(f"=== DB: {db_path} ===")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print("Tables:", tables)
        for t in ['physical_assets', 'racks', 'rack_units', 'topology_links', 'interfaces', 'devices']:
            if t in tables:
                cur.execute(f"SELECT * FROM {t} LIMIT 5")
                print(f"Sample from {t}:", cur.fetchall())
