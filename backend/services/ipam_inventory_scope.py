"""Resolve IPAM observation identities without treating an IP as a global key."""

import ipaddress


def load_inventory_catalog(conn) -> tuple[list[dict], dict[str, dict], dict[tuple[str, str], set[str]]]:
    sites = {
        str(row['id']): {
            'id': row['id'], 'name': row['site_name'] or row['site_code'] or '未命名站点',
            'code': row['site_code'] or '', 'count': 0, 'ip_count': 0,
        }
        for row in conn.execute('SELECT id, site_name, site_code FROM sites ORDER BY site_name').fetchall()
    }
    vrfs: dict[tuple[str, str], set[str]] = {}
    for row in conn.execute('SELECT id, vrf_name, tenant_id FROM vrfs').fetchall():
        tenant = str(row['tenant_id'] or 'tenant-default')
        for alias in (row['id'], row['vrf_name']):
            vrfs.setdefault((tenant, str(alias or '').strip()), set()).add(str(row['id']))

    prefixes = []
    for row in conn.execute(
        'SELECT id, prefix, name, tenant_id, vrf_id, site_id, network_type FROM prefixes'
    ).fetchall():
        item = dict(row)
        try:
            item['network'] = ipaddress.ip_network(item['prefix'], strict=False)
        except (TypeError, ValueError):
            continue
        item['tenant_id'] = str(item.get('tenant_id') or 'tenant-default')
        item['vrf_id'] = str(item.get('vrf_id') or '')
        site = sites.get(str(item.get('site_id') or ''))
        item['invalid_site_assignment'] = bool(item.get('site_id') and not site)
        item['site_id'] = site['id'] if site else ''
        item['site_name'] = site['name'] if site else '未分配站点'
        item['site_code'] = site['code'] if site else ''
        prefixes.append(item)
        if site:
            site['count'] += 1
    prefixes.sort(key=lambda item: item['network'].prefixlen, reverse=True)
    return prefixes, sites, vrfs


def address_key(address: str, tenant_id: str, vrf_id: str) -> tuple[str, str, str]:
    try:
        normalized = str(ipaddress.ip_address(str(address).strip()))
    except ValueError:
        normalized = str(address or '').strip()
    return str(tenant_id or 'tenant-default'), str(vrf_id or ''), normalized


def manual_address_key(item: dict) -> tuple[str, str, str]:
    tenant = item.get('prefix_tenant_id') or item.get('tenant_id') or 'tenant-default'
    # The parent prefix also defines the global (empty) VRF. Legacy address
    # rows may not yet have copied its scope columns.
    vrf = item.get('prefix_vrf_id') if item.get('subnet_prefix') else item.get('vrf_id')
    return address_key(item.get('address') or '', tenant, vrf or '')


def endpoint_address_key(endpoint: dict, vrfs: dict) -> tuple[str, str, str] | None:
    if not endpoint.get('cmdb_device_id'):
        # The legacy endpoint cache has no tenant column. Without a CMDB
        # owner, assigning it to the default tenant would be invented scope.
        return None
    tenant = str(endpoint.get('device_tenant_id') or 'tenant-default')
    raw_vrf = str(endpoint.get('vrf') or '').strip()
    matches = vrfs.get((tenant, raw_vrf), set())
    if len(matches) > 1:
        return None
    if matches:
        vrf = next(iter(matches))
    elif raw_vrf.lower() in ('', 'default', 'global', 'public'):
        vrf = ''
    else:
        # An unknown name must never become the global VRF.
        return None
    return address_key(endpoint.get('ip') or '', tenant, vrf)


def endpoint_site_id(endpoint: dict, sites: dict) -> str:
    # Linked assets are the canonical placement; unlinked devices retain
    # their CMDB assignment. A live unassigned device must not inherit its
    # previous site's cached observation.
    fields = ('asset_site_id', 'device_site_id', 'device_site') if endpoint.get('cmdb_device_id') else ('site',)
    for field in fields:
        candidate = str(endpoint.get(field) or '')
        if candidate in sites:
            return candidate
        if field == 'device_site' and candidate:
            matches = [site['id'] for site in sites.values() if candidate in (site['name'], site['code'])]
            if len(matches) == 1:
                return matches[0]
    return ''


def match_inventory_prefix(address: str, key: tuple | None, site_id: str, prefixes: list[dict]) -> dict | None:
    if key is None:
        return None
    try:
        ip_obj = ipaddress.ip_address(address)
    except ValueError:
        return None
    matches = [
        item for item in prefixes
        if item['tenant_id'] == key[0] and item['vrf_id'] == key[1]
        and not item.get('invalid_site_assignment')
        and ip_obj.version == item['network'].version and ip_obj in item['network']
        and (not site_id or not item['site_id'] or item['site_id'] == site_id)
    ]
    if not matches:
        return None
    longest = matches[0]['network'].prefixlen
    best = [item for item in matches if item['network'].prefixlen == longest]
    if site_id:
        at_site = [item for item in best if item['site_id'] == site_id]
        if at_site:
            best = at_site
    # Equal networks in different sites (or duplicate prefixes) are ambiguous.
    return best[0] if len(best) == 1 else None
