from database import get_db_connection
try:
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM instant_executions ORDER BY created_at DESC LIMIT 5").fetchall()
    for r in rows:
        d = dict(r)
        # Truncate long output for readability
        if d['output']:
            d['output'] = d['output'][:200] + "..." if len(d['output']) > 200 else d['output']
        print(d)
finally:
    conn.close()
