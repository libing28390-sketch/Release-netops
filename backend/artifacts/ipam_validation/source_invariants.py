import hashlib,json,sys
from pathlib import Path
from database import get_db_connection
TABLES=("arp_table","mac_table","network_endpoints","interfaces","ip_inventory","ip_addresses")
c=get_db_connection()
result={}
try:
 for table in TABLES:
  rows=[dict(r) for r in c.execute("SELECT * FROM "+table).fetchall()]
  ordered=sorted(json.dumps(r,sort_keys=True,ensure_ascii=True,default=str) for r in rows)
  result[table]={"rows":len(rows),"sha256":hashlib.sha256("\n".join(ordered).encode()).hexdigest()}
finally:c.close()
p=Path(sys.argv[1]);p.write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps({k:v["rows"] for k,v in result.items()}))
