from database import get_db_connection
import json
try:
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM execution_device_results ORDER BY started_at DESC LIMIT 5").fetchall()
    for r in rows:
        d = dict(r)
        print(f"Time: {d['started_at']}, Device: {d['device_id']}, Status: {d['status']}, Error: {d['error_message']}")
        # Phases JSON usually contains the output
        if d['phases_json']:
            phases = json.loads(d['phases_json'])
            execute_phase = phases.get('execute', {})
            output = execute_phase.get('output', '')
            print(f"Output (truncated): {output[:200]}...")
        print("-" * 50)
finally:
    conn.close()
