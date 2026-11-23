from database import get_db_connection
from services.ipam_service import list_ip_inventory, preview_interface_prefixes, _current_cmdb_interface_ip_observations
c=get_db_connection()
try:
 tables=('ip_addresses','prefixes','interfaces','ip_inventory','cmdb_device_interface_observations','cmdb_collection_snapshots')
 counts={}
 for table in tables:
  try: counts[table]=c.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n']
  except Exception:
   try:c.rollback()
   except Exception:pass
   counts[table]='missing'
 site=c.execute("SELECT id FROM sites WHERE site_name='WH-DC-01' OR site_code='WH-DC-01' LIMIT 1").fetchone()
 site_id=site['id'] if site else ''
 pref_count=c.execute("SELECT COUNT(*) AS n FROM prefixes WHERE site_id=?",(site_id,)).fetchone()['n'] if site_id else None
 ip_count=c.execute("SELECT COUNT(*) AS n FROM ip_addresses ip LEFT JOIN prefixes p ON p.id=ip.subnet_id WHERE COALESCE(NULLIF(p.site_id,''),NULLIF(ip.site_id,''),'')=?",(site_id,)).fetchone()['n'] if site_id else None
 observations=_current_cmdb_interface_ip_observations(c)
 cmdb_site=sum(1 for row in observations if row.get('device_site_id')==site_id or row.get('asset_site_id')==site_id) if site_id else None
 snapshots=[]
 try:snapshots=[dict(r) for r in c.execute("SELECT device_id,domain,attempt_generation,successful_generation,attempt_status,record_count,observed_at,failure_code FROM cmdb_collection_snapshots WHERE domain='interface_inventory' ORDER BY device_id").fetchall()]
 except Exception:
  try:c.rollback()
  except Exception:pass
 print({'counts':counts,'site_resolved':bool(site_id),'site_prefixes':pref_count,'site_ipam_ledger':ip_count,'last_good_interface_observations':len(observations),'site_last_good_interface_observations':cmdb_site,'interface_snapshots':snapshots})
 for registered in (False,True):
  inventory=list_ip_inventory(site_id=site_id or 'all',registered_only=registered,page_size=10)
  print('inventory',registered,{'total':inventory.get('total'),'summary':inventory.get('summary')})
 preview=preview_interface_prefixes(page_size=100)
 print('interface_candidates', {key:preview.get(key) for key in ('candidate_count','interface_count','skipped_count','existing_count','to_create_count')})
except Exception as e:
 print('inspection_error',type(e).__name__,str(e))
finally:c.close()
