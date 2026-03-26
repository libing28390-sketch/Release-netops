"""
capacity.py — Capacity Planning & IP/VLAN Resource Management API
Provides link utilization trending, capacity forecasting, and IP/VLAN management.
"""

import uuid
import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ──────────────────────────────────────────────
# Capacity Planning endpoints
# ──────────────────────────────────────────────

@router.get('/capacity/overview')
def capacity_overview():
    """Overall capacity dashboard: top utilized interfaces, devices with high CPU/memory."""
    conn = get_db_connection()
    try:
        # Get devices with CPU/memory info
        devices = conn.execute('''
            SELECT id, hostname, ip_address, platform, status,
                   cpu_usage, memory_usage, interface_count, interface_up_count,
                   uptime, model
            FROM devices
            WHERE status = 'online'
            ORDER BY cpu_usage DESC
        ''').fetchall()

        high_cpu = [dict(d) for d in devices if (d['cpu_usage'] or 0) >= 80]
        high_mem = [dict(d) for d in devices if (d['memory_usage'] or 0) >= 80]

        # Get top utilized interfaces from recent telemetry
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        hot_interfaces = conn.execute('''
            SELECT device_id, interface_name,
                   AVG(in_util) as avg_in_util, AVG(out_util) as avg_out_util,
                   MAX(in_util) as peak_in_util, MAX(out_util) as peak_out_util,
                   MAX(speed_mbps) as bandwidth_mbps
            FROM interface_telemetry_raw
            WHERE ts >= ?
            GROUP BY device_id, interface_name
            HAVING avg_in_util > 50 OR avg_out_util > 50
            ORDER BY MAX(COALESCE(in_util, 0), COALESCE(out_util, 0)) DESC
            LIMIT 20
        ''', (cutoff,)).fetchall()

        # Enrich with hostname
        dev_map = {d['id']: d['hostname'] for d in devices}
        hot_intf_list = []
        for intf in hot_interfaces:
            item = dict(intf)
            item['hostname'] = dev_map.get(intf['device_id'], '')
            hot_intf_list.append(item)

        # Summary stats
        total_devices = len(devices)
        avg_cpu = round(sum(d['cpu_usage'] or 0 for d in devices) / max(total_devices, 1), 1)
        avg_mem = round(sum(d['memory_usage'] or 0 for d in devices) / max(total_devices, 1), 1)

        return {
            'total_devices': total_devices,
            'avg_cpu': avg_cpu,
            'avg_memory': avg_mem,
            'high_cpu_count': len(high_cpu),
            'high_memory_count': len(high_mem),
            'high_cpu_devices': high_cpu[:10],
            'high_memory_devices': high_mem[:10],
            'hot_interfaces': hot_intf_list,
        }
    finally:
        conn.close()


@router.get('/capacity/device/{device_id}/trend')
def device_capacity_trend(device_id: str, days: int = Query(default=30, ge=1, le=365)):
    """Get daily CPU/memory/interface utilization trend for a device."""
    conn = get_db_connection()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # From device_health_samples
        health_rows = conn.execute('''
            SELECT DATE(ts) as day, AVG(health_score) as avg_health,
                   COUNT(*) as samples
            FROM device_health_samples
            WHERE device_id = ? AND ts >= ?
            GROUP BY DATE(ts)
            ORDER BY day
        ''', (device_id, cutoff)).fetchall()

        # From interface telemetry (1m rollup)
        intf_rows = conn.execute('''
            SELECT DATE(bucket) as day, interface_name,
                   AVG(avg_in_util) as avg_in, AVG(avg_out_util) as avg_out,
                   MAX(max_in_util) as peak_in, MAX(max_out_util) as peak_out
            FROM interface_telemetry_1m
            WHERE device_id = ? AND bucket >= ?
            GROUP BY DATE(bucket), interface_name
            ORDER BY day
        ''', (device_id, cutoff)).fetchall()

        # Aggregate interface data per day (pick the busiest interface)
        day_intf = {}
        for row in intf_rows:
            d = row['day']
            if d not in day_intf or max(row['avg_in'] or 0, row['avg_out'] or 0) > max(day_intf[d].get('avg_in', 0), day_intf[d].get('avg_out', 0)):
                day_intf[d] = {
                    'interface_name': row['interface_name'],
                    'avg_in': round(row['avg_in'] or 0, 1),
                    'avg_out': round(row['avg_out'] or 0, 1),
                    'peak_in': round(row['peak_in'] or 0, 1),
                    'peak_out': round(row['peak_out'] or 0, 1),
                }

        # Get current device info
        dev = conn.execute('SELECT hostname, cpu_usage, memory_usage FROM devices WHERE id = ?', (device_id,)).fetchone()
        hostname = dev['hostname'] if dev else ''

        trends = []
        for row in health_rows:
            day = row['day']
            intf = day_intf.get(day, {})
            trends.append({
                'date': day,
                'health_score': round(row['avg_health'] or 0, 1),
                'avg_in_util': intf.get('avg_in', 0),
                'avg_out_util': intf.get('avg_out', 0),
                'peak_in_util': intf.get('peak_in', 0),
                'peak_out_util': intf.get('peak_out', 0),
                'busiest_interface': intf.get('interface_name', ''),
            })

        # Simple linear forecast (next 30 days) for the busiest metric
        forecast = []
        if len(trends) >= 7:
            # Use peak utilization for forecasting
            peak_values = [max(t['peak_in_util'], t['peak_out_util']) for t in trends]
            n = len(peak_values)
            x_mean = (n - 1) / 2
            y_mean = sum(peak_values) / n
            numerator = sum((i - x_mean) * (peak_values[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
            intercept = y_mean - slope * x_mean

            for i in range(1, 31):
                predicted = slope * (n + i - 1) + intercept
                predicted = max(0, min(100, round(predicted, 1)))
                future_date = (datetime.now(timezone.utc) + timedelta(days=i)).strftime('%Y-%m-%d')
                forecast.append({'date': future_date, 'predicted_util': predicted})

            # Days until 80% and 95%
            days_to_80 = None
            days_to_95 = None
            current_val = peak_values[-1] if peak_values else 0
            if slope > 0:
                if current_val < 80:
                    days_to_80 = max(1, round((80 - intercept) / slope - n + 1))
                if current_val < 95:
                    days_to_95 = max(1, round((95 - intercept) / slope - n + 1))
        else:
            days_to_80 = None
            days_to_95 = None

        return {
            'device_id': device_id,
            'hostname': hostname,
            'trends': trends,
            'forecast': forecast,
            'days_to_80_pct': days_to_80,
            'days_to_95_pct': days_to_95,
        }
    finally:
        conn.close()


@router.get('/capacity/forecast')
def capacity_forecast_all():
    """Get capacity forecast summary for all devices — which ones will hit thresholds soonest."""
    conn = get_db_connection()
    try:
        devices = conn.execute('''
            SELECT id, hostname, ip_address, platform, cpu_usage, memory_usage
            FROM devices WHERE status = 'online'
        ''').fetchall()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        warnings = []
        for dev in devices:
            # Get recent peak interface utilization
            intf_data = conn.execute('''
                SELECT AVG(COALESCE(avg_in_util, 0)) as avg_util,
                       MAX(COALESCE(max_in_util, 0)) as peak_util
                FROM interface_telemetry_1m
                WHERE device_id = ? AND bucket >= ?
            ''', (dev['id'], cutoff)).fetchone()

            cpu = dev['cpu_usage'] or 0
            mem = dev['memory_usage'] or 0
            peak_util = round(intf_data['peak_util'] or 0, 1) if intf_data else 0
            avg_util = round(intf_data['avg_util'] or 0, 1) if intf_data else 0

            risk_level = 'normal'
            reasons = []
            if cpu >= 90:
                risk_level = 'critical'
                reasons.append(f'CPU {cpu}%')
            elif cpu >= 80:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'CPU {cpu}%')
            if mem >= 90:
                risk_level = 'critical'
                reasons.append(f'Memory {mem}%')
            elif mem >= 80:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'Memory {mem}%')
            if peak_util >= 90:
                risk_level = 'critical'
                reasons.append(f'Link peak {peak_util}%')
            elif peak_util >= 75:
                risk_level = 'warning' if risk_level == 'normal' else risk_level
                reasons.append(f'Link peak {peak_util}%')

            if risk_level != 'normal':
                warnings.append({
                    'device_id': dev['id'],
                    'hostname': dev['hostname'],
                    'ip_address': dev['ip_address'],
                    'platform': dev['platform'],
                    'cpu': cpu,
                    'memory': mem,
                    'peak_link_util': peak_util,
                    'avg_link_util': avg_util,
                    'risk_level': risk_level,
                    'reasons': reasons,
                })

        warnings.sort(key=lambda w: (0 if w['risk_level'] == 'critical' else 1, -max(w['cpu'], w['memory'], w['peak_link_util'])))
        return {
            'total_warnings': len(warnings),
            'critical_count': sum(1 for w in warnings if w['risk_level'] == 'critical'),
            'warning_count': sum(1 for w in warnings if w['risk_level'] == 'warning'),
            'items': warnings,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# IP / VLAN Resource Management
# ──────────────────────────────────────────────

class SubnetCreate(BaseModel):
    name: str = ''
    network: str
    prefix_len: int
    vlan_id: Optional[int] = None
    vlan_name: str = ''
    gateway: str = ''
    description: str = ''
    site: str = ''


class SubnetUpdate(BaseModel):
    name: Optional[str] = None
    vlan_id: Optional[int] = None
    vlan_name: Optional[str] = None
    gateway: Optional[str] = None
    description: Optional[str] = None
    site: Optional[str] = None
    status: Optional[str] = None


class IPAddressCreate(BaseModel):
    address: str
    hostname: str = ''
    device_id: str = ''
    interface_name: str = ''
    mac_address: str = ''
    device_type: str = ''
    description: str = ''
    status: str = 'active'


class IPAddressUpdate(BaseModel):
    hostname: Optional[str] = None
    device_id: Optional[str] = None
    interface_name: Optional[str] = None
    mac_address: Optional[str] = None
    device_type: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


@router.get('/ipam/subnets')
def list_subnets(site: str = 'all', status: str = 'all', q: str = ''):
    conn = get_db_connection()
    try:
        sql = 'SELECT * FROM ip_subnets WHERE 1=1'
        params = []
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
            # Count used IPs
            count = conn.execute('SELECT COUNT(*) as cnt FROM ip_addresses WHERE subnet_id = ?', (r['id'],)).fetchone()
            item['used_ips'] = count['cnt'] if count else 0
            if item['total_ips'] > 0:
                item['utilization'] = round(item['used_ips'] / item['total_ips'] * 100, 1)
            else:
                item['utilization'] = 0
            result.append(item)
        return result
    finally:
        conn.close()


@router.post('/ipam/subnets', status_code=201)
def create_subnet(body: SubnetCreate):
    conn = get_db_connection()
    try:
        # Check for overlapping subnets
        existing = conn.execute(
            'SELECT id FROM ip_subnets WHERE network = ? AND prefix_len = ?',
            (body.network, body.prefix_len)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail='Subnet already exists')

        subnet_id = f"subnet-{uuid.uuid4().hex[:12]}"
        total_ips = max(0, (2 ** (32 - body.prefix_len)) - 2) if body.prefix_len < 31 else 2
        now = _utc_now()
        conn.execute('''
            INSERT INTO ip_subnets (id, name, network, prefix_len, vlan_id, vlan_name,
                                     gateway, description, site, status, total_ips, used_ips, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?)
        ''', (subnet_id, body.name, body.network, body.prefix_len,
              body.vlan_id, body.vlan_name, body.gateway, body.description,
              body.site, total_ips, now, now))
        conn.commit()
        return {'id': subnet_id, 'total_ips': total_ips}
    finally:
        conn.close()


@router.put('/ipam/subnets/{subnet_id}')
def update_subnet(subnet_id: str, body: SubnetUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM ip_subnets WHERE id = ?', (subnet_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Subnet not found')

        updates = []
        params = []
        for field in ['name', 'vlan_id', 'vlan_name', 'gateway', 'description', 'site', 'status']:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f'{field} = ?')
                params.append(val)
        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(subnet_id)
            conn.execute(f"UPDATE ip_subnets SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.delete('/ipam/subnets/{subnet_id}')
def delete_subnet(subnet_id: str):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM ip_addresses WHERE subnet_id = ?', (subnet_id,))
        conn.execute('DELETE FROM ip_subnets WHERE subnet_id = ? OR id = ?', (subnet_id, subnet_id))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.get('/ipam/subnets/{subnet_id}/addresses')
def list_addresses(subnet_id: str):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM ip_addresses WHERE subnet_id = ? ORDER BY address',
            (subnet_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post('/ipam/subnets/{subnet_id}/addresses', status_code=201)
def create_address(subnet_id: str, body: IPAddressCreate):
    conn = get_db_connection()
    try:
        # Check subnet exists
        subnet = conn.execute('SELECT * FROM ip_subnets WHERE id = ?', (subnet_id,)).fetchone()
        if not subnet:
            raise HTTPException(status_code=404, detail='Subnet not found')

        # Check for duplicate
        existing = conn.execute(
            'SELECT id FROM ip_addresses WHERE subnet_id = ? AND address = ?',
            (subnet_id, body.address)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail='IP address already registered in this subnet')

        addr_id = f"ip-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        conn.execute('''
            INSERT INTO ip_addresses (id, subnet_id, address, hostname, device_id,
                                       interface_name, mac_address, device_type, status, description, last_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (addr_id, subnet_id, body.address, body.hostname, body.device_id,
              body.interface_name, body.mac_address, body.device_type, body.status, body.description, now, now, now))
        # Update used count
        conn.execute('UPDATE ip_subnets SET used_ips = used_ips + 1, updated_at = ? WHERE id = ?', (now, subnet_id))
        conn.commit()
        return {'id': addr_id}
    finally:
        conn.close()


@router.delete('/ipam/addresses/{address_id}')
def delete_address(address_id: str):
    conn = get_db_connection()
    try:
        addr = conn.execute('SELECT subnet_id FROM ip_addresses WHERE id = ?', (address_id,)).fetchone()
        if not addr:
            raise HTTPException(status_code=404, detail='Address not found')
        conn.execute('DELETE FROM ip_addresses WHERE id = ?', (address_id,))
        now = _utc_now()
        conn.execute('UPDATE ip_subnets SET used_ips = MAX(0, used_ips - 1), updated_at = ? WHERE id = ?', (now, addr['subnet_id']))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.put('/ipam/addresses/{address_id}')
def update_address(address_id: str, body: IPAddressUpdate):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM ip_addresses WHERE id = ?', (address_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Address not found')

        updates = []
        params = []
        for field in ['hostname', 'device_id', 'interface_name', 'mac_address', 'device_type', 'description', 'status']:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f'{field} = ?')
                params.append(val)
        if updates:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(address_id)
            conn.execute(f"UPDATE ip_addresses SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()
        return {'ok': True}
    finally:
        conn.close()


@router.get('/ipam/conflicts')
def detect_conflicts():
    """Scan for IP address conflicts (same IP in multiple subnets or duplicate MACs)."""
    conn = get_db_connection()
    try:
        # Find duplicate IPs across subnets
        dup_ips = conn.execute('''
            SELECT address, GROUP_CONCAT(subnet_id) as subnets, COUNT(*) as cnt
            FROM ip_addresses
            GROUP BY address
            HAVING cnt > 1
        ''').fetchall()

        # Find duplicate MACs
        dup_macs = conn.execute('''
            SELECT mac_address, GROUP_CONCAT(address) as addresses, COUNT(*) as cnt
            FROM ip_addresses
            WHERE mac_address != '' AND mac_address IS NOT NULL
            GROUP BY mac_address
            HAVING cnt > 1
        ''').fetchall()

        return {
            'ip_conflicts': [dict(r) for r in dup_ips],
            'mac_conflicts': [dict(r) for r in dup_macs],
            'total_conflicts': len(dup_ips) + len(dup_macs),
        }
    finally:
        conn.close()


@router.get('/ipam/summary')
def ipam_summary():
    """Quick summary of IPAM status."""
    conn = get_db_connection()
    try:
        subnets = conn.execute('SELECT COUNT(*) as cnt FROM ip_subnets').fetchone()
        addresses = conn.execute('SELECT COUNT(*) as cnt FROM ip_addresses').fetchone()
        total_capacity = conn.execute('SELECT SUM(total_ips) as total FROM ip_subnets').fetchone()
        total_used = conn.execute('SELECT SUM(used_ips) as total FROM ip_subnets').fetchone()

        high_util = conn.execute('''
            SELECT * FROM ip_subnets
            WHERE total_ips > 0 AND CAST(used_ips AS REAL) / total_ips >= 0.8
            ORDER BY CAST(used_ips AS REAL) / total_ips DESC
        ''').fetchall()

        return {
            'total_subnets': subnets['cnt'] if subnets else 0,
            'total_addresses': addresses['cnt'] if addresses else 0,
            'total_capacity': total_capacity['total'] if total_capacity and total_capacity['total'] else 0,
            'total_used': total_used['total'] if total_used and total_used['total'] else 0,
            'high_utilization_subnets': [dict(r) for r in high_util],
        }
    finally:
        conn.close()
