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
        '''SELECT p.id, p.prefix, p.name, p.tenant_id, p.vrf_id, p.site_id,
                  p.address_space_id,
                  p.network_type, p.gateway, p.gateway_device_id,
                  p.gateway_interface_id, d.hostname AS gateway_device_name
           FROM prefixes p
           LEFT JOIN devices d ON d.id = p.gateway_device_id'''
    ).fetchall():
        item = dict(row)
        try:
            item['network'] = ipaddress.ip_network(item['prefix'], strict=False)
        except (TypeError, ValueError):
            continue
        item['tenant_id'] = str(item.get('tenant_id') or 'tenant-default')
        item['vrf_id'] = str(item.get('vrf_id') or '')
        item['address_space_id'] = str(item.get('address_space_id') or '')
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


def address_key(address: str, tenant_id: str, scope_key: str) -> tuple[str, str, str]:
    try:
        normalized = str(ipaddress.ip_address(str(address).strip()))
    except ValueError:
        normalized = str(address or '').strip()
    return str(tenant_id or 'tenant-default'), str(scope_key or 'legacy-unresolved'), normalized


def manual_address_key(item: dict) -> tuple[str, str, str]:
    tenant = item.get('prefix_tenant_id') or item.get('tenant_id') or 'tenant-default'
    address_space_id = str(
        item.get('prefix_address_space_id') or item.get('address_space_id') or ''
    ).strip()
    if address_space_id:
        return address_key(item.get('address') or '', tenant, f'space:{address_space_id}')

    # Keep unresolved legacy rows in a separate namespace. An empty VRF is not
    # the same identity as any explicitly mapped Global address space.
    vrf = item.get('prefix_vrf_id') if item.get('subnet_prefix') else item.get('vrf_id')
    return address_key(
        item.get('address') or '', tenant,
        f'legacy-vrf:{str(vrf).strip()}' if str(vrf or '').strip() else 'legacy-unresolved',
    )


def endpoint_address_key(endpoint: dict, vrfs: dict | None = None) -> tuple[str, str, str] | None:
    del vrfs  # Legacy VRF names are display hints, not canonical address identity.
    if not endpoint.get('cmdb_device_id'):
        # The legacy endpoint cache has no tenant column. Without a CMDB
        # owner, assigning it to the default tenant would be invented scope.
        return None
    address_space_id = str(endpoint.get('address_space_id') or '').strip()
    if not address_space_id:
        # Until the collector projection carries a context mapping, the same
        # VRF label on two devices is insufficient evidence to join a Prefix.
        return None
    tenant = str(endpoint.get('device_tenant_id') or 'tenant-default')
    return address_key(endpoint.get('ip') or '', tenant, f'space:{address_space_id}')


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
    if key is None or len(key) < 2 or not str(key[1]).startswith('space:'):
        return None
    address_space_id = str(key[1]).removeprefix('space:')
    try:
        ip_obj = ipaddress.ip_address(address)
    except ValueError:
        return None
    matches = [
        item for item in prefixes
        if item['tenant_id'] == key[0] and item.get('address_space_id') == address_space_id
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
