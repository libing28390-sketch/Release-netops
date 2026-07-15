"""
IP Locator Service — 根据 IP 地址定位设备所在交换机端口。

流程：
1. 从所有具备 L3 能力的设备采集 ARP → 获取 IP→MAC 映射（access 路由器也包含在内）
2. 用 MAC 去接入交换机采集 MAC 地址表 → 获取 MAC→Port 映射
3. 结合 LLDP 邻居信息拼出完整路径：IP → MAC → Switch → Port → Uplink

性能优化：
- 使用设备端过滤命令（如 show ip arp <ip>）减少数据传输量
- ThreadPoolExecutor 并发 SSH 采集
- ARP 阶段找到目标即取消剩余设备查询
"""

import asyncio
import uuid
import logging
import re
import threading
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime, timezone, timedelta
from typing import Any

from netmiko import ConnectHandler

from database import get_db_connection, _SERIAL_PK, init_db
from core.crypto import decrypt_credential
from services.vault_service import resolve_device_credentials
from drivers.ssh_compat import build_netmiko_compatibility_kwargs
from services.operational_data_service import (
    collect_operational_data,
    ROLE_EXCLUDED_CATEGORIES,
    PLATFORM_DEVICE_TYPE_MAP,
)
from services.oui_lookup import lookup_vendor
from core.cmd_cache import get_cached_command, set_cached_command

# 并发 SSH 连接上限，避免瞬间打开过多连接
# 小规模 (≤10 台) 取 5；中规模动态扩展到 10；大规模上限 15
MAX_SSH_WORKERS_MIN = 5
MAX_SSH_WORKERS_MAX = 15

def normalize_interface_name(name: str) -> str:
    if not name:
        return ""
    name = name.strip()
    name = re.sub(r'^(eth|ethernet)\s*(\d)', r'Ethernet\2', name, flags=re.I)
    name = re.sub(r'^(gi|gigabitethernet)\s*(\d)', r'GigabitEthernet\2', name, flags=re.I)
    name = re.sub(r'^(te|ten-gigabitethernet|tengigabitethernet)\s*(\d)', r'TenGigabitEthernet\2', name, flags=re.I)
    name = re.sub(r'^(lo|loopback)\s*(\d)', r'Loopback\2', name, flags=re.I)
    name = re.sub(r'^(vl|vlan)\s*(\d)', r'Vlan\2', name, flags=re.I)
    name = re.sub(r'\s+', '', name)
    return name


def _calc_ssh_workers(device_count: int) -> int:
    """根据设备数量动态计算并发 SSH worker 数。"""
    if device_count <= 10:
        return min(MAX_SSH_WORKERS_MIN, device_count)
    return min(MAX_SSH_WORKERS_MAX, max(MAX_SSH_WORKERS_MIN, device_count // 3))

# ARP 缓存：按 target_ip 懒加载，不做全网全量预采集
# 二级缓存架构：L1 = 进程内 dict（热数据快速命中）, L2 = SQLite（持久化跨重启）
# 采集间隔 5 分钟，TTL 10 分钟，保证在下次采集到来前始终有有效缓存
ARP_SWEEP_INTERVAL_SECONDS = 300   # 后台全量采集间隔：5 分钟
ARP_CACHE_TTL_SECONDS = 600        # 缓存有效期：10 分钟（2 倍采集间隔，保证覆盖）
ARP_CACHE_MAX_ENTRIES = 5000

logger = logging.getLogger(__name__)

_ARP_CACHE_LOCK = threading.Lock()
_ARP_CACHE: dict[str, dict[str, Any]] = {}

_MAC_NORMALIZE_RE = re.compile(r'[.\-:\s]')

# ── 设备端精确过滤命令 ──────────────────────────────
# 每个平台针对 ARP / MAC 的过滤命令模板，{ip} / {mac} 会被替换

# 不具备 ARP 表的平台（服务器/Linux），跳过 ARP 采集，避免超时拖慢整体采集
_ARP_UNSUPPORTED_PLATFORMS = frozenset({
    'linux', 'linux_ssh', 'linux_telnet',
    'windows', 'windows_ssh',
    'paloalto_panos',
})

_TARGETED_ARP_COMMANDS: dict[str, str] = {
    'cisco_ios':    'show ip arp {ip}',
    'cisco_nxos':   'show ip arp {ip}',
    'arista_eos':   'show ip arp {ip}',
    'huawei_vrp':   'display arp | include {ip}',
    'h3c_comware':  'display arp | include {ip}',
    'juniper_junos': 'show arp no-resolve | match {ip}',
    'ruijie_rgos':  'show arp | include {ip}',
}

_TARGETED_MAC_COMMANDS: dict[str, str] = {
    'cisco_ios':    'show mac address-table address {mac}',
    'cisco_nxos':   'show mac address-table address {mac}',
    'arista_eos':   'show mac address-table address {mac}',
    'huawei_vrp':   'display mac-address {mac}',
    'h3c_comware':  'display mac-address {mac}',
    'juniper_junos': 'show ethernet-switching table {mac}',
    'ruijie_rgos':  'show mac address-table address {mac}',
}

# ARP 行正则：匹配 IP、MAC（各种分隔格式）和接口
_ARP_LINE_RE = re.compile(
    r'(?P<ip>(?:\d{1,3}\.){3}\d{1,3})'          # IP 地址
    r'.*?'
    r'(?P<mac>[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}'  # xxxx.xxxx.xxxx
    r'|[0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}'
    r'[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})'  # xx:xx:xx:xx:xx:xx
    r'.*?'
    r'(?P<intf>\S+)\s*$'                          # 最后一个非空字段 = 接口
)

# MAC 表行正则：匹配 VLAN、MAC、类型、端口
_MAC_LINE_RE = re.compile(
    r'(?:^|\s)(?P<vlan>\d{1,4})\s+'
    r'(?P<mac>[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}'
    r'|[0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}'
    r'[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})\s+'
    r'(?P<type>\S+)\s+'
    r'(?P<port>\S+)'
)


def _normalize_mac(mac: str) -> str:
    """将各种格式的 MAC 地址统一为小写无分隔符的 12 位十六进制。"""
    if not mac:
        return ''
    cleaned = _MAC_NORMALIZE_RE.sub('', mac.strip()).lower()
    return cleaned if len(cleaned) == 12 else ''


def _format_mac(mac12: str) -> str:
    """将 12 位 hex 格式化为 xxxx.xxxx.xxxx（Cisco 风格）方便阅读。"""
    if len(mac12) != 12:
        return mac12
    return f'{mac12[0:4]}.{mac12[4:8]}.{mac12[8:12]}'


_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).replace(microsecond=0).isoformat()


# ── ARP 持久化缓存（SQLite L2 + 内存 L1） ──────────────────────────

import json as _json

def _ensure_arp_cache_table():
    """建表（幂等），在模块加载时调用一次。"""
    init_db()

# 模块加载时建表
try:
    _ensure_arp_cache_table()
except Exception:
    logger.warning("[IPLocator] arp_cache table init deferred")


def _get_cached_arp(target_ip: str) -> dict[str, Any] | None:
    """L1 内存 → L2 SQLite 二级查找。"""
    now_ts = time.time()

    # L1: 内存热缓存
    with _ARP_CACHE_LOCK:
        _prune_memory_cache(now_ts)
        mem = _ARP_CACHE.get(target_ip)
        if mem:
            return dict(mem)

    # L2: SQLite 持久缓存
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT mac, arp_source, cached_at, expires_at FROM arp_cache WHERE target_ip = ? AND expires_at > ?',
                (target_ip, now_ts),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None

    if not row:
        return None

    # 回填 L1
    entry = {
        'target_ip': target_ip,
        'mac': row['mac'],
        'arp_source': _json.loads(row['arp_source'] or '{}'),
        'cached_at': row['cached_at'],
        'created_at_epoch': now_ts,
        'expires_at': row['expires_at'],
    }
    with _ARP_CACHE_LOCK:
        _ARP_CACHE[target_ip] = entry

    return dict(entry)


def _set_cached_arp(target_ip: str, mac: str, arp_source: dict[str, Any] | None):
    """同时写入 L1 内存 + L2 SQLite。"""
    now_ts = time.time()
    cached_at = _beijing_now_iso()
    expires_at = now_ts + ARP_CACHE_TTL_SECONDS
    source_dict = dict(arp_source or {})

    # L1 写入
    entry = {
        'target_ip': target_ip,
        'mac': mac,
        'arp_source': source_dict,
        'cached_at': cached_at,
        'created_at_epoch': now_ts,
        'expires_at': expires_at,
    }
    with _ARP_CACHE_LOCK:
        _ARP_CACHE[target_ip] = entry
        _prune_memory_cache(now_ts)

    # L2 写入（upsert）
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                '''INSERT INTO arp_cache (target_ip, mac, arp_source, cached_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(target_ip) DO UPDATE SET
                       mac = excluded.mac,
                       arp_source = excluded.arp_source,
                       cached_at = excluded.cached_at,
                       expires_at = excluded.expires_at''',
                (target_ip, mac, _json.dumps(source_dict), cached_at, expires_at),
            )
            
            # Write to arp_table as well
            dev_id = source_dict.get('device_id')
            if not dev_id:
                dev_label = source_dict.get('device')
                if dev_label:
                    d_row = conn.execute("SELECT id FROM devices WHERE hostname = ? OR ip_address = ?", (dev_label, dev_label)).fetchone()
                    if d_row:
                        dev_id = d_row['id']
            if not dev_id:
                d_row = conn.execute("SELECT id FROM devices LIMIT 1").fetchone()
                if d_row:
                    dev_id = d_row['id']
            if dev_id:
                conn.execute("DELETE FROM arp_table WHERE device_id = ? AND ip_address = ?", (dev_id, target_ip))
                conn.execute(
                    '''INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), dev_id, target_ip, mac, source_dict.get('interface') or '', cached_at)
                )

            # 顺便清理过期行（轻量级，不阻塞）
            conn.execute('DELETE FROM arp_cache WHERE expires_at <= ?', (now_ts,))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"[IPLocator] arp_cache DB write error: {exc}")


def _prune_memory_cache(now_ts: float):
    """清理内存 L1 中过期和超限的条目（需在锁内调用）。"""
    expired_keys = [k for k, v in _ARP_CACHE.items() if float(v.get('expires_at', 0)) <= now_ts]
    for k in expired_keys:
        _ARP_CACHE.pop(k, None)

    if len(_ARP_CACHE) <= ARP_CACHE_MAX_ENTRIES:
        return
    over = len(_ARP_CACHE) - ARP_CACHE_MAX_ENTRIES
    oldest = sorted(
        _ARP_CACHE.items(),
        key=lambda item: float(item[1].get('created_at_epoch', 0.0)),
    )[:over]
    for k, _ in oldest:
        _ARP_CACHE.pop(k, None)


def _load_eligible_devices(role_filter: list[str] | None = None) -> list[dict]:
    """加载有 SSH 凭据的设备列表，可按 role 过滤。"""
    conn = get_db_connection()
    try:
        sql = "SELECT * FROM devices WHERE status = 'online'"
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    devices = []
    for r in rows:
        d = dict(r)
        # 跳过不支持 ARP 采集的平台（Linux 服务器等），避免超时
        platform = str(d.get('platform') or '').lower()
        if platform in _ARP_UNSUPPORTED_PLATFORMS:
            continue
        creds = resolve_device_credentials(d)
        auth_model = (d.get('auth_model') or 'single').lower()

        # dual 模式：优先用 admin 账号登录（与 operational_data_service 保持一致）
        if auth_model == 'dual':
            username = creds.get('admin_username') or creds.get('username') or (d.get('admin_username') or d.get('username') or '').strip()
            password = creds.get('admin_password') or creds.get('password') or ''
        else:
            username = creds['username'] or (d.get('username') or '').strip()
            password = creds['password']

        if not username or not password:
            continue
        if role_filter:
            dev_role = (d.get('role') or '').lower().strip()
            if dev_role not in role_filter:
                continue
        # 把解析好的登录凭据写回 dict，供 _build_ssh_params 直接使用
        d['_ssh_username'] = username
        d['_ssh_password'] = password
        d['_ssh_enable'] = creds.get('enable_password') or ''
        devices.append(d)
    return devices


def _build_ssh_params(device_info: dict) -> dict[str, Any]:
    """构建 netmiko ConnectHandler 参数（轻量版，仅 IP Locator 使用）。"""
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    device_type = PLATFORM_DEVICE_TYPE_MAP.get(platform, 'cisco_ios')
    # 优先使用 _load_eligible_devices 预解析好的登录凭据（已处理 dual 模式）
    username = device_info.get('_ssh_username') or device_info.get('username') or ''
    password = device_info.get('_ssh_password') or device_info.get('password') or ''
    enable  = device_info.get('_ssh_enable')  or device_info.get('enable_password') or ''
    params = {
        'device_type': device_type,
        'host': device_info.get('ip_address'),
        'username': username,
        'password': password,
        'port': int(device_info.get('port') or device_info.get('management_port') or 22),
        'timeout': 10,
        'session_timeout': 20,
        'fast_cli': platform not in {'huawei_vrp', 'h3c_comware'},
        'global_delay_factor': 1.2 if platform in {'huawei_vrp', 'h3c_comware'} else 0.3,
        'blocking_timeout': 15,
    }
    params.update(build_netmiko_compatibility_kwargs())
    if enable:
        params['secret'] = enable
    return params


def _send_command(device_info: dict, command: str) -> str:
    """SSH 到设备执行单条命令并返回原始输出。"""
    device_ip = device_info.get('ip_address') or device_info.get('hostname') or 'unknown'
    cached = get_cached_command(device_ip, command)
    if cached is not None:
        return cached

    port = int(device_info.get('port') or device_info.get('management_port') or 22)
    from drivers.ssh_compat import is_ssh_port_open
    if not is_ssh_port_open(device_ip, port):
        logger.warning("SSH port %s is closed/unreachable for %s", port, device_ip)
        return ""

    conn_params = _build_ssh_params(device_info)
    with ConnectHandler(**conn_params) as client:
        if conn_params.get('secret'):
            try:
                client.enable()
            except Exception:
                pass
        output = client.send_command(
            command,
            cmd_verify=False,
            strip_prompt=True,
            strip_command=True,
            read_timeout=30,
        )
        set_cached_command(device_ip, command, output)
        return output


# ── 精确 ARP 查询 ─────────────────────────────────────

def _targeted_arp_query(device_info: dict, target_ip: str, vrf: str = None) -> dict | None:
    """
    向设备发送精确 ARP 查询命令，仅返回目标 IP 的记录。
    数据量：1 条记录 vs 全表可能上万条。
    支持可选的 vrf 参数，用于在特定的 VRF 虚拟路由上下文中查询 ARP 表。
    失败时回退到全表采集。
    """
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    
    if vrf:
        if platform in ('cisco_ios', 'cisco_nxos', 'arista_eos', 'ruijie_rgos'):
            cmd_template = 'show ip arp vrf {vrf} {ip}'
        elif platform in ('huawei_vrp', 'h3c_comware'):
            cmd_template = 'display arp vpn-instance {vrf} | include {ip}'
        elif platform in ('juniper_junos',):
            cmd_template = 'show arp table {vrf} no-resolve | match {ip}'
        else:
            cmd_template = _TARGETED_ARP_COMMANDS.get(platform)
    else:
        cmd_template = _TARGETED_ARP_COMMANDS.get(platform)

    if cmd_template:
        try:
            if vrf:
                cmd = cmd_template.format(ip=target_ip, vrf=vrf)
            else:
                cmd = cmd_template.format(ip=target_ip)
            output = _send_command(device_info, cmd)
            # 解析输出行，寻找包含目标 IP 的 ARP 条目
            for line in output.splitlines():
                if target_ip not in line:
                    continue
                m = _ARP_LINE_RE.search(line)
                if m and m.group('ip') == target_ip:
                    mac_norm = _normalize_mac(m.group('mac'))
                    if mac_norm:
                        return {
                            'ip': target_ip,
                            'mac': mac_norm,
                            'mac_display': _format_mac(mac_norm),
                            'interface': m.group('intf'),
                            'source_device_id': device_info.get('id'),
                            'source_device': device_info.get('hostname') or device_info.get('ip_address'),
                        }
        except Exception as exc:
            logger.debug(f"[IPLocator] Targeted ARP query failed on {device_info.get('ip_address')}: {exc}")

    # 回退：全表采集 + 搜索
    return _collect_arp_from_device_for_ip(device_info, target_ip)


def _collect_arp_from_device_for_ip(device_info: dict, target_ip: str) -> dict | None:
    """全表采集 ARP 并搜索目标 IP（回退路径），找到即返回，不继续解析剩余记录。"""
    try:
        payload = collect_operational_data(device_info, categories=['arp'])
    except Exception as exc:
        logger.debug(f"[IPLocator] ARP collect failed on {device_info.get('ip_address')}: {exc}")
        return None

    for cat in payload.get('categories', []):
        if cat.get('key') == 'arp' and cat.get('success'):
            for rec in cat.get('records', []):
                ip_addr = rec.get('address', '').strip()
                if ip_addr != target_ip:
                    continue
                mac_raw = rec.get('hardware_address', '') or rec.get('mac_address', '') or rec.get('mac', '')
                iface = rec.get('interface', '')
                mac_norm = _normalize_mac(mac_raw)
                if mac_norm:
                    return {
                        'ip': target_ip,
                        'mac': mac_norm,
                        'mac_display': _format_mac(mac_norm),
                        'interface': iface,
                        'source_device_id': device_info.get('id'),
                        'source_device': device_info.get('hostname') or device_info.get('ip_address'),
                    }
    return None


# ── 精确 MAC 查询 ─────────────────────────────────────

def _targeted_mac_query(device_info: dict, target_mac: str) -> list[dict]:
    """
    向设备发送精确 MAC 地址表查询命令。
    target_mac 为 12 位 hex（无分隔符），函数内部转为设备所需格式。
    """
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    cmd_template = _TARGETED_MAC_COMMANDS.get(platform)

    if cmd_template:
        try:
            # 转为设备可识别的 MAC 格式
            mac_formatted = _format_mac(target_mac)  # xxxx.xxxx.xxxx (Cisco)
            if platform in ('huawei_vrp', 'h3c_comware'):
                # Huawei/H3C 使用 xxxx-xxxx-xxxx
                mac_formatted = f'{target_mac[0:4]}-{target_mac[4:8]}-{target_mac[8:12]}'
            elif platform == 'juniper_junos':
                # Juniper 使用 xx:xx:xx:xx:xx:xx
                mac_formatted = ':'.join(target_mac[i:i+2] for i in range(0, 12, 2))

            cmd = cmd_template.format(mac=mac_formatted)
            output = _send_command(device_info, cmd)
            return _parse_mac_output(output, target_mac, device_info)
        except Exception as exc:
            logger.debug(f"[IPLocator] Targeted MAC query failed on {device_info.get('ip_address')}: {exc}")

    # 回退：全表采集 + 过滤
    return _collect_mac_from_device_for_mac(device_info, target_mac)


def _parse_mac_output(output: str, target_mac: str, device_info: dict) -> list[dict]:
    """解析 MAC 表输出，提取匹配目标 MAC 的记录。"""
    records = []
    for line in output.splitlines():
        m = _MAC_LINE_RE.search(line)
        if not m:
            continue
        mac_norm = _normalize_mac(m.group('mac'))
        if mac_norm != target_mac:
            continue
        records.append({
            'mac': mac_norm,
            'port': m.group('port').strip(),
            'vlan': m.group('vlan').strip(),
            'type': m.group('type').strip(),
            'switch_id': device_info.get('id'),
            'switch_name': device_info.get('hostname') or device_info.get('ip_address'),
        })
    return records


def _collect_mac_from_device_for_mac(device_info: dict, target_mac: str) -> list[dict]:
    """全表采集 MAC 地址表并过滤目标 MAC（回退路径）。"""
    try:
        payload = collect_operational_data(device_info, categories=['mac_table'])
    except Exception as exc:
        logger.debug(f"[IPLocator] MAC collect failed on {device_info.get('ip_address')}: {exc}")
        return []

    records = []
    for cat in payload.get('categories', []):
        if cat.get('key') == 'mac_table' and cat.get('success'):
            for rec in cat.get('records', []):
                mac_raw = rec.get('destination_address', '') or rec.get('mac_address', '') or rec.get('mac', '')
                mac_norm = _normalize_mac(mac_raw)
                if mac_norm != target_mac:
                    continue
                port_field = rec.get('destination_port', '') or rec.get('port', '') or rec.get('interface', '')
                if isinstance(port_field, list):
                    port_field = port_field[0] if port_field else ''
                vlan = rec.get('vlan_id', '') or rec.get('vlan', '')
                if port_field:
                    records.append({
                        'mac': mac_norm,
                        'port': str(port_field).strip(),
                        'vlan': str(vlan).strip(),
                        'type': rec.get('type', ''),
                        'switch_id': device_info.get('id'),
                        'switch_name': device_info.get('hostname') or device_info.get('ip_address'),
                    })
    return records


def _collect_lldp_from_device(device_info: dict) -> list[dict]:
    """从单台设备采集 LLDP/CDP 邻居信息。"""
    try:
        payload = collect_operational_data(device_info, categories=['neighbors'])
    except Exception as exc:
        logger.debug(f"[IPLocator] LLDP collect failed on {device_info.get('ip_address')}: {exc}")
        return []

    records = []
    for cat in payload.get('categories', []):
        if cat.get('key') == 'neighbors' and cat.get('success'):
            for rec in cat.get('records', []):
                local_intf = rec.get('local_interface', '') or rec.get('interface', '')
                neighbor = rec.get('neighbor', '') or rec.get('neighbor_name', '') or rec.get('system_name', '')
                neighbor_port = rec.get('neighbor_interface', '') or rec.get('neighbor_port', '') or rec.get('port_id', '')
                if local_intf:
                    records.append({
                        'local_interface': str(local_intf).strip(),
                        'neighbor': str(neighbor).strip(),
                        'neighbor_port': str(neighbor_port).strip(),
                    })
    return records


def _check_local_device_ip(device_info: dict, target_ip: str, vrf: str = None) -> dict | None:
    """检查 target_ip 是否是设备的本地接口 IP（如 Loopback 口），支持 VRF 上下文"""
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    if platform in _ARP_UNSUPPORTED_PLATFORMS:
        return None
    
    if platform in ('huawei_vrp', 'h3c_comware'):
        cmd = 'display ip interface brief'
    else:
        cmd = 'show ip interface brief'
        
    try:
        output = _send_command(device_info, cmd)
        for line in output.splitlines():
            if re.search(r'\b' + re.escape(target_ip) + r'\b', line):
                parts = line.split()
                if parts:
                    intf_name = parts[0]
                    return {
                        'ip': target_ip,
                        'interface': intf_name,
                        'device_id': device_info.get('id'),
                        'device_name': device_info.get('hostname') or device_info.get('ip_address'),
                    }
    except Exception as exc:
        logger.debug(f"[IPLocator] Local IP check failed on {device_info.get('ip_address')}: {exc}")
    return None


def _get_ip_network_role(target_ip: str) -> dict | None:
    """查询目标 IP 所属的最具体网段（prefix）及其 network_type。

    用于 Smart Trace：互联地址(transit) 背后是网络设备接口，应走路由邻居
    (OSPF/BGP/IS-IS) 与接口状态检查，而非 ARP/MAC 终端定位。
    """
    try:
        ip_obj = ipaddress.ip_address(target_ip)
    except ValueError:
        return None

    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, prefix, name, network_type FROM prefixes"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"[IPLocator] network role lookup error: {exc}")
        return None

    best = None
    best_len = -1
    for r in rows:
        try:
            net = ipaddress.ip_network(r['prefix'], strict=False)
        except (ValueError, KeyError):
            continue
        if net.version != ip_obj.version:
            continue
        if ip_obj in net and net.prefixlen > best_len:
            best_len = net.prefixlen
            best = r

    if best is None:
        return None
    return {
        'prefix_id': best['id'],
        'prefix': best['prefix'],
        'name': best['name'],
        'network_type': (best['network_type'] or 'server'),
    }


def locate_ip(target_ip: str, force_refresh: bool = False) -> dict[str, Any]:
    """
    核心定位逻辑：IP → MAC（ARP） → Port（MAC表 + LLDP 拓扑追踪）

    性能与精度策略：
    - L1 级事实库缓存：优先查询 network_endpoints 表，0 连接数据库毫秒返回。
    - L2 级 IP 资产库：查询 ip_inventory（Loopback/VIP等无 ARP 设备 IP）与 IPAM / 设备管理 IP。
    - L3 级 拓扑跳步追踪（Path-Tracing）：缓存未命中时，使用数据库 links 拓扑库寻找邻居交换机，消除实时的 show lldp neighbors 命令行连接。
    """
    result: dict[str, Any] = {
        'target_ip': target_ip,
        'found': False,
        'mac': None,
        'mac_display': None,
        'arp_source': None,
        'locations': [],
        'searched_devices': {'arp': [], 'mac': [], 'lldp': []},
        'cache': {
            'enabled': True,
            'arp_cache_hit': False,
            'ttl_seconds': ARP_CACHE_TTL_SECONDS,
            'force_refresh': force_refresh,
            'cached_at': None,
        },
        'timestamp': _beijing_now_iso(),
        'errors': [],
    }

    # ── Step -1: 网段角色识别 ──
    # 互联地址 (Transit) 背后是网络设备接口，应切换到路由/邻居检查策略，
    # 而非 ARP/MAC 终端定位。Loopback 同理标注以供前端区分展示。
    net_role = _get_ip_network_role(target_ip)
    if net_role:
        result['address_role'] = net_role['network_type']
        result['prefix_info'] = {
            'prefix': net_role['prefix'],
            'name': net_role['name'],
        }

    if net_role and net_role['network_type'] == 'transit':
        result['found'] = True
        result['is_transit'] = True
        result['recommended_checks'] = [
            'routing_table', 'ospf', 'bgp', 'interface_status',
        ]
        loc = {
            'switch_id': None,
            'switch_name': '',
            'port': '',
            'vlan': '',
            'type': 'TRANSIT_LINK',
            'is_uplink': True,
            'note': (
                '设备互联地址 (Transit Network)：该地址背后为网络设备接口，'
                '建议进行路由邻居 (OSPF/BGP/IS-IS) 与接口状态检查，'
                '而非 ARP/MAC 终端定位。'
            ),
        }
        # 尝试补充该互联地址归属的设备与接口
        try:
            conn = get_db_connection()
            try:
                row = conn.execute(
                    "SELECT inv.device_id, inv.interface, d.hostname "
                    "FROM ip_inventory inv "
                    "LEFT JOIN devices d ON inv.device_id = d.id "
                    "WHERE inv.ip = ?",
                    (target_ip,),
                ).fetchone()
                if row:
                    loc['switch_id'] = row['device_id']
                    loc['switch_name'] = row['hostname'] or ''
                    loc['port'] = row['interface'] or ''
                    loc['note'] += (
                        f" 归属设备: {row['hostname'] or row['device_id']}，"
                        f"接口: {row['interface'] or 'N/A'}。"
                    )
            finally:
                conn.close()
        except Exception as exc:
            logger.debug(f"[IPLocator] transit device lookup error: {exc}")
        result['locations'] = [loc]
        return result

    # ── Step 0: 预检查缓存与 IP 资产库 ──
    if not force_refresh:
        # 1. 查找 network_endpoints 事实缓存
        cached_ep = _get_cached_endpoint(target_ip)
        if cached_ep:
            result['found'] = True
            result['mac'] = cached_ep['mac']
            result['mac_display'] = _format_mac(cached_ep['mac'])
            result['locations'] = [{
                'switch_id': cached_ep.get('switch_id') or cached_ep.get('device_id'),
                'switch_name': cached_ep.get('site') or '',
                'port': cached_ep.get('switch_port') or cached_ep.get('port'),
                'vlan': cached_ep.get('vlan') or '',
                'type': 'CACHED_ENDPOINT',
                'is_uplink': False,
                'note': '本地事实缓存命中',
            }]
            result['cache']['cached_at'] = cached_ep.get('last_seen')
            result['cache']['arp_cache_hit'] = True
            return result

        # 2. 查找 ip_inventory 资产库 (支持 Loopback/设备接口等无 ARP 数据)
        try:
            conn = get_db_connection()
            try:
                row = conn.execute(
                    "SELECT inv.ip, inv.mask, inv.device_id, inv.interface, inv.type, d.hostname "
                    "FROM ip_inventory inv "
                    "LEFT JOIN devices d ON inv.device_id = d.id "
                    "WHERE inv.ip = ?",
                    (target_ip,)
                ).fetchone()
                if row:
                    result['found'] = True
                    result['mac'] = 'N/A'
                    result['mac_display'] = 'N/A (IP 资产登记)'
                    result['locations'] = [{
                        'switch_id': row['device_id'],
                        'switch_name': row['hostname'] or '',
                        'port': row['interface'],
                        'vlan': '',
                        'type': 'IP_INVENTORY',
                        'is_uplink': False,
                        'note': f"该 IP 为网络设备登记资产，接口: {row['interface']}, 类型: {row['type']}",
                    }]
                    return result
            finally:
                conn.close()
        except Exception as e:
            logger.debug(f"[IPLocator] ip_inventory check error: {e}")

    # ── 一次性加载所有有 SSH 凭据的在线设备 ──
    all_eligible = _load_eligible_devices()
    if not all_eligible:
        result['errors'].append('没有可用的设备用于查询')
        return result

    # ARP 采集不按角色排除——access 路由器同样拥有 ARP 表
    gateway_devices = all_eligible

    target_mac: str = ''
    arp_source_info: dict | None = None

    # ── Step 1: ARP 懒加载缓存（仅按 IP 命中，不做全网预采集） ──
    if not force_refresh:
        cached_arp = _get_cached_arp(target_ip)
        if cached_arp:
            target_mac = str(cached_arp.get('mac') or '')
            arp_source_info = cached_arp.get('arp_source') or None
            result['cache']['arp_cache_hit'] = True
            result['cache']['cached_at'] = cached_arp.get('cached_at')

    # ── Step 1.5: 未命中缓存则并发 ARP 实时查询（找到即终止） ──
    if not target_mac:
        workers = _calc_ssh_workers(len(gateway_devices))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map: dict[Future, dict] = {}
            for dev in gateway_devices:
                f = executor.submit(_targeted_arp_query, dev, target_ip)
                future_map[f] = dev

            for future in as_completed(future_map):
                dev = future_map[future]
                dev_label = dev.get('hostname') or dev.get('ip_address')
                result['searched_devices']['arp'].append(dev_label)

                try:
                    arp_hit = future.result()
                except Exception as exc:
                    logger.debug(f"[IPLocator] ARP future error for {dev_label}: {exc}")
                    continue

                if arp_hit:
                    target_mac = arp_hit['mac']
                    arp_source_info = {
                        'device_id': arp_hit['source_device_id'],
                        'device': arp_hit['source_device'],
                        'interface': arp_hit['interface'],
                    }
                    # 早期终止：取消尚未开始的任务
                    for pending_f in future_map:
                        if not pending_f.done():
                            pending_f.cancel()
                    break

        if target_mac:
            _set_cached_arp(target_ip, target_mac, arp_source_info)

    # ── Step 1.7: 如果 ARP 未找到，并发检查是否是网络设备自身的本地接口/环回口 ──
    if not target_mac:
        workers = _calc_ssh_workers(len(all_eligible))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map_local = {
                executor.submit(_check_local_device_ip, dev, target_ip): dev
                for dev in all_eligible
            }
            for future in as_completed(future_map_local):
                dev = future_map_local[future]
                try:
                    local_hit = future.result()
                    if local_hit:
                        target_mac = 'N/A'
                        result['mac'] = 'N/A'
                        result['mac_display'] = 'N/A (环回口/设备接口)'
                        result['arp_source'] = {
                            'device_id': local_hit['device_id'],
                            'device': local_hit['device_name'],
                            'interface': local_hit['interface']
                        }
                        result['found'] = True
                        result['locations'] = [{
                            'switch_id': local_hit['device_id'],
                            'switch_name': local_hit['device_name'],
                            'port': local_hit['interface'],
                            'vlan': '',
                            'type': 'DEVICE_INTERFACE',
                            'is_uplink': False,
                            'note': '该 IP 为网络设备自身的接口/环回口地址',
                        }]
                        for pending_f in future_map_local:
                            if not pending_f.done():
                                pending_f.cancel()
                        return result
                except Exception as exc:
                    logger.debug(f"[IPLocator] Local IP check error: {exc}")

    if not target_mac:
        result['errors'].append(f'在 {len(gateway_devices)} 台网关设备的 ARP 表中未找到 {target_ip}')
        return result

    result['mac'] = target_mac
    result['mac_display'] = _format_mac(target_mac)
    result['arp_source'] = arp_source_info

    # ── Step 2: 拓扑追踪定位 (Path Tracing) ──
    curr_device_id = arp_source_info.get('device_id')
    visited_switches = {curr_device_id}
    trace_notes = []
    terminal_switch_id = None
    terminal_port = None
    terminal_vlan = ''
    terminal_type = 'DYNAMIC'

    trace_notes.append(f"开始追踪：源 ARP 学习自网关 {arp_source_info.get('device')} ({arp_source_info.get('interface')})")

    _SWITCH_ROLES = frozenset({'switch', 'access', 'distribution', 'core', 'aggregation', 'l2', 'l3switch'})
    _MAC_EXCLUDED_ROLES = frozenset({'router', 'firewall', 'gateway', 'server', 'linux', 'windows'})
    switch_devices = [
        d for d in all_eligible
        if (d.get('role') or '').lower().strip() not in _MAC_EXCLUDED_ROLES
    ]

    try:
        conn = get_db_connection()
        try:
            while True:
                dev_dict = next((d for d in all_eligible if d.get('id') == curr_device_id), None)
                if not dev_dict:
                    trace_notes.append(f"设备 ID {curr_device_id} 不在管理资产中或未在线，追踪终止。")
                    break

                dev_label = dev_dict.get('hostname') or dev_dict.get('ip_address')
                result['searched_devices']['mac'].append(dev_label)

                try:
                    mac_records = _targeted_mac_query(dev_dict, target_mac)
                except Exception as e:
                    trace_notes.append(f"查询设备 {dev_label} MAC 表出错: {e}")
                    break

                if not mac_records:
                    trace_notes.append(f"在设备 {dev_label} 上未匹配到 MAC {target_mac}。")
                    break

                mac_rec = mac_records[0]
                curr_port = mac_rec['port']
                terminal_vlan = mac_rec.get('vlan', '')
                terminal_type = mac_rec.get('type', 'DYNAMIC')
                
                terminal_switch_id = curr_device_id
                terminal_port = curr_port

                # 判断是否为上联端口
                neighbor_id = None
                neighbor_name = None
                port_norm = normalize_interface_name(curr_port).lower()

                # [Topology Cache 优化]：优先查本地 links 数据库，避免 SSH 收集 lldp neighbors
                row_link = conn.execute(
                    "SELECT target_device_id AS neighbor_id, target_hostname AS neighbor_name "
                    "FROM topology_links WHERE source_device_id = ? AND LOWER(source_port_normalized) = ?",
                    (curr_device_id, port_norm)
                ).fetchone()
                if not row_link:
                    row_link = conn.execute(
                        "SELECT source_device_id AS neighbor_id, source_hostname AS neighbor_name "
                        "FROM topology_links WHERE target_device_id = ? AND LOWER(target_port_normalized) = ?",
                        (curr_device_id, port_norm)
                    ).fetchone()

                if row_link:
                    neighbor_name = row_link['neighbor_name']
                    neighbor_id = row_link['neighbor_id']
                    trace_notes.append(f"[拓扑缓存命中] 接口 {curr_port} 连接了下游邻居 {neighbor_name}")
                    if neighbor_id not in visited_switches:
                        curr_device_id = neighbor_id
                        visited_switches.add(curr_device_id)
                        continue
                    else:
                        break
                else:
                    result['searched_devices']['lldp'].append(dev_label)
                    try:
                        lldp_records = _collect_lldp_from_device(dev_dict)
                    except Exception as e:
                        logger.debug(f"[IPLocator] Error querying LLDP neighbors on {dev_label}: {e}")
                        lldp_records = []

                    for lrec in lldp_records:
                        if normalize_interface_name(lrec['local_interface']).lower() == port_norm:
                            neighbor_name = lrec['neighbor']
                            break

                    if neighbor_name:
                        neighbor_dev = lookup_neighbor_device(conn, neighbor_name, "")
                        if neighbor_dev and neighbor_dev['id'] not in visited_switches:
                            curr_device_id = neighbor_dev['id']
                            visited_switches.add(curr_device_id)
                            trace_notes.append(f"设备 {dev_label} 接口 {curr_port} 连接了下游邻居 {neighbor_name}，继续追踪。")
                            continue
                        else:
                            trace_notes.append(f"发现接口 {curr_port} 存在邻居 {neighbor_name}，但其不在管理资产中或已访问过，追踪终止。")
                            break
                    else:
                        trace_notes.append(f"设备 {dev_label} 接口 {curr_port} 无下挂邻居设备，判定为直连主机的接入端口。")
                        break
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"[IPLocator] Path tracing database error: {exc}")

    # ── Step 3: 构造最终结果与缓存 ──
    if terminal_switch_id and terminal_port:
        term_dev = next((d for d in all_eligible if d.get('id') == terminal_switch_id), None)
        term_label = term_dev.get('hostname') or term_dev.get('ip_address') if term_dev else ''
        
        result['found'] = True
        result['locations'] = [{
            'switch_id': terminal_switch_id,
            'switch_name': term_label,
            'port': terminal_port,
            'vlan': terminal_vlan,
            'type': 'PATH_TRACED',
            'is_uplink': False,
            'note': ' -> '.join(trace_notes),
        }]
        
        # 保存事实缓存
        _set_cached_endpoint(
            ip=target_ip,
            mac=target_mac,
            device_id=terminal_switch_id,
            port=terminal_port,
            vlan=terminal_vlan,
            site=term_label,
            confidence='98% (精准拓扑追踪端口)',
            source_type='path_traced'
        )
    elif arp_source_info:
        result['found'] = True
        result['locations'] = [{
            'switch_id': arp_source_info.get('device_id'),
            'switch_name': arp_source_info.get('device'),
            'port': arp_source_info.get('interface') or 'N/A',
            'vlan': '',
            'type': 'ARP_DIRECT',
            'is_uplink': False,
            'note': '该 MAC 未在交换机 MAC 表中发现，定位基于 ARP 记录',
        }]
    
    return result



async def locate_ip_async(target_ip: str) -> dict[str, Any]:
    """异步包装，在线程池中执行阻塞的 SSH 操作。"""
    return await asyncio.to_thread(locate_ip, target_ip)


async def locate_ip_async_with_options(target_ip: str, force_refresh: bool = False) -> dict[str, Any]:
    """异步包装（带选项），支持强制刷新跳过缓存。"""
    return await asyncio.to_thread(locate_ip, target_ip, force_refresh)


# ── 后台全量 ARP 采集 ──────────────────────────────────────────────

def _collect_full_arp_from_device(device_info: dict) -> list[dict]:
    """从单台设备采集完整 ARP 表，返回解析后的条目列表。"""
    try:
        payload = collect_operational_data(device_info, categories=['arp'])
    except Exception as exc:
        logger.debug(f"[ARP Sweep] collect failed on {device_info.get('ip_address')}: {exc}")
        return []

    entries = []
    dev_label = device_info.get('hostname') or device_info.get('ip_address')
    dev_id = device_info.get('id')
    for cat in payload.get('categories', []):
        if cat.get('key') == 'arp' and cat.get('success'):
            for rec in cat.get('records', []):
                ip_addr = (rec.get('address', '') or '').strip()
                mac_raw = rec.get('hardware_address', '') or rec.get('mac_address', '') or rec.get('mac', '')
                iface = rec.get('interface', '')
                mac_norm = _normalize_mac(mac_raw)
                if ip_addr and mac_norm:
                    entries.append({
                        'ip': ip_addr,
                        'mac': mac_norm,
                        'interface': iface,
                        'source_device_id': dev_id,
                        'source_device': dev_label,
                    })
    return entries


def run_arp_sweep():
    """
    后台全量 ARP 采集：并发 SSH 到所有网关设备，采集完整 ARP 表并写入缓存。
    由 APScheduler 定时调度（每 5 分钟）。
    """
    logger.info("[ARP Sweep] Starting full ARP table collection...")
    t0 = time.time()

    all_eligible = _load_eligible_devices()
    # ARP 采集不按角色排除——access 路由器同样拥有 ARP 表
    gateway_devices = all_eligible

    if not gateway_devices:
        logger.info("[ARP Sweep] No eligible devices, skipping")
        return

    logger.info(f"[ARP Sweep] {len(gateway_devices)} eligible device(s) found, starting collection")

    all_entries: list[dict] = []
    workers = _calc_ssh_workers(len(gateway_devices))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_collect_full_arp_from_device, dev): dev for dev in gateway_devices}
        for future in as_completed(future_map):
            dev = future_map[future]
            try:
                entries = future.result()
                all_entries.extend(entries)
            except Exception as exc:
                logger.debug(f"[ARP Sweep] Error from {dev.get('ip_address')}: {exc}")

    if not all_entries:
        logger.info("[ARP Sweep] No ARP entries collected")
        return

    # ── MAC 变更检测 ──
    # 先读取旧的 ARP 缓存快照，用于和本次采集结果比较
    old_arp_map: dict[str, tuple[str, str]] = {}  # ip → (mac, device)
    try:
        conn = get_db_connection()
        try:
            for row in conn.execute('SELECT target_ip, mac, arp_source FROM arp_cache').fetchall():
                src = _json.loads(row['arp_source'] or '{}')
                old_arp_map[row['target_ip']] = (row['mac'], src.get('device', ''))
        finally:
            conn.close()
    except Exception:
        pass

    mac_changes: list[dict] = []
    for e in all_entries:
        old = old_arp_map.get(e['ip'])
        if old and old[0] != e['mac']:
            mac_changes.append({
                'ip': e['ip'],
                'old_mac': old[0],
                'new_mac': e['mac'],
                'old_vendor': lookup_vendor(old[0]),
                'new_vendor': lookup_vendor(e['mac']),
                'old_device': old[1],
                'new_device': e['source_device'],
            })

    # 批量写入 L1 + L2
    now_ts = time.time()
    cached_at = _beijing_now_iso()
    expires_at = now_ts + ARP_CACHE_TTL_SECONDS

    # L2: 批量 upsert SQLite
    try:
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM arp_cache WHERE expires_at <= ?', (now_ts,))
            for e in all_entries:
                source_dict = {
                    'device_id': e['source_device_id'],
                    'device': e['source_device'],
                    'interface': e['interface'],
                }
                conn.execute(
                    '''INSERT INTO arp_cache (target_ip, mac, arp_source, cached_at, expires_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(target_ip) DO UPDATE SET
                           mac = excluded.mac,
                           arp_source = excluded.arp_source,
                           cached_at = excluded.cached_at,
                           expires_at = excluded.expires_at''',
                    (e['ip'], e['mac'], _json.dumps(source_dict), cached_at, expires_at),
                )
                
                # Bulk update to arp_table as well
                dev_id = e['source_device_id']
                if not dev_id:
                    dev_label = e['source_device']
                    if dev_label:
                        d_row = conn.execute("SELECT id FROM devices WHERE hostname = ? OR ip_address = ?", (dev_label, dev_label)).fetchone()
                        if d_row:
                            dev_id = d_row['id']
                if not dev_id:
                    d_row = conn.execute("SELECT id FROM devices LIMIT 1").fetchone()
                    if d_row:
                        dev_id = d_row['id']
                if dev_id:
                    conn.execute("DELETE FROM arp_table WHERE device_id = ? AND ip_address = ?", (dev_id, e['ip']))
                    conn.execute(
                        '''INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), dev_id, e['ip'], e['mac'], e['interface'] or '', cached_at)
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"[ARP Sweep] DB batch write error: {exc}")

    # L1: 批量写入内存
    with _ARP_CACHE_LOCK:
        for e in all_entries:
            _ARP_CACHE[e['ip']] = {
                'target_ip': e['ip'],
                'mac': e['mac'],
                'arp_source': {
                    'device_id': e['source_device_id'],
                    'device': e['source_device'],
                    'interface': e['interface'],
                },
                'cached_at': cached_at,
                'created_at_epoch': now_ts,
                'expires_at': expires_at,
            }
        _prune_memory_cache(now_ts)

    elapsed = round(time.time() - t0, 1)
    # 写入 MAC 变更日志
    if mac_changes:
        detected_at = cached_at
        try:
            conn = get_db_connection()
            try:
                for c in mac_changes:
                    conn.execute(
                        '''INSERT INTO mac_change_log (ip, old_mac, new_mac, old_vendor, new_vendor, old_device, new_device, detected_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (c['ip'], c['old_mac'], c['new_mac'], c['old_vendor'], c['new_vendor'], c['old_device'], c['new_device'], detected_at),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.error(f"[ARP Sweep] MAC change log write error: {exc}")
        logger.warning(f"[ARP Sweep] Detected {len(mac_changes)} MAC address changes")
    logger.info(f"[ARP Sweep] Collected {len(all_entries)} entries from {len(gateway_devices)} devices in {elapsed}s")


async def run_arp_sweep_async():
    """异步包装，供 APScheduler 调度。"""
    await asyncio.to_thread(run_arp_sweep)


# ── 全量 ARP 表查询 ────────────────────────────────────────────────

def get_arp_table() -> dict[str, Any]:
    """查询 SQLite 中所有有效 ARP 缓存条目，供前端展示。"""
    now_ts = time.time()
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT target_ip, mac, arp_source, cached_at, expires_at FROM arp_cache WHERE expires_at > ? ORDER BY target_ip',
                (now_ts,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    for row in rows:
        source = _json.loads(row['arp_source'] or '{}')
        mac_raw = row['mac']
        entries.append({
            'ip': row['target_ip'],
            'mac': _format_mac(mac_raw),
            'mac_raw': mac_raw,
            'vendor': lookup_vendor(mac_raw),
            'interface': source.get('interface', ''),
            'device': source.get('device', ''),
            'device_id': source.get('device_id'),
            'cached_at': row['cached_at'],
            'ttl_remaining': max(0, int(row['expires_at'] - now_ts)),
        })

    return {
        'total': len(entries),
        'ttl_seconds': ARP_CACHE_TTL_SECONDS,
        'sweep_interval_seconds': ARP_SWEEP_INTERVAL_SECONDS,
        'entries': entries,
        'timestamp': _beijing_now_iso(),
    }


async def get_arp_table_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_arp_table)


# ── MAC 变更日志查询 ────────────────────────────────────────────────

def get_mac_changes(limit: int = 200) -> dict[str, Any]:
    """查询最近的 MAC 变更记录。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT id, ip, old_mac, new_mac, old_vendor, new_vendor, old_device, new_device, detected_at '
                'FROM mac_change_log ORDER BY detected_at DESC, id DESC LIMIT ?',
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    for row in rows:
        entries.append({
            'id': row['id'],
            'ip': row['ip'],
            'old_mac': _format_mac(row['old_mac']),
            'new_mac': _format_mac(row['new_mac']),
            'old_mac_raw': row['old_mac'],
            'new_mac_raw': row['new_mac'],
            'old_vendor': row['old_vendor'],
            'new_vendor': row['new_vendor'],
            'old_device': row['old_device'],
            'new_device': row['new_device'],
            'detected_at': row['detected_at'],
        })
    return {
        'total': len(entries),
        'entries': entries,
        'timestamp': _beijing_now_iso(),
    }


async def get_mac_changes_async(limit: int = 200) -> dict[str, Any]:
    return await asyncio.to_thread(get_mac_changes, limit)


# === RESTORED MISSING FUNCTIONS ===


def lookup_neighbor_device(conn, neighbor_host: str, next_hop_ip: str) -> dict | None:
    """在设备表和 IPAM 表中根据主机名或 IP 地址查找匹配的设备。"""
    if neighbor_host:
        h = neighbor_host.strip().lower()
        row = conn.execute(
            "SELECT id, hostname, role, platform, ip_address FROM devices WHERE LOWER(hostname) = ? OR LOWER(hostname) LIKE ?",
            (h, h + ".%")
        ).fetchone()
        if row:
            return dict(row)

    if next_hop_ip and next_hop_ip != "directly connected" and next_hop_ip != "local":
        ip = next_hop_ip.strip()
        row = conn.execute(
            "SELECT id, hostname, role, platform, ip_address FROM devices WHERE TRIM(ip_address) = ?",
            (ip,)
        ).fetchone()
        if row:
            return dict(row)

        row_ip = conn.execute(
            "SELECT d.id, d.hostname, d.role, d.platform, d.ip_address "
            "FROM ip_addresses ip "
            "JOIN devices d ON ip.device_id = d.id "
            "WHERE TRIM(ip.address) = ?", (ip,)
        ).fetchone()
        if row_ip:
            return dict(row_ip)

        row_inv = conn.execute(
            "SELECT d.id, d.hostname, d.role, d.platform, d.ip_address "
            "FROM ip_inventory inv "
            "JOIN devices d ON inv.device_id = d.id "
            "WHERE TRIM(inv.ip) = ?", (ip,)
        ).fetchone()
        if row_inv:
            return dict(row_inv)

    return None


def _get_cached_endpoint(ip: str) -> dict[str, Any] | None:
    """从 SQLite network_endpoints 事实表中查询终端。"""
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT id, ip, mac, hostname, vendor, os_type, asset_type, switch_id, switch_port, vlan, vrf, site, source_type, confidence, first_seen, last_seen, is_active '
                'FROM network_endpoints WHERE ip = ? AND is_active = 1',
                (ip,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"[IPLocator] get cached endpoint error: {e}")
        return None

    if not row:
        return None

    res = dict(row)
    if 'device_id' not in res and 'switch_id' in res:
        res['device_id'] = res['switch_id']
    if 'switch_port' in res:
        res['port'] = res['switch_port']
    return res


def _set_cached_endpoint(
    ip: str, mac: str, device_id: str, port: str,
    vlan: str = '', site: str = '', confidence: str = '95%',
    hostname: str = '', vendor: str = '', os_type: str = '',
    asset_type: str = 'host', vrf: str = '', source_type: str = 'arp',
    first_seen: str = None
):
    """保存或更新终端事实记录到 network_endpoints 表。"""
    import uuid
    last_seen = _beijing_now_iso()
    if not first_seen:
        first_seen = last_seen
    uid = f"{ip}_{mac}"
    try:
        conn = get_db_connection()
        try:
            existing = conn.execute("SELECT first_seen, switch_id, switch_port, vlan FROM network_endpoints WHERE ip = ?", (ip,)).fetchone()
            if existing:
                first_seen = existing['first_seen']
                old_sw = existing['switch_id']
                old_port = existing['switch_port']
                old_vl = existing['vlan']
                if old_sw != device_id or old_port != port or old_vl != vlan:
                    drift_id = str(uuid.uuid4())
                    conn.execute(
                        '''INSERT INTO endpoint_history (id, ip, mac, old_switch_id, old_switch_port, old_vlan, new_switch_id, new_switch_port, new_vlan, drift_type, detected_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'drift', ?)''',
                        (drift_id, ip, mac, old_sw, old_port, old_vl, device_id, port, vlan, last_seen)
                    )

            conn.execute(
                '''INSERT INTO network_endpoints (id, ip, mac, hostname, vendor, os_type, asset_type, switch_id, switch_port, vlan, vrf, site, source_type, confidence, first_seen, last_seen, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(ip) DO UPDATE SET
                       mac = excluded.mac,
                       hostname = excluded.hostname,
                       vendor = excluded.vendor,
                       os_type = excluded.os_type,
                       asset_type = excluded.asset_type,
                       switch_id = excluded.switch_id,
                       switch_port = excluded.switch_port,
                       vlan = excluded.vlan,
                       vrf = excluded.vrf,
                       site = excluded.site,
                       source_type = excluded.source_type,
                       confidence = excluded.confidence,
                       last_seen = excluded.last_seen,
                       is_active = 1''',
                (uid, ip, mac, hostname, vendor or lookup_vendor(mac), os_type, asset_type, device_id, port, vlan, vrf, site, source_type, confidence, first_seen, last_seen),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.error(f"[IPLocator] write endpoint cache DB error: {exc}")




# ── 全量 MAC 表采集 ─────────────────────────────────────────

def _collect_full_mac_table_from_device(device_info: dict) -> list[dict]:
    """从单台交换机采集完整的 MAC 地址表（所有 VLAN）。"""
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    if platform in ('huawei_vrp', 'h3c_comware'):
        cmd = 'display mac-address'
    elif platform in ('juniper_junos',):
        cmd = 'show ethernet-switching table'
    else:
        cmd = 'show mac address-table'

    try:
        output = _send_command(device_info, cmd)
    except Exception as exc:
        logger.debug(f"[MAC Collector] Failed from {device_info.get('ip_address')}: {exc}")
        return []

    records = []
    dev_id = device_info.get('id', '')
    dev_name = device_info.get('hostname') or device_info.get('ip_address') or ''

    for line in output.splitlines():
        m = _MAC_LINE_RE.search(line)
        if not m:
            continue
        vlan = m.group('vlan')
        mac_raw = m.group('mac')
        port_field = m.group('port')
        mac_norm = _normalize_mac(mac_raw)
        if not mac_norm or len(mac_norm) != 12:
            continue

        records.append({
            'mac': mac_norm,
            'vlan': str(vlan).strip(),
            'port': str(port_field).strip(),
            'type': m.group('type'),
            'switch_id': dev_id,
            'switch_name': dev_name,
        })
    return records


def get_network_endpoints() -> dict[str, Any]:
    """查询 network_endpoints 表所有活跃终端，供前端展示。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT id, ip, mac, hostname, vendor, os_type, asset_type, switch_id, switch_port, vlan, vrf, site, source_type, confidence, first_seen, last_seen, is_active '
                'FROM network_endpoints WHERE is_active = 1 ORDER BY last_seen DESC'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    stats = {}
    for row in rows:
        e = dict(row)
        if 'switch_port' in e:
            e['port'] = e['switch_port']
        if 'mac' in e:
            e['mac_display'] = _format_mac(e['mac']) if e['mac'] else '—'
        t = e.get('asset_type', 'host')
        stats[t] = stats.get(t, 0) + 1
        entries.append(e)

    return {
        'total': len(entries),
        'type_stats': stats,
        'entries': entries,
        'table_name': 'network_endpoints',
        'columns': ['ip', 'mac', 'hostname', 'vendor', 'os_type', 'asset_type', 'switch_id', 'switch_port', 'vlan', 'vrf', 'site', 'source_type', 'confidence', 'first_seen', 'last_seen'],
        'timestamp': _beijing_now_iso(),
    }


async def get_network_endpoints_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_network_endpoints)


def get_ip_inventory() -> dict[str, Any]:
    """查询 ip_inventory 表所有 IP 资产，供前端展示。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT inv.ip, inv.mask, inv.device_id, inv.interface, inv.type, inv.last_seen, d.hostname AS device_name '
                'FROM ip_inventory inv LEFT JOIN devices d ON inv.device_id = d.id '
                'ORDER BY inv.last_seen DESC'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = [dict(row) for row in rows]
    type_stats = {}
    for e in entries:
        t = e.get('type', 'unknown')
        type_stats[t] = type_stats.get(t, 0) + 1

    return {
        'total': len(entries),
        'type_stats': type_stats,
        'entries': entries,
        'table_name': 'ip_inventory',
        'columns': ['ip', 'mask', 'device_id', 'device_name', 'interface', 'type', 'last_seen'],
        'timestamp': _beijing_now_iso(),
    }


async def get_ip_inventory_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_ip_inventory)


def get_route_cache() -> dict[str, Any]:
    """查询 route_table 表所有路由条目，供前端展示。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT rc.id, rc.device_id, rc.vrf_name, rc.destination, rc.next_hop, rc.protocol, rc.outgoing_interface, rc.metric, rc.last_updated, d.hostname AS device_name '
                'FROM route_table rc LEFT JOIN devices d ON rc.device_id = d.id '
                'ORDER BY rc.device_id, rc.destination'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    for row in rows:
        row_dict = dict(row)
        dest = row_dict.get('destination') or ''
        prefix, mask = dest, ''
        if '/' in dest:
            try:
                prefix, mask_len_str = dest.split('/')
                mask_len = int(mask_len_str)
                mask_int = (0xffffffff >> (32 - mask_len)) << (32 - mask_len)
                mask = f"{(mask_int >> 24) & 0xff}.{(mask_int >> 16) & 0xff}.{(mask_int >> 8) & 0xff}.{mask_int & 0xff}"
            except Exception:
                pass
        
        entries.append({
            'id': row_dict.get('id'),
            'device_id': row_dict.get('device_id'),
            'device_name': row_dict.get('device_name'),
            'vrf_name': row_dict.get('vrf_name') or 'default',
            'prefix': prefix,
            'mask': mask,
            'next_hop': row_dict.get('next_hop'),
            'protocol': row_dict.get('protocol'),
            'interface': row_dict.get('outgoing_interface'),
            'metric': row_dict.get('metric'),
            'last_update': row_dict.get('last_updated')
        })

    proto_stats = {}
    for e in entries:
        p = e.get('protocol', 'unknown')
        proto_stats[p] = proto_stats.get(p, 0) + 1
    device_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1

    return {
        'total': len(entries),
        'protocol_stats': proto_stats,
        'device_stats': device_stats,
        'entries': entries,
        'table_name': 'route_table',
        'columns': ['id', 'device_id', 'device_name', 'vrf_name', 'prefix', 'mask', 'next_hop', 'protocol', 'interface', 'metric', 'last_update'],
        'timestamp': _beijing_now_iso(),
    }


async def get_route_cache_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_route_cache)


def get_routing_neighbors() -> dict[str, Any]:
    """查询 routing_neighbors 表所有路由协议邻居条目，供前端展示。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT rn.id, rn.device_id, rn.protocol, rn.neighbor_id, rn.neighbor_ip, rn.local_interface, rn.state, rn.uptime, rn.local_as, rn.remote_as, rn.area_id, rn.last_updated, d.hostname AS device_name '
                'FROM routing_neighbors rn LEFT JOIN devices d ON rn.device_id = d.id '
                'ORDER BY rn.device_id, rn.protocol, rn.neighbor_ip'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    for row in rows:
        row_dict = dict(row)
        entries.append({
            'id': row_dict.get('id'),
            'device_id': row_dict.get('device_id'),
            'device_name': row_dict.get('device_name'),
            'protocol': row_dict.get('protocol'),
            'neighbor_id': row_dict.get('neighbor_id'),
            'neighbor_ip': row_dict.get('neighbor_ip'),
            'local_interface': row_dict.get('local_interface'),
            'state': row_dict.get('state'),
            'uptime': row_dict.get('uptime'),
            'local_as': row_dict.get('local_as'),
            'remote_as': row_dict.get('remote_as'),
            'area_id': row_dict.get('area_id'),
            'last_update': row_dict.get('last_updated')
        })

    proto_stats = {}
    for e in entries:
        p = e.get('protocol', 'unknown')
        proto_stats[p] = proto_stats.get(p, 0) + 1
    device_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1

    return {
        'total': len(entries),
        'protocol_stats': proto_stats,
        'device_stats': device_stats,
        'entries': entries,
        'table_name': 'routing_neighbors',
        'columns': ['id', 'device_id', 'device_name', 'protocol', 'neighbor_id', 'neighbor_ip', 'local_interface', 'state', 'uptime', 'remote_as', 'area_id', 'last_update'],
        'timestamp': _beijing_now_iso(),
    }


def get_bgp_routes() -> dict[str, Any]:
    """查询 bgp_route_table 表所有路由条目，供前端展示。"""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                'SELECT br.id, br.device_id, br.vrf_name, br.prefix, br.next_hop, br.metric, br.loc_pref, br.weight, br.as_path, br.local_as, br.is_best, br.is_active, br.last_updated, d.hostname AS device_name '
                'FROM bgp_route_table br LEFT JOIN devices d ON br.device_id = d.id '
                'ORDER BY br.device_id, br.vrf_name, br.prefix, br.next_hop'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = []
    for row in rows:
        row_dict = dict(row)
        entries.append({
            'id': row_dict.get('id'),
            'device_id': row_dict.get('device_id'),
            'device_name': row_dict.get('device_name'),
            'vrf_name': row_dict.get('vrf_name'),
            'prefix': row_dict.get('prefix'),
            'next_hop': row_dict.get('next_hop'),
            'metric': row_dict.get('metric'),
            'loc_pref': row_dict.get('loc_pref'),
            'weight': row_dict.get('weight'),
            'as_path': row_dict.get('as_path'),
            'local_as': row_dict.get('local_as'),
            'is_best': row_dict.get('is_best'),
            'is_active': row_dict.get('is_active'),
            'last_update': row_dict.get('last_updated')
        })

    device_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1

    return {
        'total': len(entries),
        'device_stats': device_stats,
        'entries': entries,
        'table_name': 'bgp_route_table',
        'columns': ['id', 'device_id', 'device_name', 'vrf_name', 'prefix', 'next_hop', 'metric', 'loc_pref', 'weight', 'as_path', 'local_as', 'is_best', 'is_active', 'last_update'],
        'timestamp': _beijing_now_iso(),
    }


async def get_routing_neighbors_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_routing_neighbors)


async def get_bgp_routes_async() -> dict[str, Any]:
    return await asyncio.to_thread(get_bgp_routes)


# ── 设备接口 IP 采集 ──────────────────────────────────────

def _parse_brief_interface_ips(output: str, device_info: dict) -> list[dict]:
    records = []
    dev_id = device_info.get('id', '')
    dev_name = device_info.get('hostname') or device_info.get('ip_address') or ''
    ipv4_re = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})')

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(kw in line.lower() for kw in ('interface', 'ip-address', 'ok?', 'method', 'status', 'protocol', 'physical')):
            continue

        match = ipv4_re.search(line)
        if not match:
            continue

        ip = match.group(1)
        if ip in ('0.0.0.0', '255.255.255.255'):
            continue
        if ip.startswith('169.254.'):
            continue

        parts = line.split()
        intf_name = parts[0] if parts else 'unknown'

        mask = '255.255.255.255'
        ip_col = match.group(0)
        if '/' in ip_col and ip_col.startswith(ip):
            prefix_len = ip_col.split('/')[1]
            try:
                pl = int(prefix_len)
                mask = _int_to_netmask(pl)
            except ValueError:
                pass
        else:
            for part in parts[1:]:
                if '/' in part and part.startswith(ip):
                    prefix_len = part.split('/')[1]
                    try:
                        pl = int(prefix_len)
                        mask = _int_to_netmask(pl)
                    except ValueError:
                        pass
                    break

        records.append({
            'ip': ip,
            'mask': mask,
            'interface': intf_name,
            'device_id': dev_id,
            'device_name': dev_name,
        })
    return records


def _parse_detailed_interface_ips(output: str, platform: str, device_info: dict) -> list[dict]:
    records = []
    dev_id = device_info.get('id', '')
    dev_name = device_info.get('hostname') or device_info.get('ip_address') or ''
    
    current_intf = None
    
    # Matches interface headers
    # Cisco style: GigabitEthernet1 is up
    cisco_intf_re = re.compile(r"^([A-Za-z0-9\/\.\-\:]+)\s+is\s+(up|down|administratively|testing)", re.IGNORECASE)
    # Huawei style: GigabitEthernet0/0/0 current state : UP
    huawei_intf_re = re.compile(r"^([A-Za-z0-9\/\.\-\:]+)\s+current\s+state\s*:", re.IGNORECASE)
    
    # Matches Internet Address (IP + mask length or subnet mask)
    # e.g., Internet address is 10.1.67.6/24
    # e.g., Internet address is 10.1.67.6, Subnet mask is 255.255.255.0
    ip_re = re.compile(r"Internet\s+[aA]ddress\s+is\s+(\d+\.\d+\.\d+\.\d+)(?:/(\d+))?(?:,\s+Subnet\s+mask\s+is\s+(\d+\.\d+\.\d+\.\d+))?", re.IGNORECASE)

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
            
        cisco_match = cisco_intf_re.match(line)
        if cisco_match:
            current_intf = cisco_match.group(1)
            continue
            
        huawei_match = huawei_intf_re.match(line)
        if huawei_match:
            current_intf = huawei_match.group(1)
            continue
            
        ip_match = ip_re.search(line)
        if ip_match and current_intf:
            ip = ip_match.group(1)
            prefix_len = ip_match.group(2)
            sub_mask = ip_match.group(3)
            
            if ip in ('0.0.0.0', '255.255.255.255') or ip.startswith('169.254.'):
                continue
                
            mask = '255.255.255.255'
            if prefix_len:
                try:
                    pl = int(prefix_len)
                    mask = _int_to_netmask(pl)
                except ValueError:
                    pass
            elif sub_mask:
                mask = sub_mask
                
            records.append({
                'ip': ip,
                'mask': mask,
                'interface': current_intf,
                'device_id': dev_id,
                'device_name': dev_name,
            })
            
    return records


def _collect_device_interface_ips(device_info: dict) -> list[dict]:
    """从设备采集所有本地接口 IP（Loopback/物理接口/VLAN 等），用于 ip_inventory 同步。"""
    platform = str(device_info.get('platform') or 'cisco_ios').lower()
    if platform in _ARP_UNSUPPORTED_PLATFORMS:
        return []

    # Prefer detailed interface command that returns masks
    if platform in ('huawei_vrp', 'h3c_comware'):
        cmd = 'display ip interface'
    else:
        cmd = 'show ip interface'

    try:
        output = _send_command(device_info, cmd)
        records = _parse_detailed_interface_ips(output, platform, device_info)
        if records:
            return records
        # If no records parsed (perhaps command succeeded but output empty/unparsed), raise to fallback
        raise ValueError("No interface IP records parsed from detailed command.")
    except Exception as exc:
        logger.debug(f"[IP Inventory] Detailed interface IP collection failed for {device_info.get('ip_address')}, falling back to brief: {exc}")
        if platform in ('huawei_vrp', 'h3c_comware'):
            cmd_fallback = 'display ip interface brief'
        else:
            cmd_fallback = 'show ip interface brief'
        try:
            output = _send_command(device_info, cmd_fallback)
            return _parse_brief_interface_ips(output, device_info)
        except Exception as fallback_exc:
            logger.debug(f"[IP Inventory] Fallback brief command also failed for {device_info.get('ip_address')}: {fallback_exc}")
            return []


# ── IP Inventory 同步 ────────────────────────────────────

def sync_ip_inventory():
    """从已登记的 IPAM (ip_addresses) 与设备接口配置中同步 Loopback/物理接口 IP 到 ip_inventory。"""
    logger.info("[IP Inventory Sync] Starting sync from ip_addresses and device interfaces...")
    total_ipam = 0
    total_device = 0

    # ── Phase 1: Sync from IPAM (ip_addresses) ──
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT ip.address, ip.device_id, ip.interface_name, d.hostname, ip.ip_address "
                "FROM ip_addresses ip "
                "JOIN devices d ON ip.device_id = d.id"
            ).fetchall()

            last_seen = _beijing_now_iso()
            for row in rows:
                ip = row['address'].strip()
                ip_addr_with_mask = row['ip_address'] or ''
                intf = row['interface_name'] or 'unknown'
                dev_id = row['device_id']

                # Compute mask based on registered ip_address (which contains prefix length)
                mask = '255.255.255.255'
                if '/' in ip_addr_with_mask:
                    try:
                        prefix_len = int(ip_addr_with_mask.split('/')[1])
                        mask = _int_to_netmask(prefix_len)
                    except Exception:
                        pass
                elif '/' in ip:
                    try:
                        prefix_len = int(ip.split('/')[1])
                        mask = _int_to_netmask(prefix_len)
                        ip = ip.split('/')[0]
                    except Exception:
                        pass

                intf_lower = intf.lower()
                ip_type = 'physical'
                if 'loopback' in intf_lower or 'lo' in intf_lower:
                    ip_type = 'loopback'
                elif 'vlan' in intf_lower or 'vl' in intf_lower:
                    ip_type = 'vlan'
                elif 'tunnel' in intf_lower:
                    ip_type = 'tunnel'

                conn.execute(
                    '''INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ip) DO UPDATE SET
                           mask = excluded.mask,
                           device_id = excluded.device_id,
                           interface = excluded.interface,
                           type = excluded.type,
                           last_seen = excluded.last_seen''',
                    (ip, mask, dev_id, intf, ip_type, last_seen),
                )
                total_ipam += 1
            conn.commit()
            logger.info(f"[IP Inventory Sync] Phase 1 (IPAM): synced {total_ipam} IPs.")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[IP Inventory Sync] Phase 1 (IPAM) failed: {e}")

    # ── Phase 2: Auto-discover interface IPs from online devices ──
    try:
        all_devices = _load_eligible_devices()
        if all_devices:
            workers = min(5, len(all_devices))
            device_ips: list[dict] = []
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_collect_device_interface_ips, dev): dev
                    for dev in all_devices
                }
                for future in as_completed(future_map):
                    try:
                        records = future.result()
                        device_ips.extend(records)
                    except Exception as exc:
                        logger.debug(f"[IP Inventory Sync] Device collection error: {exc}")

            if device_ips:
                conn = get_db_connection()
                try:
                    last_seen = _beijing_now_iso()
                    for rec in device_ips:
                        ip = rec['ip']
                        intf = rec['interface']
                        dev_id = rec['device_id']
                        mask = rec.get('mask', '255.255.255.255')

                        intf_lower = intf.lower()
                        ip_type = 'physical'
                        if 'loopback' in intf_lower or 'lo' in intf_lower:
                            ip_type = 'loopback'
                        elif 'vlan' in intf_lower or 'vl' in intf_lower:
                            ip_type = 'vlan'
                        elif 'tunnel' in intf_lower:
                            ip_type = 'tunnel'

                        conn.execute(
                            '''INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
                               VALUES (?, ?, ?, ?, ?, ?)
                               ON CONFLICT(ip) DO UPDATE SET
                                   mask = excluded.mask,
                                   device_id = excluded.device_id,
                                   interface = excluded.interface,
                                   type = excluded.type,
                                   last_seen = excluded.last_seen''',
                            (ip, mask, dev_id, intf, ip_type, last_seen),
                        )
                        total_device += 1
                    conn.commit()
                    logger.info(f"[IP Inventory Sync] Phase 2 (Devices): synced {total_device} IPs from {len(all_devices)} devices.")
                finally:
                    conn.close()
    except Exception as e:
        logger.error(f"[IP Inventory Sync] Phase 2 (Devices) failed: {e}")

    logger.info(f"[IP Inventory Sync] Complete — IPAM: {total_ipam}, Devices: {total_device}")


# ── 终端事实库后台同步 ──────────────────────────────────

def run_endpoint_collector():
    """
    后台终端事实库同步任务：
    1. 触发 ARP Sweep 以确保本地 ARP 缓存最新。
    2. 获取所有的在线交换机设备，并发采集其完整的 MAC 地址表。
    3. 获取所有的 LLDP/CDP 拓扑连接，构建上联口白名单。
    4. 对比 ARP 和 MAC，找出每个活跃 IP 的最佳接入端口，写入 network_endpoints 表。
    5. 同步 IP Inventory 表。
    """
    logger.info("[Endpoint Collector] Starting endpoint cache sync...")
    t0 = time.time()

    # 1. 确保 ARP 缓存最新
    try:
        run_arp_sweep()
    except Exception as e:
        logger.error(f"[Endpoint Collector] ARP sweep failed: {e}")

    arp_data = get_arp_table()
    arp_entries = arp_data.get('entries', [])
    if not arp_entries:
        logger.info("[Endpoint Collector] No active ARP entries found, skipping.")
        # Still sync IP inventory even without ARP
        try:
            sync_ip_inventory()
        except Exception as e:
            logger.error(f"[Endpoint Collector] Error syncing IP Inventory: {e}")
        return

    # 2. 获取所有在线交换机
    all_eligible = _load_eligible_devices()
    _MAC_EXCLUDED_ROLES = frozenset({'router', 'firewall', 'gateway', 'server', 'linux', 'windows'})
    switch_devices = [
        d for d in all_eligible
        if (d.get('role') or '').lower().strip() not in _MAC_EXCLUDED_ROLES
    ]
    if not switch_devices:
        logger.info("[Endpoint Collector] No eligible switch devices found.")
        try:
            sync_ip_inventory()
        except Exception as e:
            logger.error(f"[Endpoint Collector] Error syncing IP Inventory: {e}")
        return

    workers = min(3, len(switch_devices))
    all_mac_records: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_collect_full_mac_table_from_device, dev): dev for dev in switch_devices}
        for future in as_completed(future_map):
            dev = future_map[future]
            try:
                records = future.result()
                all_mac_records.extend(records)
            except Exception as exc:
                logger.debug(f"[Endpoint Collector] MAC collection error from {dev.get('ip_address')}: {exc}")

    if not all_mac_records:
        logger.warning("[Endpoint Collector] No MAC entries collected from switches. Proceeding with fallback logic.")

    # 3. 收集 LLDP/CDP 邻居以判定上联口
    conn = get_db_connection()
    uplink_ports = set()
    try:
        rows = conn.execute("SELECT source_device_id, source_port, target_device_id, target_port FROM topology_links").fetchall()
        for r in rows:
            if r['source_device_id'] and r['source_port']:
                uplink_ports.add((r['source_device_id'], normalize_interface_name(r['source_port']).lower()))
            if r['target_device_id'] and r['target_port']:
                uplink_ports.add((r['target_device_id'], normalize_interface_name(r['target_port']).lower()))
    except Exception as e:
        logger.debug(f"[Endpoint Collector] Error querying topology links: {e}")
    finally:
        conn.close()

    # 4. 对比匹配
    mac_to_locations = {}
    for rec in all_mac_records:
        mac = rec['mac']
        switch_id = rec['switch_id']
        port_norm = normalize_interface_name(rec['port']).lower()

        is_uplink = (switch_id, port_norm) in uplink_ports or any(kw in port_norm for kw in ('po', 'port-channel', 'lag', 'eth-trunk'))
        rec['is_uplink'] = is_uplink

        if mac not in mac_to_locations:
            mac_to_locations[mac] = []
        mac_to_locations[mac].append(rec)

    endpoints_to_save = []
    for arp in arp_entries:
        ip = arp['ip']
        mac_raw = arp['mac_raw']
        mac_norm = _normalize_mac(mac_raw)

        locations = mac_to_locations.get(mac_norm, [])
        if not locations:
            if arp.get('device_id') and arp.get('interface'):
                endpoints_to_save.append({
                    'ip': ip,
                    'mac': mac_norm,
                    'device_id': arp['device_id'],
                    'port': arp['interface'],
                    'vlan': '',
                    'site': arp.get('device', ''),
                    'confidence': '80% (基于 ARP 学习源)',
                })
            continue

        locations.sort(key=lambda x: (x.get('is_uplink', False), x.get('type', '') == 'STATIC'))
        best_loc = locations[0]

        confidence = '98% (精准接入端口)'
        if best_loc.get('is_uplink'):
            confidence = '70% (仅发现上联端口匹配)'

        endpoints_to_save.append({
            'ip': ip,
            'mac': mac_norm,
            'device_id': best_loc['switch_id'],
            'port': best_loc['port'],
            'vlan': best_loc['vlan'],
            'site': best_loc['switch_name'],
            'confidence': confidence,
        })

    if endpoints_to_save:
        try:
            conn = get_db_connection()
            try:
                conn.execute("UPDATE network_endpoints SET is_active = 0")

                last_seen = _beijing_now_iso()
                for ep in endpoints_to_save:
                    existing = conn.execute("SELECT first_seen, switch_id, switch_port, vlan FROM network_endpoints WHERE ip = ?", (ep['ip'],)).fetchone()
                    if existing:
                        first_seen = existing['first_seen']
                        old_sw = existing['switch_id']
                        old_port = existing['switch_port']
                        old_vl = existing['vlan']
                        if old_sw != ep['device_id'] or old_port != ep['port'] or old_vl != ep['vlan']:
                            import uuid
                            drift_id = str(uuid.uuid4())
                            conn.execute(
                                '''INSERT INTO endpoint_history (id, ip, mac, old_switch_id, old_switch_port, old_vlan, new_switch_id, new_switch_port, new_vlan, drift_type, detected_at)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'drift', ?)''',
                                (drift_id, ep['ip'], ep['mac'], old_sw, old_port, old_vl, ep['device_id'], ep['port'], ep['vlan'], last_seen)
                            )
                    else:
                        first_seen = last_seen
                    uid = f"{ep['ip']}_{ep['mac']}"

                    conn.execute(
                        '''INSERT INTO network_endpoints (id, ip, mac, hostname, vendor, os_type, asset_type, switch_id, switch_port, vlan, vrf, site, source_type, confidence, first_seen, last_seen, is_active)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                           ON CONFLICT(ip) DO UPDATE SET
                               mac = excluded.mac,
                               hostname = excluded.hostname,
                               vendor = excluded.vendor,
                               os_type = excluded.os_type,
                               asset_type = excluded.asset_type,
                               switch_id = excluded.switch_id,
                               switch_port = excluded.switch_port,
                               vlan = excluded.vlan,
                               vrf = excluded.vrf,
                               site = excluded.site,
                               source_type = excluded.source_type,
                               confidence = excluded.confidence,
                               last_seen = excluded.last_seen,
                               is_active = 1''',
                        (uid, ep['ip'], ep['mac'], ep.get('hostname', ''), lookup_vendor(ep['mac']), ep.get('os_type', ''), ep.get('asset_type', 'host'), ep['device_id'], ep['port'], ep['vlan'], ep.get('vrf', ''), ep['site'], ep.get('source_type', 'arp'), ep['confidence'], first_seen, last_seen),
                    )
                conn.commit()
                logger.info(f"[Endpoint Collector] Successfully synced {len(endpoints_to_save)} endpoints to Network Source of Truth cache.")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[Endpoint Collector] Error writing to network_endpoints table: {e}")

    # 同步 IP Inventory 表
    try:
        sync_ip_inventory()
    except Exception as e:
        logger.error(f"[Endpoint Collector] Error syncing IP Inventory: {e}")

    elapsed = round(time.time() - t0, 1)
    logger.info(f"[Endpoint Collector] Finished endpoint cache sync in {elapsed}s.")


async def run_endpoint_collector_async():
    await asyncio.to_thread(run_endpoint_collector)


# ── 路由表解析与采集 ─────────────────────────────────────

def _int_to_netmask(prefix_len: int) -> str:
    """把前缀长度 (0-32) 转换为子网掩码字符串。"""
    mask = (0xffffffff >> (32 - prefix_len)) << (32 - prefix_len)
    return f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"


def parse_routing_table(output: str, platform: str) -> list[dict]:
    """解析完整的 show ip route / display ip routing-table 输出，提取前缀、掩码、下一跳、出接口和协议类型。"""
    platform = platform.lower()
    routes = []

    # ── Huawei/H3C ──
    if any(p in platform for p in ('huawei', 'vrp', 'comware', 'h3c')):
        for line in output.splitlines():
            m = re.search(r'(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\w+)\s+\d+\s+\d+\s+\w*\s+(\S+)\s+(\S+)', line)
            if m:
                dest, mask_len_str, proto, next_hop, interface = m.groups()
                mask_len = int(mask_len_str)
                netmask = _int_to_netmask(mask_len)
                routes.append({
                    'prefix': dest,
                    'mask': netmask,
                    'next_hop': "directly connected" if proto.lower() == 'direct' else next_hop,
                    'protocol': proto.lower(),
                    'interface': interface,
                    'metric': 0
                })
        return routes

    # ── Juniper ──
    if 'juniper' in platform or 'junos' in platform:
        current_dest = None
        current_mask = None
        for line in output.splitlines():
            m_dest = re.search(r'(\d+\.\d+\.\d+\.\d+)/(\d+)', line)
            if m_dest:
                current_dest = m_dest.group(1)
                current_mask = _int_to_netmask(int(m_dest.group(2)))
                continue
            if current_dest and ('Next hop:' in line or 'via' in line):
                m_nh = re.search(r'Next hop:\s+([^\s,]+)\s+via\s+(\S+)|via\s+(\S+)', line)
                if m_nh:
                    if m_nh.group(1) and m_nh.group(2):
                        nh = m_nh.group(1)
                        intf = m_nh.group(2)
                    else:
                        nh = "directly connected"
                        intf = m_nh.group(3)
                    routes.append({
                        'prefix': current_dest,
                        'mask': current_mask,
                        'next_hop': nh,
                        'protocol': 'static',
                        'interface': intf,
                        'metric': 0
                    })
        return routes

    # ── Cisco IOS / Default ──
    current_subnet = None
    last_dest = None
    last_mask = None
    last_proto = None

    for line in output.splitlines():
        line = line.strip()
        m_subnet = re.search(r'^(\d+\.\d+\.\d+\.\d+)/(\d+)\s+is\s+subnetted', line)
        if m_subnet:
            current_subnet = m_subnet.group(2)
            continue

        m_route = re.search(
            r'^(?P<proto>[C|S|O|B|D|R|L]\*?\s*(?:IA|EX2|E2|E1|L1|L2)?)\s+'
            r'(?P<dest>\d+\.\d+\.\d+\.\d+)(?P<mask_len_part>/\d+)?',
            line
        )
        if m_route:
            gd = m_route.groupdict()
            proto = gd['proto'].strip().lower()
            dest = gd['dest']
            mask_len_part = gd['mask_len_part']
            if mask_len_part:
                mask_len = int(mask_len_part.strip('/'))
            else:
                mask_len = int(current_subnet) if current_subnet else 32

            netmask = _int_to_netmask(mask_len)

            rest_of_line = line[m_route.end():].strip()
            next_hop = ""
            interface = ""
            if 'directly connected' in rest_of_line or 'is directly connected' in rest_of_line:
                next_hop = "directly connected"
                parts = [p.strip() for p in rest_of_line.replace('is directly connected', '').replace('directly connected', '').split(',')]
                for p in reversed(parts):
                    p_clean = p.replace('via', '').strip()
                    if p_clean and p_clean[0].isalpha():
                        interface = p_clean
                        break
            elif 'via' in rest_of_line:
                parts = [p.strip() for p in rest_of_line.split('via')[1].split(',')]
                if parts:
                    next_hop = parts[0]
                    if len(parts) > 1:
                        last_part = parts[-1]
                        if last_part and last_part[0].isalpha():
                            interface = last_part

            if next_hop:
                routes.append({
                    'prefix': dest,
                    'mask': netmask,
                    'next_hop': next_hop,
                    'protocol': proto,
                    'interface': interface,
                    'metric': 0
                })

                last_dest = dest
                last_mask = netmask
                last_proto = proto
                continue

        if last_dest:
            next_hop = ""
            interface = ""
            if 'directly connected' in line or 'is directly connected' in line:
                next_hop = "directly connected"
                parts = [p.strip() for p in line.replace('is directly connected', '').replace('directly connected', '').split(',')]
                for p in reversed(parts):
                    p_clean = p.replace('via', '').strip()
                    if p_clean and p_clean[0].isalpha():
                        interface = p_clean
                        break
            elif 'via' in line:
                parts = [p.strip() for p in line.split('via')[1].split(',')]
                if parts:
                    next_hop = parts[0]
                    if len(parts) > 1:
                        last_part = parts[-1]
                        if last_part and last_part[0].isalpha():
                            interface = last_part

            if next_hop:
                routes.append({
                    'prefix': last_dest,
                    'mask': last_mask,
                    'next_hop': next_hop,
                    'protocol': last_proto,
                    'interface': interface,
                    'metric': 0
                })
                continue
            elif line:
                # If we encounter a non-empty line that doesn't match a next-hop,
                # we have moved past the multi-path block. Clear state.
                last_dest = None
                last_mask = None
                last_proto = None

    return routes


def _collect_device_vrfs(dev: dict) -> list[str]:
    import re
    platform = str(dev.get('platform') or 'cisco_ios').lower()
    if platform in ('huawei_vrp', 'h3c_comware'):
        cmd = "display ip vpn-instance"
    elif platform in ('juniper_junos',):
        cmd = "show instance"
    else:
        cmd = "show ip vrf"
        
    vrfs = ['default']
    try:
        output = _send_command(dev, cmd)
        if not output or "Invalid input" in output or "Unrecognized command" in output:
            return vrfs
            
        for raw_line in output.splitlines():
            line_strip = raw_line.strip()
            if not line_strip:
                continue
            if platform not in ('huawei_vrp', 'h3c_comware', 'juniper_junos'):
                if any(h in line_strip.lower() for h in ('name', 'default rd', 'protocols', 'interfaces')):
                    continue
                tokens = line_strip.split()
                if tokens and tokens[0] not in ('Name', 'Default', 'Loopback', 'Vlan'):
                    vrf_name = tokens[0]
                    if vrf_name not in vrfs:
                        vrfs.append(vrf_name)
            elif platform in ('huawei_vrp', 'h3c_comware'):
                if any(h in line_strip.lower() for h in ('vpn-instance', 'total', 'configured')):
                    continue
                if "vpn-instance name" in line_strip.lower():
                    m = re.search(r'name\s+and\s+id\s*:\s*(\S+)', line_strip, re.IGNORECASE)
                    if m:
                        vrfs.append(m.group(1))
                else:
                    tokens = line_strip.split()
                    if tokens:
                        vrf_name = tokens[0]
                        if '(' in vrf_name:
                            vrf_name = vrf_name.split('(')[0]
                        if vrf_name not in vrfs:
                            vrfs.append(vrf_name)
            elif platform == 'juniper_junos':
                m = re.search(r'Instance:\s*(\S+),', line_strip, re.IGNORECASE)
                if m:
                    vrfs.append(m.group(1))
    except Exception as e:
        logger.debug(f"[Route Collector] Failed to collect VRFs from {dev.get('hostname')}: {e}")
        
    return vrfs


def run_route_collector():
    """
    后台路由事实库同步任务：
    1. 获取所有支持路由的在线设备。
    2. 并发连接，拉取 `show ip route` 路由表。
    3. 解析后批量写入 `route_cache` 表。
    """
    logger.info("[Route Collector] Starting route cache sync...")
    t0 = time.time()

    all_eligible = _load_eligible_devices()
    _L3_ROLES = {'router', 'gateway', 'core', 'dist', 'aggregation', 'l3switch'}
    route_devices = [
        d for d in all_eligible
        if (d.get('role') or '').lower().strip() in _L3_ROLES
    ]

    if not route_devices:
        logger.info("[Route Collector] No eligible L3 routing devices found.")
        return

    workers = min(5, len(route_devices))
    all_routes_to_save = []

    def collect_device_routes(dev: dict) -> list[dict]:
        ip = dev.get('ip_address')
        port = int(dev.get('port') or dev.get('management_port') or 22)
        from drivers.ssh_compat import is_ssh_port_open
        if not is_ssh_port_open(ip, port):
            logger.warning("[Route Collector] SSH port %s is closed/unreachable for %s", port, dev.get('hostname') or ip)
            return []

        platform = str(dev.get('platform') or 'cisco_ios').lower()
        vrfs = _collect_device_vrfs(dev)
        all_device_routes = []
        
        for vrf in vrfs:
            if vrf == 'default':
                if platform in ('huawei_vrp', 'h3c_comware'):
                    cmd = "display ip routing-table"
                elif platform in ('juniper_junos',):
                    cmd = "show route"
                else:
                    cmd = "show ip route"
            else:
                if platform in ('huawei_vrp', 'h3c_comware'):
                    cmd = f"display ip routing-table vpn-instance {vrf}"
                elif platform in ('juniper_junos',):
                    cmd = f"show route table {vrf}.inet.0"
                else:
                    cmd = f"show ip route vrf {vrf}"
                    
            try:
                output = _send_command(dev, cmd)
                parsed = parse_routing_table(output, platform)
                for r in parsed:
                    r['device_id'] = dev['id']
                    r['vrf_name'] = vrf
                all_device_routes.extend(parsed)
            except Exception as e:
                logger.debug(f"[Route Collector] Failed to collect routes for VRF {vrf} from {dev.get('hostname') or dev.get('ip_address')}: {e}")
                
        return all_device_routes

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(collect_device_routes, dev): dev for dev in route_devices}
        for future in as_completed(future_map):
            dev = future_map[future]
            try:
                device_routes = future.result()
                all_routes_to_save.extend(device_routes)
            except Exception as exc:
                logger.debug(f"[Route Collector] Error from {dev.get('ip_address')}: {exc}")

    if all_routes_to_save:
        try:
            conn = get_db_connection()
            try:
                conn.execute("DELETE FROM route_cache")
                conn.execute("DELETE FROM route_table")
                last_update = _beijing_now_iso()
                for r in all_routes_to_save:
                    vrf_val = r.get('vrf_name') or 'default'
                    rid = f"{r['device_id']}_{vrf_val}_{r['prefix']}_{r['mask']}_{r['next_hop']}_{r['interface']}"
                    conn.execute(
                        '''INSERT INTO route_cache (id, device_id, vrf_name, prefix, mask, next_hop, protocol, interface, metric, last_update)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (rid, r['device_id'], vrf_val, r['prefix'], r['mask'], r['next_hop'], r['protocol'], r['interface'], r['metric'], last_update)
                    )
                    
                    dest = r['prefix'] or ''
                    mask_val = r['mask'] or ''
                    if mask_val and '/' not in dest:
                        try:
                            if '.' in mask_val:
                                octets = [int(o) for o in mask_val.split('.')]
                                binary = ''.join(f'{o:08b}' for o in octets)
                                cidr = str(binary.count('1'))
                            else:
                                cidr = str(int(mask_val))
                            dest = f"{dest}/{cidr}"
                        except Exception:
                            dest = f"{dest}/24"
                    
                    pref_val = 1
                    proto_lower = (r.get('protocol') or '').lower()
                    if 'direct' in proto_lower or 'connect' in proto_lower:
                        pref_val = 0
                    elif 'static' in proto_lower:
                        pref_val = 1
                    elif 'ospf' in proto_lower:
                        pref_val = 110
                    elif 'bgp' in proto_lower:
                        pref_val = 200

                    conn.execute(
                        '''INSERT INTO route_table (
                            id, device_id, vrf_name, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
                        (rid, r['device_id'], vrf_val, dest, r['next_hop'], r['interface'], r['protocol'], r['metric'], pref_val, last_update)
                    )
                conn.commit()
                logger.info(f"[Route Collector] Successfully synced {len(all_routes_to_save)} routes to route_cache and route_table.")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[Route Collector] Error writing routes: {e}")

    elapsed = round(time.time() - t0, 1)
    logger.info(f"[Route Collector] Finished route cache sync in {elapsed}s.")


async def run_route_collector_async():
    await asyncio.to_thread(run_route_collector)
