import logging
import uuid
from datetime import datetime, timezone
from database import get_db_connection
from services.oui_lookup import lookup_vendor

logger = logging.getLogger(__name__)

def _beijing_now_iso() -> str:
    # Same timezone representation as core code
    # We can use datetime.now() formatted, or Beijing ISO.
    # Standard format: datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def _normalize_mac(mac: str) -> str:
    if not mac:
        return ''
    return mac.replace(':', '').replace('-', '').replace('.', '').lower()

def locate_mac_address(mac: str, mac_entries: list[dict], topology_links: list[dict]) -> dict | None:
    """
    Recursive leaf-node localization algorithm for a MAC address.
    Returns: {switch_id, port, vlan, confidence} or None
    """
    from services.topology_service import normalize_interface_name

    mac_norm = _normalize_mac(mac)
    if not mac_norm:
        return None
        
    # Filter mac entries for this MAC
    locs = []
    for entry in mac_entries:
        ent_mac = _normalize_mac(entry.get('mac_address', ''))
        if ent_mac == mac_norm:
            locs.append(entry)
            
    if not locs:
        return None
        
    # Map from switch_id to port info
    sw_to_loc = {l['device_id']: l for l in locs}
    
    # Map for topology links: (sw, port) -> (remote_sw, remote_port)
    link_map = {}
    for link in topology_links:
        s_dev = link.get('source_device_id')
        s_port = normalize_interface_name(link.get('source_port_normalized') or link.get('source_port') or '').lower()
        t_dev = link.get('target_device_id')
        t_port = normalize_interface_name(link.get('target_port_normalized') or link.get('target_port') or '').lower()
        
        if s_dev and s_port:
            link_map[(s_dev, s_port)] = (t_dev, t_port)
        if t_dev and t_port:
            link_map[(t_dev, t_port)] = (s_dev, s_port)
            
    # Uplink ports set
    uplink_ports = set()
    for link in topology_links:
        s_dev = link.get('source_device_id')
        s_port = normalize_interface_name(link.get('source_port_normalized') or link.get('source_port') or '').lower()
        t_dev = link.get('target_device_id')
        t_port = normalize_interface_name(link.get('target_port_normalized') or link.get('target_port') or '').lower()
        if s_dev and s_port:
            uplink_ports.add((s_dev, s_port))
        if t_dev and t_port:
            uplink_ports.add((t_dev, t_port))
            
    # Check if a port name is a lag/trunk by name
    def is_trunk_port_name(port_name: str) -> bool:
        pn = str(port_name or '').lower()
        return any(kw in pn for kw in ('po', 'port-channel', 'lag', 'eth-trunk', 'bridge-aggregation', 'bagg'))
        
    # Classify locations
    access_locs = []
    uplink_locs = []
    for l in locs:
        sw_id = l['device_id']
        port = l['interface_name']
        port_norm = normalize_interface_name(port).lower()
        
        is_uplink = (sw_id, port_norm) in uplink_ports or is_trunk_port_name(port)
        if is_uplink:
            uplink_locs.append(l)
        else:
            access_locs.append(l)
            
    if access_locs:
        # Access port found! Pick the one with the latest update or just the first
        access_locs.sort(key=lambda x: x.get('last_updated', ''), reverse=True)
        best = access_locs[0]
        return {
            'switch_id': best['device_id'],
            'port': best['interface_name'],
            'vlan': str(best.get('vlan_id') or ''),
            'confidence': '98% (Access Port)',
        }
        
    # If no access port is found, trace recursively along the trunk ports
    sw_ids = list(sw_to_loc.keys())
    if not sw_ids:
        return None
        
    curr_sw = sw_ids[0]
    visited = {curr_sw}
    
    while True:
        curr_loc = sw_to_loc[curr_sw]
        curr_port = normalize_interface_name(curr_loc['interface_name']).lower()
        
        # Check if this port is connected to another switch
        connection = link_map.get((curr_sw, curr_port))
        if connection:
            next_sw, next_port = connection
            # If the next switch is also in our learned switches list, move to it!
            if next_sw in sw_to_loc and next_sw not in visited:
                visited.add(next_sw)
                curr_sw = next_sw
                continue
        break
        
    final_loc = sw_to_loc[curr_sw]
    return {
        'switch_id': final_loc['device_id'],
        'port': final_loc['interface_name'],
        'vlan': str(final_loc.get('vlan_id') or ''),
        'confidence': '70% (Trunk Port)',
    }

def track_and_locate_endpoints():
    """
    Main Endpoint Tracker logic:
    1. Read all ARP table entries from 'arp_table'.
    2. Read all MAC table entries from 'mac_table'.
    3. Read all topology links from 'topology_links'.
    4. Compute leaf locations for each endpoint.
    5. Write results to 'network_endpoints'.
    6. Detect location drifts and write to 'endpoint_history'.
    """
    logger.info("[Endpoint Tracker] Starting track_and_locate_endpoints execution...")
    conn = get_db_connection()
    try:
        # Load all ARP table entries
        arp_rows = conn.execute("SELECT device_id, ip_address, mac_address, interface_name, vlan_id, last_updated FROM arp_table").fetchall()
        arp_entries = [dict(row) for row in arp_rows]
        
        # Load all MAC table entries
        mac_rows = conn.execute("SELECT device_id, mac_address, interface_name, vlan_id, entry_type, last_updated FROM mac_table").fetchall()
        mac_entries = [dict(row) for row in mac_rows]
        
        # Load all topology links
        link_rows = conn.execute("SELECT source_device_id, source_port, source_port_normalized, target_device_id, target_port, target_port_normalized FROM topology_links").fetchall()
        topology_links = [dict(row) for row in link_rows]
        
        # Load all devices for hostname and site name mapping
        dev_rows = conn.execute("SELECT id, hostname, site FROM devices").fetchall()
        device_map = {row['id']: dict(row) for row in dev_rows}
        
        if not arp_entries:
            logger.info("[Endpoint Tracker] No ARP entries found in arp_table. Skipping execution.")
            return
            
        endpoints_to_save = []
        for arp in arp_entries:
            ip = arp['ip_address']
            mac_raw = arp['mac_address']
            mac_norm = _normalize_mac(mac_raw)
            
            if not mac_norm or ip in ('0.0.0.0', '255.255.255.255'):
                continue
                
            # Run the localization algorithm
            location = locate_mac_address(mac_norm, mac_entries, topology_links)
            
            if location:
                switch_id = location['switch_id']
                port = location['port']
                vlan = location['vlan']
                confidence = location['confidence']
            else:
                # Fallback to the reporting L3 device
                switch_id = arp['device_id']
                port = arp['interface_name'] or 'unknown'
                vlan = str(arp.get('vlan_id') or '')
                confidence = '80% (based on ARP learning source)'
                
            # Get device details for site mapping
            dev_info = device_map.get(switch_id, {})
            site_name = dev_info.get('site') or dev_info.get('hostname') or 'Default Site'
            hostname = dev_info.get('hostname') or ''
            
            endpoints_to_save.append({
                'ip': ip,
                'mac': mac_norm,
                'hostname': hostname,
                'switch_id': switch_id,
                'switch_port': port,
                'vlan': vlan,
                'site': site_name,
                'confidence': confidence,
            })
            
        if endpoints_to_save:
            last_seen = _beijing_now_iso()
            
            # Deactivate all current endpoints first
            conn.execute("UPDATE network_endpoints SET is_active = 0")
            
            for ep in endpoints_to_save:
                # Check for existing record to log drift
                existing = conn.execute(
                    "SELECT first_seen, switch_id, switch_port, vlan FROM network_endpoints WHERE ip = ?", 
                    (ep['ip'],)
                ).fetchone()
                
                if existing:
                    first_seen = existing['first_seen']
                    old_sw = existing['switch_id']
                    old_port = existing['switch_port']
                    old_vl = existing['vlan']
                    
                    if old_sw != ep['switch_id'] or old_port != ep['switch_port'] or old_vl != ep['vlan']:
                        # Location drift detected!
                        drift_id = str(uuid.uuid4())
                        conn.execute(
                            '''INSERT INTO endpoint_history (
                                id, ip, mac, old_switch_id, old_switch_port, old_vlan, 
                                new_switch_id, new_switch_port, new_vlan, drift_type, detected_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'drift', ?)''',
                            (drift_id, ep['ip'], ep['mac'], old_sw, old_port, old_vl, 
                             ep['switch_id'], ep['switch_port'], ep['vlan'], last_seen)
                        )
                else:
                    first_seen = last_seen
                    
                uid = f"{ep['ip']}_{ep['mac']}"
                vendor = lookup_vendor(ep['mac'])
                
                conn.execute(
                    '''INSERT INTO network_endpoints (
                        id, ip, mac, hostname, vendor, os_type, asset_type, 
                        switch_id, switch_port, vlan, vrf, site, source_type, 
                        confidence, first_seen, last_seen, is_active
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                       ON CONFLICT(ip) DO UPDATE SET
                           mac = excluded.mac,
                           hostname = excluded.hostname,
                           vendor = excluded.vendor,
                           switch_id = excluded.switch_id,
                           switch_port = excluded.switch_port,
                           vlan = excluded.vlan,
                           site = excluded.site,
                           confidence = excluded.confidence,
                           last_seen = excluded.last_seen,
                           is_active = 1''',
                    (uid, ep['ip'], ep['mac'], ep['hostname'], vendor, 'Linux', 'host',
                     ep['switch_id'], ep['switch_port'], ep['vlan'], '', ep['site'], 'arp',
                     ep['confidence'], first_seen, last_seen)
                )
                
            conn.commit()
            logger.info(f"[Endpoint Tracker] Successfully localized {len(endpoints_to_save)} endpoints.")
    except Exception as e:
        logger.exception(f"[Endpoint Tracker] Error in track_and_locate_endpoints: {e}")
    finally:
        conn.close()
