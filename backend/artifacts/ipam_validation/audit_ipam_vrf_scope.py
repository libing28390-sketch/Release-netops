from database import get_db_connection
from services.ipam_service import _current_cmdb_interface_ip_observations,_parse_interface_prefix_length
from services.ipam_inventory_scope import load_inventory_catalog,endpoint_site_id
import ipaddress,collections
c=get_db_connection()
try:
 prefixes,sites,_=load_inventory_catalog(c); counts=collections.Counter()
 for o in _current_cmdb_interface_ip_observations(c):
  owner={'cmdb_device_id':o.get('device_id'),'asset_site_id':o.get('asset_site_id'),'device_site_id':o.get('device_site_id'),'device_site':o.get('device_site')}; site=endpoint_site_id(owner,sites); tenant=str(o.get('tenant_id') or 'tenant-default')
  try: address=ipaddress.ip_address(o['ip_address'])
  except Exception: counts['invalid']+=1;continue
  candidates=[p for p in prefixes if p['tenant_id']==tenant and p['site_id']==site and p['network'].version==address.version and address in p['network']]
  scopes={(p['vrf_id'],p['network'].prefixlen) for p in candidates}
  if not site: counts['site_missing']+=1
  elif len(candidates)==0:counts['no_covering_prefix']+=1
  elif len({p['vrf_id'] for p in candidates})==1:counts['unique_vrf_covering_prefix']+=1
  else:counts['ambiguous_vrf']+=1
 print({'interface_ips':len(_current_cmdb_interface_ip_observations(c)),'scope_distribution':dict(counts)})
finally:c.close()
