from database import get_db_connection
from services.ipam_service import _current_cmdb_interface_ip_observations,_parse_interface_prefix_length
from services.ipam_inventory_scope import load_inventory_catalog,endpoint_site_id
import ipaddress,collections
c=get_db_connection()
try:
 prefixes,sites,_=load_inventory_catalog(c)
 counts=collections.Counter(); groups=collections.Counter(); details=[]
 for o in _current_cmdb_interface_ip_observations(c):
  owner={'cmdb_device_id':o.get('device_id'),'asset_site_id':o.get('asset_site_id'),'device_site_id':o.get('device_site_id'),'device_site':o.get('device_site')}
  site=endpoint_site_id(owner,sites); tenant=str(o.get('tenant_id') or 'tenant-default'); plen=_parse_interface_prefix_length(o.get('ip_prefix_length'))
  if plen is None: counts['missing_mask']+=1;continue
  try:
   address=ipaddress.ip_address(o['ip_address']); net=ipaddress.ip_network(f'{address}/{plen}',strict=False)
  except Exception:counts['invalid']+=1;continue
  matches=[p for p in prefixes if p['tenant_id']==tenant and p['site_id']==site and str(p['network'])==str(net)]
  kind='unique_scope_match' if len(matches)==1 else 'ambiguous_scope_match' if len(matches)>1 else 'no_existing_exact_prefix'
  counts[kind]+=1;groups[(str(net),kind)]+=1
 print({'obs':sum(counts.values())+counts['missing_mask']+counts['invalid'],'classification':dict(counts),'unique_prefix_groups':len({net for net,k in groups if k=='unique_scope_match'}),'prefixes_in_site':len([p for p in prefixes if p['site_id']==next(iter(sites.keys()))])})
except Exception as e:print('inspection_error',type(e).__name__,str(e))
finally:c.close()
