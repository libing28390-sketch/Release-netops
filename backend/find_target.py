from database import get_db_connection
target_id = '875ca5ed-0751-4a5b-959c-29bb907eb9a3'
try:
    conn = get_db_connection()
    # Check various tables
    for table in ['scripts', 'templates', 'playbook_executions', 'execution_device_results', 'inspection_runs', 'inspection_results']:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (target_id,)).fetchone()
        if row:
            print(f"Found in {table}: {dict(row)}")
            break
    else:
        # Check by name_zh or name
        row = conn.execute("SELECT * FROM scripts WHERE name_zh LIKE '%%Ubuntu%%' OR name LIKE '%%Ubuntu%%'").fetchone()
        if row:
            print(f"Found script by name: {dict(row)}")
finally:
    conn.close()
