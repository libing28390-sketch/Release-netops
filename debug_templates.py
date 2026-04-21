from backend.database import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

print("=== TEMPLATES ===")
rows = cursor.execute("SELECT id, name, content, vendor, category FROM templates").fetchall()
for r in rows:
    content = r["content"] or ""
    # find {{var}} patterns
    import re
    variables = re.findall(r'\{\{\s*([\w.-]+)\s*\}\}', content)
    uniq = list(dict.fromkeys(variables))
    print(f"  ID: {r['id']}")
    print(f"  Name: {r['name']}")
    print(f"  Vendor: {r['vendor']}")
    print(f"  Category: {r['category']}")
    print(f"  Variables: {uniq}")
    print(f"  Content preview: {content[:120]}...")
    print()

print("=== SCENARIOS (from API) ===")
import json
rows2 = cursor.execute("SELECT id, data_json FROM custom_scenarios").fetchall()
for r in rows2:
    data = json.loads(r["data_json"])
    print(f"  ID: {r['id']}, Name: {data.get('name')}")

conn.close()
