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
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime, timezone, timedelta
from typing import Any

from netmiko import ConnectHandler

from database import get_db_connection, _SERIAL_PK
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
    conn = get_db_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS arp_cache (
                target_ip   TEXT PRIMARY KEY,
                mac         TEXT NOT NULL,
                arp_source  TEXT NOT NULL DEFAULT '{}',
                cached_at   TEXT NOT NULL,
                expires_at  REAL NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_arp_cache_expires ON arp_cache(expires_at)')
        # MAC 变更日志表
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS mac_change_log (
                id          {_SERIAL_PK},
                ip          TEXT NOT NULL,
                old_mac     TEXT NOT NULL,
                new_mac     TEXT NOT NULL,
                old_vendor  TEXT NOT NULL DEFAULT '',
                new_vendor  TEXT NOT NULL DEFAULT '',
                old_device  TEXT NOT NULL DEFAULT '',
                new_device  TEXT NOT NULL DEFAULT '',
                detected_at TEXT NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_mac_change_ip ON mac_change_log(ip)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_mac_change_time ON mac_change_log(detected_at DESC)')
        conn.commit()
    finally:
        conn.close()

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
        'port': int(device_info.get('port') or 22),
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


def locate_ip(target_ip: str, force_refresh: bool = False) -> dict[str, Any]:
    """
    核心定位逻辑：IP → MAC（ARP） → Port（MAC表） → Uplink（LLDP）

    性能策略：
    - 设备端精确过滤：发送 "show ip arp <ip>" 而非 "show arp"（数据量从万级→1条）
    - 并发 SSH：ThreadPoolExecutor 并行查询多台设备
    - 早期终止：ARP 阶段找到目标后立即取消剩余设备查询
    - 单次设备列表加载：避免重复查库
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

    # ── Step 2: 并发 MAC 地址表查询（仅交换机，路由器无二层 MAC 表）──
    # 白名单：只查已知具备 MAC 地址表的设备角色
    _SWITCH_ROLES = frozenset({'switch', 'access', 'distribution', 'core', 'aggregation', 'l2', 'l3switch'})
    # 如果 role 字段为空或不在白名单，也允许查询（兼容未填 role 的设备）
    # 明确排除路由器和防火墙
    _MAC_EXCLUDED_ROLES = frozenset({'router', 'firewall', 'gateway', 'server', 'linux', 'windows'})
    switch_devices = [
        d for d in all_eligible
        if (d.get('role') or '').lower().strip() not in _MAC_EXCLUDED_ROLES
    ]

    mac_matches: list[dict] = []

    workers = _calc_ssh_workers(len(switch_devices))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map_mac: dict[Future, dict] = {}
        for dev in switch_devices:
            f = executor.submit(_targeted_mac_query, dev, target_mac)
            future_map_mac[f] = dev

        for future in as_completed(future_map_mac):
            dev = future_map_mac[future]
            dev_label = dev.get('hostname') or dev.get('ip_address')
            result['searched_devices']['mac'].append(dev_label)

            try:
                device_mac_records = future.result()
            except Exception as exc:
                logger.debug(f"[IPLocator] MAC future error for {dev_label}: {exc}")
                continue

            for rec in device_mac_records:
                port_lower = rec['port'].lower()
                is_uplink = any(kw in port_lower for kw in ('po', 'port-channel', 'lag', 'eth-trunk'))
                rec['is_uplink'] = is_uplink
                mac_matches.append(rec)

    # ── Step 2.5: MAC 表未命中时，利用 ARP 源信息回退 ──
    if not mac_matches and arp_source_info:
        mac_matches.append({
            'switch_id': arp_source_info.get('device_id'),
            'switch_name': arp_source_info.get('device'),
            'port': arp_source_info.get('interface') or 'N/A',
            'vlan': '',
            'type': 'ARP_DIRECT',
            'is_uplink': False,
            'note': '该 MAC 未在交换机 MAC 表中发现，可能是直连网关/路由器接口，定位基于 ARP 记录',
        })

    # ── Step 3: 用 LLDP 补充上联信息 ──
    for match in mac_matches:
        if match.get('type') == 'ARP_DIRECT':
            continue
        switch_id = match.get('switch_id')
        dev_dict = next((d for d in switch_devices if d.get('id') == switch_id), None)
        if not dev_dict:
            continue

        dev_label = dev_dict.get('hostname') or dev_dict.get('ip_address')
        if dev_label not in result['searched_devices']['lldp']:
            result['searched_devices']['lldp'].append(dev_label)

        lldp_records = _collect_lldp_from_device(dev_dict)
        for lrec in lldp_records:
            if lrec['local_interface'].lower() == match['port'].lower():
                match['uplink_neighbor'] = lrec['neighbor']
                match['uplink_port'] = lrec['neighbor_port']
                break

    # 优先返回非上联口的结果
    mac_matches.sort(key=lambda m: (m.get('is_uplink', False), m.get('type', '') == 'STATIC'))

    result['found'] = len(mac_matches) > 0
    result['locations'] = mac_matches
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
