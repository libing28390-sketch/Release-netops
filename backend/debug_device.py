from database import get_db_connection
try:
    conn = get_db_connection()
    row = conn.execute("SELECT id, hostname, ip_address, platform, username FROM devices WHERE ip_address = '192.168.204.128'").fetchone()
    if row:
        print(dict(row))
    else:
        # Check assets table too
        row = conn.execute("SELECT id, hostname, management_ip, platform, asset_type FROM physical_assets WHERE management_ip = '192.168.204.128'").fetchone()
        if row:
            print("From physical_assets:", dict(row))
        else:
            print("Device/Asset not found")
finally:
    conn.close()
