from database import get_db_connection
conn=get_db_connection()
try:
 rows=conn.execute("SELECT datname,state,wait_event_type,wait_event,backend_type,now()-query_start AS age FROM pg_stat_activity WHERE usename=current_user ORDER BY query_start NULLS LAST").fetchall()
 print([dict(row) for row in rows])
finally:conn.close()
