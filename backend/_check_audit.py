from database import get_db_connection
conn = get_db_connection()
rows = conn.execute(
    "SELECT created_at, event_type, summary FROM audit_events "
    "WHERE event_type LIKE ? OR event_type LIKE ? "
    "ORDER BY created_at DESC LIMIT 10",
    ('%ROTAT%', '%PASSWORD%')
).fetchall()
conn.close()
for r in rows:
    print(r['created_at'], '|', r['event_type'], '|', str(r['summary'])[:90])
