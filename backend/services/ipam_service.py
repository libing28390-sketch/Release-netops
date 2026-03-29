"""
IPAM Service — Business logic for IP/VLAN resource management.
Provides subnet and IP address CRUD with validation, overlap detection, and conflict scanning.
"""

import uuid
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Optional

from database import get_db_connection

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ip_in_subnet(addr: str, network: str, prefix_len: int) -> bool:
    """Check whether *addr* falls within the given CIDR block."""
    try:
        net = ipaddress.ip_network(f"{network}/{prefix_len}", strict=False)
        return ipaddress.ip_address(addr) in net
    except ValueError:
        return False


# ── Subnet ────────────────────────────────────

def list_subnets(*, site: str = 'all', status: str = 'all', q: str = '') -> list[dict]:
    conn = get_db_connection()
    try:
        sql = 'SELECT * FROM ip_subnets WHERE 1=1'
        params: list = []
        if site and site != 'all':
            sql += ' AND site = ?'
            params.append(site)
        if status and status != 'all':
            sql += ' AND status = ?'
            params.append(status)
        if q and q.strip():
            fuzzy = f'%{q.strip().lower()}%'
            sql += ' AND (LOWER(name) LIKE ? OR LOWER(network) LIKE ? OR LOWER(vlan_name) LIKE ? OR LOWER(description) LIKE ?)'
            params.extend([fuzzy, fuzzy, fuzzy, fuzzy])
        sql += ' ORDER BY network'
        rows = conn.execute(sql, tuple(params)).fetchall()

        result = []
        for r in rows:
            item = dict(r)
            count = conn.execute(
                'SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = ?',
                (r['id'],),
            ).fetchone()
            item['used_ips'] = count['cnt'] if count else 0
            item['utilization'] = (
                round(item['used_ips'] / item['total_ips'] * 100, 1)
                if item['total_ips'] > 0
                else 0
            )
            result.append(item)
        return result
    finally:
        conn.close()


def create_subnet(
    *,
    name: str,
    network: str,
    prefix_len: int,
    vlan_id: Optional[int],
    vlan_name: str,
    gateway: str,
    description: str,
    site: str,
) -> dict:
    """Create a subnet after validating CIDR and checking for overlaps."""
    # Validate CIDR
    try:
        net = ipaddress.ip_network(f"{network}/{prefix_len}", strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid CIDR: {exc}") from exc

    conn = get_db_connection()
    try:
        # Exact-duplicate check
        existing = conn.execute(
            'SELECT id FROM ip_subnets WHERE network = ? AND prefix_len = ?',
            (network, prefix_len),
        ).fetchone()
        if existing:
            raise ValueError('Subnet already exists')

        # Overlap check against all existing subnets
        all_subnets = conn.execute('SELECT id, network, prefix_len, name FROM ip_subnets').fetchall()
        for row in all_subnets:
            try:
                existing_net = ipaddress.ip_network(f"{row['network']}/{row['prefix_len']}", strict=False)
                if net.overlaps(existing_net):
                    raise ValueError(
                        f"New subnet {net} overlaps with existing subnet "
                        f"'{row['name']}' ({existing_net})"
                    )
            except ValueError as e:
                if 'overlaps' in str(e):
                    raise
                # Skip unparseable existing entries

        subnet_id = f"subnet-{uuid.uuid4().hex[:12]}"
        # Calculate usable addresses for IPv4 vs IPv6
        addr = ipaddress.ip_address(network)
        if addr.version == 6:
            bits = 128 - prefix_len
            total_ips = max(0, (2 ** bits) - 2) if prefix_len < 127 else (1 if prefix_len == 128 else 2)
            # Cap display at a reasonable number for very large v6 subnets
            if total_ips > 2**63:
                total_ips = 2**63
        else:
            total_ips = max(0, (2 ** (32 - prefix_len)) - 2) if prefix_len < 31 else (1 if prefix_len == 32 else 2)
        now = _utc_now()
        conn.execute(
            '''INSERT INTO ip_subnets
               (id, name, network, prefix_len, vlan_id, vlan_name,
                gateway, description, site, status, total_ips, used_ips, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?)''',
            (subnet_id, name, network, prefix_len,
             vlan_id, vlan_name, gateway, description, site, total_ips, now, now),
        )
        conn.commit()
        logger.info("Created subnet %s (%s/%s)", subnet_id, network, prefix_len)
        return {'id': subnet_id, 'total_ips': total_ips}
    finally:
        conn.close()


def update_subnet(subnet_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM ip_subnets WHERE id = ?', (subnet_id,)).fetchone()
        if not row:
            return False

        updates = []
        params = []
        for field in ('name', 'vlan_id', 'vlan_name', 'gateway', 'description', 'site', 'status'):
            val = fields.get(field)
            if val is not None:
                updates.append(f'{field} = ?')
                params.append(val)
        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(subnet_id)
            conn.execute(
                f"UPDATE ip_subnets SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_subnet(subnet_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM ip_subnets WHERE id = ?', (subnet_id,)).fetchone()
        if not row:
            return False
        conn.execute('DELETE FROM ip_addresses WHERE subnet_id = ?', (subnet_id,))
        conn.execute('DELETE FROM ip_subnets WHERE id = ?', (subnet_id,))
        conn.commit()
        logger.info("Deleted subnet %s", subnet_id)
        return True
    finally:
        conn.close()


# ── IP Addresses ──────────────────────────────

def list_addresses(subnet_id: str) -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM ip_addresses WHERE subnet_id = ? ORDER BY address',
            (subnet_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_address(
    subnet_id: str,
    *,
    address: str,
    hostname: str = '',
    device_id: str = '',
    interface_name: str = '',
    mac_address: str = '',
    device_type: str = '',
    description: str = '',
    status: str = 'active',
) -> dict:
    """Add an IP address after validating it belongs to the subnet."""
    conn = get_db_connection()
    try:
        subnet = conn.execute('SELECT * FROM ip_subnets WHERE id = ?', (subnet_id,)).fetchone()
        if not subnet:
            raise ValueError('Subnet not found')

        # Validate address belongs to subnet CIDR
        if not _ip_in_subnet(address, subnet['network'], subnet['prefix_len']):
            net = ipaddress.ip_network(
                f"{subnet['network']}/{subnet['prefix_len']}", strict=False
            )
            raise ValueError(f"Address {address} is not within subnet {net}")

        # Duplicate check
        existing = conn.execute(
            'SELECT id FROM ip_addresses WHERE subnet_id = ? AND address = ?',
            (subnet_id, address),
        ).fetchone()
        if existing:
            raise ValueError('IP address already registered in this subnet')

        addr_id = f"ip-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute(
            '''INSERT INTO ip_addresses
               (id, subnet_id, address, hostname, device_id, interface_name,
                mac_address, device_type, status, description, last_seen, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (addr_id, subnet_id, address, hostname, device_id,
             interface_name, mac_address, device_type, status, description, now, now, now),
        )
        # Dynamically recalculate used_ips
        cnt = conn.execute(
            'SELECT COUNT(*) as c FROM ip_addresses WHERE subnet_id = ?', (subnet_id,)
        ).fetchone()['c']
        conn.execute(
            'UPDATE ip_subnets SET used_ips = ?, updated_at = ? WHERE id = ?',
            (cnt, now, subnet_id),
        )
        conn.commit()
        return {'id': addr_id}
    finally:
        conn.close()


def update_address(address_id: str, **fields) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM ip_addresses WHERE id = ?', (address_id,)).fetchone()
        if not row:
            return False

        updates = []
        params = []
        for field in ('hostname', 'device_id', 'interface_name', 'mac_address',
                      'device_type', 'description', 'status'):
            val = fields.get(field)
            if val is not None:
                updates.append(f'{field} = ?')
                params.append(val)
        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(address_id)
            conn.execute(
                f"UPDATE ip_addresses SET {', '.join(updates)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()
        return True
    finally:
        conn.close()


def delete_address(address_id: str) -> bool:
    conn = get_db_connection()
    try:
        addr = conn.execute('SELECT subnet_id FROM ip_addresses WHERE id = ?', (address_id,)).fetchone()
        if not addr:
            return False
        subnet_id = addr['subnet_id']
        conn.execute('DELETE FROM ip_addresses WHERE id = ?', (address_id,))
        now = _utc_now()
        cnt = conn.execute(
            'SELECT COUNT(*) as c FROM ip_addresses WHERE subnet_id = ?', (subnet_id,)
        ).fetchone()['c']
        conn.execute(
            'UPDATE ip_subnets SET used_ips = ?, updated_at = ? WHERE id = ?',
            (cnt, now, subnet_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ── Conflict Detection ────────────────────────

def detect_conflicts() -> dict:
    """Scan for duplicate IPs across subnets and duplicate MACs."""
    conn = get_db_connection()
    try:
        dup_ips = conn.execute('''
            SELECT address, GROUP_CONCAT(subnet_id) as subnets, COUNT(*) as cnt
            FROM ip_addresses GROUP BY address HAVING cnt > 1
        ''').fetchall()

        dup_macs = conn.execute('''
            SELECT mac_address, GROUP_CONCAT(address) as addresses, COUNT(*) as cnt
            FROM ip_addresses
            WHERE mac_address != '' AND mac_address IS NOT NULL
            GROUP BY mac_address HAVING cnt > 1
        ''').fetchall()

        return {
            'ip_conflicts': [dict(r) for r in dup_ips],
            'mac_conflicts': [dict(r) for r in dup_macs],
            'total_conflicts': len(dup_ips) + len(dup_macs),
        }
    finally:
        conn.close()


def ipam_summary() -> dict:
    conn = get_db_connection()
    try:
        subnets = conn.execute('SELECT COUNT(*) as cnt FROM ip_subnets').fetchone()
        addresses = conn.execute('SELECT COUNT(*) as cnt FROM ip_addresses').fetchone()
        total_capacity = conn.execute('SELECT SUM(total_ips) as total FROM ip_subnets').fetchone()
        # Dynamic used count
        total_used = conn.execute('SELECT COUNT(*) as total FROM ip_addresses').fetchone()

        high_util_rows = conn.execute(
            'SELECT s.*, COUNT(a.id) as real_used FROM ip_subnets s '
            'LEFT JOIN ip_addresses a ON a.subnet_id = s.id '
            'GROUP BY s.id HAVING s.total_ips > 0 AND CAST(COUNT(a.id) AS REAL) / s.total_ips >= 0.8 '
            'ORDER BY CAST(COUNT(a.id) AS REAL) / s.total_ips DESC'
        ).fetchall()

        return {
            'total_subnets': subnets['cnt'] if subnets else 0,
            'total_addresses': addresses['cnt'] if addresses else 0,
            'total_capacity': total_capacity['total'] if total_capacity and total_capacity['total'] else 0,
            'total_used': total_used['total'] if total_used else 0,
            'high_utilization_subnets': [dict(r) for r in high_util_rows],
        }
    finally:
        conn.close()
