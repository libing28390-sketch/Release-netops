import json
from urllib.parse import urlparse
from database import get_db_connection
from database import core
from database.migrations import build_migration_plan,run_migrations
from database.migrations.m0301_ipam_discovery_evidence import upgrade
from services.ipam_discovery_service import run_ipam_discovery_projection,list_discovered_endpoints
from services.ipam_service import get_ipam_reconciliation,list_ip_inventory
url=urlparse(core._DATABASE_URL)
assert url.hostname in {"127.0.0.1","localhost","::1"}, "Refusing nonlocal development database"
c=get_db_connection()
try:
 plan=build_migration_plan(c,True)
 assert set(plan.pending_versions)<= {301}, "Unexpected migration scope"
 assert plan.safe, "Unsafe migration history"
 if 301 in plan.pending_versions:
  assert run_migrations(c,True)==1
 else:
  upgrade(c.cursor(),True);c.commit()
finally:c.close()
first=run_ipam_discovery_projection()
second=run_ipam_discovery_projection()
assert second["observations_created"]==0 and second["snapshots_created"]==0
listing=list_discovered_endpoints(kind="ip",page_size=100)
ledger=list_ip_inventory(registered_only=True)
recon=get_ipam_reconciliation()
print(json.dumps({"projection":first,"repeat_projection":second,"discovery_records":listing["total"],"discovery_summary":listing["summary"],"registered_records":ledger["total"],"reconciliation_summary":recon["summary"]},ensure_ascii=True,indent=2))
