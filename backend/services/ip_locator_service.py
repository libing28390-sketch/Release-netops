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
import os
import re
import threading
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from datetime import datetime, timezone, timedelta
from typing import Any

from netmiko import ConnectHandler, NetmikoAuthenticationException

from database import get_db_connection, _SERIAL_PK, _USE_PG, init_db
from core.crypto import decrypt_credential
from services.vault_service import resolve_device_credentials
from services.network_access_limiter import limited_connect_handler
from drivers.ssh_compat import build_netmiko_compatibility_kwargs
from core.interface_utils import normalize_interface_name as normalize_canonical_interface_name
from services.operational_data_service import (
    collect_operational_data,
    ROLE_EXCLUDED_CATEGORIES,
    PLATFORM_DEVICE_TYPE_MAP,
)
from services.oui_lookup import lookup_vendor
from core.cmd_cache import get_cached_command, set_cached_command
from services.collection_plan_service import (
    explicit_collector_override,
    filter_devices,
    should_collect,
)
from services.collection_status_service import record_collection_results
from services.collector_sweep_state_service import (
    complete_collector_sweep,
    reserve_collector_sweep_batch,
)
from services.collector_task_queue_service import enqueue_tasks
from services.vlan_discovery_service import parse_vlan_id_from_interface

# 并发 SSH 连接上限，避免瞬间打开过多连接
# 小规模 (≤10 台) 取 5；中规模动态扩展到 10；大规模上限 15
MAX_SSH_WORKERS_MIN = 5
MAX_SSH_WORKERS_MAX = 15

def normalize_interface_name(name: str) -> str:
    """Use the shared vendor-neutral interface key for locator joins."""
    return normalize_canonical_interface_name(name)


def _calc_ssh_workers(device_count: int) -> int:
    """根据设备数量动态计算并发 SSH worker 数。"""
    if device_count <= 10:
        return min(MAX_SSH_WORKERS_MIN, device_count)
    return min(MAX_SSH_WORKERS_MAX, max(MAX_SSH_WORKERS_MIN, device_count // 3))

# ARP 缓存：按 target_ip 懒加载，不做全网全量预采集
# 二级缓存架构：L1 = 进程内 dict（热数据快速命中）, L2 = 配置数据库（持久化跨重启）
# 采集间隔 5 分钟，TTL 10 分钟，保证在下次采集到来前始终有有效缓存
ARP_SWEEP_INTERVAL_SECONDS = 300   # 后台全量采集间隔：5 分钟
ARP_CACHE_TTL_SECONDS = 600        # 缓存有效期：10 分钟（2 倍采集间隔，保证覆盖）
ARP_CACHE_MAX_ENTRIES = 5000
ENDPOINT_CACHE_TTL_SECONDS = 600
ARP_SWEEP_INTERVAL_SECONDS = max(300, int(os.environ.get('ARP_SWEEP_INTERVAL_SECONDS', '600')))
ARP_CACHE_TTL_SECONDS = max(ARP_SWEEP_INTERVAL_SECONDS * 2, 600)
ENDPOINT_FACT_INTERVAL_SECONDS = max(900, int(os.environ.get('ENDPOINT_FACT_INTERVAL_SECONDS', '1800')))
ROUTE_SWEEP_INTERVAL_SECONDS = max(300, int(os.environ.get('ROUTE_SWEEP_INTERVAL_SECONDS', '300')))
ARP_MAX_DEVICES_PER_SWEEP = max(0, int(os.environ.get('ARP_MAX_DEVICES_PER_SWEEP', '500')))

_ARP_L3_ROLES = frozenset({
    'router', 'gateway', 'core', 'dist', 'distribution',
    'aggregation', 'l3switch', 'firewall', 'load-balancer',
})
_ARP_SVI_ROLES = frozenset({'access', 'switch', 'dist', 'distribution', 'aggregation', 'l3switch'})
_ARP_RETRY_BASE_SECONDS = 300
_ARP_RETRY_MAX_SECONDS = 3600
_ARP_AUTH_RETRY_SECONDS = 3600
_ARP_UNSUPPORTED_RETRY_SECONDS = 86400
_ARP_CIRCUIT_OPEN_AFTER = 5

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


def _record_value(record: dict[str, Any], *names: str) -> Any:
    """Read a parsed CLI field regardless of parser casing/alias conventions."""
    if not isinstance(record, dict):
        return ''
    by_lower_name = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        value = record.get(name, by_lower_name.get(name.lower(), ''))
        if value not in (None, ''):
            if isinstance(value, (list, tuple)):
                return value[0] if value else ''
            return value
    return ''


def _normalize_arp_record(record: dict[str, Any], device_info: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize NTC/TextFSM and vendor fallback records into one ARP shape."""
    ip_raw = _record_value(record, 'ip', 'ip_address', 'address', 'ipaddr', 'ip_addr')
    mac_raw = _record_value(
        record,
        'mac', 'mac_address', 'hardware_address', 'destination_address',
        'hardware', 'lladdr',
    )
    try:
        ip_addr = str(ip_raw or '').strip()
        parsed_ip = ipaddress.ip_address(ip_addr)
        if parsed_ip.version != 4:
            return None
    except ValueError:
        return None

    mac_norm = _normalize_mac(str(mac_raw or ''))
    if not mac_norm:
        return None

    interface = _record_value(
        record, 'interface', 'intf', 'port', 'local_interface',
        'destination_port',
    )
    normalized = {
        'ip': ip_addr,
        'mac': mac_norm,
        'interface': str(interface or '').strip(),
        'source_device_id': device_info.get('id'),
        'source_device': device_info.get('hostname') or device_info.get('ip_address'),
    }
    vlan_raw = _record_value(record, 'vlan_id', 'vlan', 'vid', 'vlanid')
    try:
        vlan_id = int(str(vlan_raw).strip())
        if 1 <= vlan_id <= 4094:
            normalized['vlan'] = str(vlan_id)
            normalized['vlan_source'] = 'arp_vid'
    except (TypeError, ValueError):
        interface_vlan = parse_vlan_id_from_interface(normalized['interface'])
        if interface_vlan:
            normalized['vlan'] = str(interface_vlan)
            normalized['vlan_source'] = 'arp_interface'
    return normalized


_ARP_OUTPUT_MAC_RE = re.compile(
    r'(?i)(?:[0-9a-f]{4}[.:-]){2}[0-9a-f]{4}|'
    r'(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|'
    r'(?<![0-9a-f])[0-9a-f]{12}(?![0-9a-f])'
)
_ARP_OUTPUT_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_ARP_INTERFACE_RE = re.compile(
    r'(?i)^(?:[a-z][a-z0-9-]*(?:[/.:][a-z0-9-]+)+|'
    r'(?:vlan|vlanif|loopback|lo|bvi|bridge)\d+)$'
)


def _parse_arp_output_fallback(output: str, device_info: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse common Cisco/Huawei/H3C ARP rows when TextFSM has no match."""
    records: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None

    def flush_pending() -> None:
        nonlocal pending
        if pending is None:
            return
        record = _normalize_arp_record(pending, device_info)
        if record:
            records.append(record)
        pending = None

    for raw_line in str(output or '').splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if pending and re.fullmatch(r'\d{1,4}', line):
            vlan_id = int(line)
            if 1 <= vlan_id <= 4094:
                pending['vlan'] = line
                flush_pending()
                continue

        ip_match = _ARP_OUTPUT_IP_RE.search(line)
        mac_match = _ARP_OUTPUT_MAC_RE.search(line)
        if not ip_match or not mac_match:
            if pending and (line.startswith('Total:') or line.startswith('-')):
                flush_pending()
            continue

        flush_pending()
        suffix_tokens = line[mac_match.end():].split()
        interface = ''
        interface_index = -1
        for index, token in enumerate(suffix_tokens):
            candidate = token.strip('(),[]')
            if _ARP_INTERFACE_RE.match(candidate):
                interface = candidate
                interface_index = index
                break
        vlan = ''
        # H3C/Huawei commonly output: IP MAC VID Interface. Cisco ARP rows
        # have ARPA/age fields here, so only accept the adjacent numeric VID.
        if interface_index > 0:
            candidate_vlan = suffix_tokens[interface_index - 1].strip('(),[]')
            if candidate_vlan.isdigit() and 1 <= int(candidate_vlan) <= 4094:
                vlan = candidate_vlan
        pending = {
            'ip': ip_match.group(0),
            'mac': mac_match.group(0),
            'interface': interface,
            'vlan': vlan,
        }
    flush_pending()
    return records


def _format_mac(mac12: str) -> str:
    """将 12 位 hex 格式化为 xxxx.xxxx.xxxx（Cisco 风格）方便阅读。"""
    if len(mac12) != 12:
        return mac12
    return f'{mac12[0:4]}-{mac12[4:8]}-{mac12[8:12]}'


def _parse_vlan_id(value: Any) -> int | None:
    try:
        vlan_id = int(str(value or '').strip())
    except (TypeError, ValueError):
        return None
    return vlan_id if 1 <= vlan_id <= 4094 else None


_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).replace(microsecond=0).isoformat()


def _age_seconds(value: Any) -> int | None:
    if not value:
        return None
    try:
        observed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=_BEIJING_TZ)
        return max(0, int((datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


# ── ARP 持久化缓存（数据库 L2 + 内存 L1） ──────────────────────────

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
    """L1 内存 → L2 配置数据库二级查找。"""
    now_ts = time.time()

    # L1: 内存热缓存
    with _ARP_CACHE_LOCK:
        _prune_memory_cache(now_ts)
        mem = _ARP_CACHE.get(target_ip)
        if mem:
            return dict(mem)

    # L2: 配置数据库持久缓存
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT mac, vlan_id, arp_source, cached_at, expires_at FROM arp_cache WHERE target_ip = ? AND expires_at > ?',
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
        'vlan': str(row['vlan_id']) if row['vlan_id'] else '',
        'arp_source': _json.loads(row['arp_source'] or '{}'),
        'cached_at': row['cached_at'],
        'created_at_epoch': now_ts,
        'expires_at': row['expires_at'],
    }
    with _ARP_CACHE_LOCK:
        _ARP_CACHE[target_ip] = entry

    return dict(entry)


def _set_cached_arp(target_ip: str, mac: str, arp_source: dict[str, Any] | None):
    """同时写入 L1 内存 + L2 配置数据库。"""
    now_ts = time.time()
    cached_at = _beijing_now_iso()
    expires_at = now_ts + ARP_CACHE_TTL_SECONDS
    source_dict = dict(arp_source or {})
    explicit_vlan_id = _parse_vlan_id(source_dict.get('vlan'))
    vlan_id = explicit_vlan_id or parse_vlan_id_from_interface(source_dict.get('interface'))
    if vlan_id is not None:
        source_dict['vlan'] = str(vlan_id)
        source_dict.setdefault('vlan_source', 'arp_vid' if explicit_vlan_id else 'arp_interface')

    # L1 写入
    entry = {
        'target_ip': target_ip,
        'mac': mac,
        'vlan': str(vlan_id) if vlan_id is not None else '',
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
                '''INSERT INTO arp_cache (target_ip, mac, vlan_id, arp_source, cached_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(target_ip) DO UPDATE SET
                       mac = excluded.mac,
                       vlan_id = excluded.vlan_id,
                       arp_source = excluded.arp_source,
                       cached_at = excluded.cached_at,
                       expires_at = excluded.expires_at''',
                (target_ip, mac, vlan_id, _json.dumps(source_dict), cached_at, expires_at),
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
                    '''INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (str(uuid.uuid4()), dev_id, target_ip, mac, source_dict.get('interface') or '', vlan_id, cached_at)
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
        # Match Playbooks: use the normal account first, then an admin fallback
        # for dual-auth devices whose normal account is unavailable.
        credential_attempts = _credential_attempts(creds, auth_model)
        if not credential_attempts:
            continue
        if role_filter:
            dev_role = (d.get('role') or '').lower().strip()
            if dev_role not in role_filter:
                continue
        # 把解析好的登录凭据写回 dict，供 _build_ssh_params 直接使用
        d['_ssh_username'], d['_ssh_password'] = credential_attempts[0]
        d['_ssh_fallback_credentials'] = credential_attempts[1:]
        d['_ssh_enable'] = creds.get('enable_password') or ''
        devices.append(d)
    return devices


def _credential_attempts(creds: dict[str, str], auth_model: str) -> list[tuple[str, str]]:
    """Return ordered SSH credential pairs for a collector connection."""
    pairs = [
        (creds.get('normal_username') or '', creds.get('normal_password') or ''),
    ]
    if auth_model == 'dual':
        pairs.append((creds.get('admin_username') or '', creds.get('admin_password') or ''))

    attempts: list[tuple[str, str]] = []
    for pair in pairs:
        if not all(pair) or pair in attempts:
            continue
        attempts.append(pair)
    return attempts


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


def _send_command(device_info: dict, command: str, force_refresh: bool = False) -> str:
    """SSH 到设备执行单条命令并返回原始输出。

    诊断流程可显式跳过命令缓存；普通定位流程继续使用缓存，避免把
    常规 IP 定位的性能优化误用到实时故障结论上。
    """
    device_ip = device_info.get('ip_address') or device_info.get('hostname') or 'unknown'
    if not force_refresh:
        cached = get_cached_command(device_ip, command)
        if cached is not None:
            return cached

    port = int(device_info.get('port') or device_info.get('management_port') or 22)
    from drivers.ssh_compat import is_ssh_port_open
    if not is_ssh_port_open(device_ip, port):
        logger.warning("SSH port %s is closed/unreachable for %s", port, device_ip)
        return ""

    credential_attempts = [
        (device_info.get('_ssh_username') or device_info.get('username') or '',
         device_info.get('_ssh_password') or device_info.get('password') or ''),
        *(device_info.get('_ssh_fallback_credentials') or []),
    ]
    credential_attempts = [pair for pair in credential_attempts if all(pair)]
    last_auth_error = None

    for attempt_index, (username, password) in enumerate(credential_attempts):
        attempt_device = dict(device_info)
        attempt_device['_ssh_username'] = username
        attempt_device['_ssh_password'] = password
        conn_params = _build_ssh_params(attempt_device)
        try:
            with limited_connect_handler(attempt_device, ConnectHandler, **conn_params) as client:
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
                if not force_refresh:
                    set_cached_command(device_ip, command, output)
                return output
        except NetmikoAuthenticationException as exc:
            last_auth_error = exc
            if attempt_index + 1 < len(credential_attempts):
                logger.warning(
                    "Normal SSH authentication failed for %s; retrying with configured fallback",
                    device_ip,
                )
                continue
            raise

    if last_auth_error:
        raise last_auth_error
    return ""


# ── 精确 ARP 查询 ─────────────────────────────────────

def _targeted_arp_query(device_info: dict, target_ip: str, vrf: str = None) -> dict | None:
    """
    向设备发送精确 ARP 查询命令，仅返回目标 IP 的记录。
    数据量：1 条记录 vs 全表可能上万条。
    支持可选的 vrf 参数，用于在特定的 VRF 虚拟路由上下文中查询 ARP 表。
    失败时回退到全表采集。
    """
    # Registry-bound devices use the published standard action and filter the
    # normalized records locally.  This keeps the locator out of the
    # vendor-specific command and pipe syntax while preserving the legacy
    # targeted-query fallback for unbound/older assets.
    if device_info.get('platform_profile_id'):
        try:
            from services.platform_registry_service import execute_platform_action

            result = execute_platform_action(
                str(device_info['id']),
                'get_arp_table_vrf' if vrf else 'get_arp_table',
                user={
                    'id': f'ip-locator:{device_info.get("id") or "unknown"}',
                    'username': 'ip-locator',
                    'role': 'Operator',
                    'tenant_id': device_info.get('tenant_id') or '',
                },
                parameters={'vrf': vrf} if vrf else None,
            )
            if result.get('success'):
                for record in result.get('records') or []:
                    normalized = _normalize_arp_record(record, device_info)
                    if normalized and normalized['ip'] == target_ip:
                        return {
                            'ip': target_ip,
                            'mac': normalized['mac'],
                            'mac_display': _format_mac(normalized['mac']),
                            'interface': normalized['interface'],
                            'vlan': normalized.get('vlan', ''),
                            'source_device_id': normalized['source_device_id'],
                            'source_device': normalized['source_device'],
                        }
                return None
        except Exception as exc:
            logger.debug(f"[IPLocator] Registry ARP query failed on {device_info.get('ip_address')}: {exc}")
        # A registry-bound device must not fall back to a vendor-specific
        # targeted command.  Unsupported/failed published actions are an
        # explicit result, not permission to bypass the release boundary.
        return None

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
            for normalized in _parse_arp_output_fallback(output, device_info):
                if normalized['ip'] == target_ip:
                    return {
                        'ip': target_ip,
                        'mac': normalized['mac'],
                        'mac_display': _format_mac(normalized['mac']),
                        'interface': normalized['interface'],
                        'vlan': normalized.get('vlan', ''),
                        'source_device_id': normalized['source_device_id'],
                        'source_device': normalized['source_device'],
                    }
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
                normalized = _normalize_arp_record(rec, device_info)
                if not normalized:
                    continue
                ip_addr = normalized['ip']
                if ip_addr != target_ip:
                    continue
                return {
                    'ip': target_ip,
                    'mac': normalized['mac'],
                    'mac_display': _format_mac(normalized['mac']),
                    'interface': normalized['interface'],
                    'vlan': normalized.get('vlan', ''),
                    'source_device_id': normalized['source_device_id'],
                    'source_device': normalized['source_device'],
                }

            # TextFSM is preferred, but a vendor output variant must not make
            # an otherwise valid ARP row disappear from the locator.
            for raw_output in cat.get('raw_outputs') or []:
                for normalized in _parse_arp_output_fallback(raw_output.get('output', ''), device_info):
                    if normalized['ip'] == target_ip:
                        return {
                            'ip': target_ip,
                            'mac': normalized['mac'],
                            'mac_display': _format_mac(normalized['mac']),
                            'interface': normalized['interface'],
                            'vlan': normalized.get('vlan', ''),
                            'source_device_id': normalized['source_device_id'],
                            'source_device': normalized['source_device'],
                        }
    return None


# ── 精确 MAC 查询 ─────────────────────────────────────

def _targeted_mac_query(device_info: dict, target_mac: str) -> list[dict]:
    """
    向设备发送精确 MAC 地址表查询命令。
    target_mac 为 12 位 hex（无分隔符），函数内部转为设备所需格式。
    """
    # A router may be the ARP source for an endpoint but still have no L2
    # forwarding table.  Respect the device collection plan before falling
    # through to a registry action; an explicit per-device override remains
    # available for platforms that do expose a bridge table.
    if not should_collect(device_info, "mac_table"):
        logger.debug(
            "[IPLocator] Skip MAC lookup for %s: mac_table is disabled by the device collection plan",
            device_info.get("hostname") or device_info.get("id"),
        )
        return []
    if device_info.get('platform_profile_id'):
        try:
            from services.platform_registry_service import execute_platform_action

            result = execute_platform_action(
                str(device_info['id']),
                'get_mac_table',
                user={
                    'id': f'ip-locator:{device_info.get("id") or "unknown"}',
                    'username': 'ip-locator',
                    'role': 'Operator',
                    'tenant_id': device_info.get('tenant_id') or '',
                },
            )
            if result.get('success'):
                records = []
                for record in result.get('records') or []:
                    mac_norm = _normalize_mac(str(_record_value(
                        record, 'mac', 'mac_address', 'destination_address', 'hardware_address'
                    ) or ''))
                    if mac_norm != target_mac:
                        continue
                    port_field = _record_value(record, 'interface', 'destination_port', 'port')
                    vlan = _record_value(record, 'vlan', 'vlan_id', 'vid')
                    records.append({
                        'mac': mac_norm,
                        'port': str(port_field or '').strip(),
                        'vlan': str(vlan or '').strip(),
                        'vlan_source': 'mac_table',
                        'type': _record_value(record, 'type', 'entry_type'),
                        'switch_id': device_info.get('id'),
                        'switch_name': device_info.get('hostname') or device_info.get('ip_address'),
                    })
                return records
        except Exception as exc:
            logger.debug(f"[IPLocator] Registry MAC query failed on {device_info.get('ip_address')}: {exc}")
        return []

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
            'vlan_source': 'mac_table',
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
                        'vlan_source': 'mac_table',
                        'type': rec.get('type', ''),
                        'switch_id': device_info.get('id'),
                        'switch_name': device_info.get('hostname') or device_info.get('ip_address'),
                    })
    return records


def _collect_lldp_from_device(device_info: dict) -> list[dict]:
    """Collect LLDP neighbor evidence from one device."""
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

    if device_info.get('platform_profile_id') and not vrf:
        try:
            from services.platform_registry_service import execute_platform_action

            result = execute_platform_action(
                str(device_info['id']),
                'get_ip_interfaces',
                user={
                    'id': f"ip-locator:{device_info.get('id') or 'unknown'}",
                    'username': 'ip-locator',
                    'role': 'Operator',
                    'tenant_id': device_info.get('tenant_id') or '',
                },
            )
            if result.get('success'):
                for record in result.get('records') or []:
                    ip_value = str(record.get('ip_address') or record.get('ip') or '').strip()
                    if target_ip == ip_value or target_ip in ip_value.split('/')[:1]:
                        intf_name = str(record.get('interface') or record.get('local_interface') or '').strip()
                        if intf_name:
                            return {
                                'ip': target_ip,
                                'interface': intf_name,
                                'device_id': device_info.get('id'),
                                'device_name': device_info.get('hostname') or device_info.get('ip_address'),
                            }
                return None
        except Exception as exc:
            logger.debug(f"[IPLocator] Registry local IP query failed on {device_info.get('ip_address')}: {exc}")
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


def _get_ip_locator_context(target_ip: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate existing IPAM, endpoint, interface and route facts for one IP."""
    context: dict[str, Any] = {
        'address': {
            'ip': target_ip, 'type': 'unknown', 'prefix': '', 'prefix_length': None,
            'netmask': '', 'network_type': '', 'purpose': '', 'status': '', 'last_seen': '',
        },
        'l2': {
            'mac': '', 'vlan': '', 'vlan_name': '', 'vlan_source': 'unknown',
            'switch_id': '', 'switch_name': '', 'port': '', 'description': '',
            'admin_status': '', 'oper_status': '', 'mode': '', 'native_vlan': '',
            'allowed_vlans': '', 'last_seen': '',
        },
        'l3': {
            'gateway': '', 'gateway_device': '', 'gateway_interface': '', 'vrf': '',
            'next_hop': '', 'route_source': '', 'route_interface': '', 'route_last_updated': '',
            'upstream_devices': [], 'downstream_devices': [], 'adjacent_devices': [],
        },
        'business': {
            'hostname': '', 'asset_type': '', 'department': '', 'tenant': '', 'site': '',
            'owner': '', 'criticality': '', 'description': '', 'config_backup_at': '',
            'business_systems': [], 'business_level': '',
            'open_alerts': [],
        },
        'freshness': {
            'endpoint_last_seen': '', 'arp_last_updated': '', 'mac_last_updated': '',
            'interface_last_seen': '', 'collected_at': _beijing_now_iso(),
        },
        'path': [],
    }

    def set_if_empty(target: dict[str, Any], key: str, value: Any) -> None:
        if target.get(key) in (None, '', 'unknown') and value not in (None, ''):
            target[key] = value

    try:
        ip_obj = ipaddress.ip_address(target_ip)
    except ValueError:
        ip_obj = None

    try:
        conn = get_db_connection()
        try:
            prefix_rows = conn.execute(
                '''SELECT p.id, p.prefix, p.name, p.network_type, p.gateway, p.vlan_id,
                          p.vrf_id, p.site_id, p.tenant_id, p.gateway_device_id,
                          p.gateway_interface_id, p.description,
                          vl.vlan_id AS vlan_number, vl.name AS vlan_name,
                          v.vrf_name, s.site_name, t.name AS tenant_name,
                          gd.hostname AS gateway_device_name,
                          gi.interface_name AS gateway_interface_name
                   FROM prefixes p
                   LEFT JOIN vlans vl ON p.vlan_id = vl.id
                   LEFT JOIN vrfs v ON p.vrf_id = v.id
                   LEFT JOIN sites s ON p.site_id = s.id
                   LEFT JOIN tenants t ON p.tenant_id = t.id
                   LEFT JOIN devices gd ON p.gateway_device_id = gd.id
                   LEFT JOIN interfaces gi ON p.gateway_interface_id = gi.id'''
            ).fetchall()

            best_prefix = None
            best_prefix_len = -1
            if ip_obj:
                for row in prefix_rows:
                    try:
                        network = ipaddress.ip_network(row['prefix'], strict=False)
                    except (ValueError, TypeError, KeyError):
                        continue
                    if network.version == ip_obj.version and ip_obj in network and network.prefixlen > best_prefix_len:
                        best_prefix = row
                        best_prefix_len = network.prefixlen

            if best_prefix:
                network = ipaddress.ip_network(best_prefix['prefix'], strict=False)
                context['address'].update({
                    'type': best_prefix['network_type'] or 'server',
                    'prefix': best_prefix['prefix'] or '',
                    'prefix_length': network.prefixlen,
                    'netmask': str(network.netmask),
                    'network_type': best_prefix['network_type'] or '',
                    'purpose': best_prefix['name'] or best_prefix['description'] or '',
                })
                context['l3'].update({
                    'gateway': best_prefix['gateway'] or '',
                    'gateway_device': best_prefix['gateway_device_name'] or best_prefix['gateway_device_id'] or '',
                    'gateway_interface': best_prefix['gateway_interface_name'] or best_prefix['gateway_interface_id'] or '',
                    'vrf': best_prefix['vrf_name'] or best_prefix['vrf_id'] or '',
                })
                context['business'].update({
                    'tenant': best_prefix['tenant_name'] or best_prefix['tenant_id'] or '',
                    'site': best_prefix['site_name'] or best_prefix['site_id'] or '',
                })
                if best_prefix['vlan_number']:
                    context['l2'].update({
                        'vlan': str(best_prefix['vlan_number']),
                        'vlan_name': best_prefix['vlan_name'] or '',
                        'vlan_source': 'ipam_prefix',
                    })
                elif best_prefix['vlan_id']:
                    prefix_vlan = _parse_vlan_id(best_prefix['vlan_id'])
                    if prefix_vlan:
                        context['l2'].update({
                            'vlan': str(prefix_vlan),
                            'vlan_source': 'ipam_prefix_id',
                        })

            ip_row = conn.execute(
                '''SELECT ip.address, ip.hostname, ip.mac_address, ip.device_id,
                          ip.interface_name, ip.device_type, ip.status, ip.description,
                          ip.last_seen
                   FROM ip_addresses ip
                   WHERE ip.address = ? OR ip.ip_address = ?
                   ORDER BY CASE WHEN ip.address = ? THEN 0 ELSE 1 END LIMIT 1''',
                (target_ip, target_ip, target_ip),
            ).fetchone()
            if ip_row:
                context['address']['status'] = ip_row['status'] or ''
                context['address']['last_seen'] = ip_row['last_seen'] or ''
                set_if_empty(context['address'], 'type', ip_row['device_type'])
                set_if_empty(context['business'], 'hostname', ip_row['hostname'])
                set_if_empty(context['business'], 'description', ip_row['description'])
                set_if_empty(context['l2'], 'mac', ip_row['mac_address'])

            endpoint = conn.execute(
                '''SELECT ne.ip, ne.mac, ne.hostname, ne.asset_type, ne.switch_id,
                          ne.switch_port, ne.vlan, ne.vrf, ne.site, ne.source_type,
                           ne.last_seen, d.hostname AS switch_name, d.owner_team,
                           d.criticality, d.site_id AS device_site_id,
                           COALESCE(s.site_name, s.site_code, d.site) AS device_site
                   FROM network_endpoints ne
                   LEFT JOIN devices d ON d.id = ne.switch_id
                   LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, ''))
                   WHERE ne.ip = ? AND ne.is_active = 1
                   ORDER BY ne.last_seen DESC LIMIT 1''',
                (target_ip,),
            ).fetchone()

            location = None
            if result:
                location = next((item for item in (result.get('locations') or []) if not item.get('is_uplink')), None)

            l2 = context['l2']
            if endpoint:
                l2.update({
                    'mac': endpoint['mac'] or l2['mac'],
                    'vlan': endpoint['vlan'] or l2['vlan'],
                    'vlan_source': endpoint['source_type'] or l2['vlan_source'],
                    'switch_id': endpoint['switch_id'] or '',
                    'switch_name': endpoint['switch_name'] or endpoint['switch_id'] or '',
                    'port': endpoint['switch_port'] or '',
                })
                context['freshness']['endpoint_last_seen'] = endpoint['last_seen'] or ''
                set_if_empty(context['business'], 'hostname', endpoint['hostname'])
                set_if_empty(context['business'], 'asset_type', endpoint['asset_type'])
                set_if_empty(context['business'], 'owner', endpoint['owner_team'])
                set_if_empty(context['business'], 'criticality', endpoint['criticality'])
                set_if_empty(context['business'], 'site', endpoint['device_site'] or endpoint['site'])
                set_if_empty(context['l3'], 'vrf', endpoint['vrf'])
            elif location:
                l2.update({
                    'switch_id': str(location.get('switch_id') or ''),
                    'switch_name': location.get('switch_name') or '',
                    'port': location.get('port') or '',
                    'vlan': location.get('vlan') or l2['vlan'],
                    'vlan_source': location.get('vlan_source') or l2['vlan_source'],
                })

            arp_row = conn.execute(
                '''SELECT a.mac_address, a.vlan_id, a.interface_name, a.last_updated,
                          d.hostname AS device_name, a.device_id
                   FROM arp_table a
                   LEFT JOIN devices d ON d.id = a.device_id
                   WHERE a.ip_address = ?
                   ORDER BY a.last_updated DESC LIMIT 1''',
                (target_ip,),
            ).fetchone()
            if arp_row:
                arp_interface_vlan = parse_vlan_id_from_interface(arp_row['interface_name'])
                arp_vlan = str(arp_row['vlan_id'] or arp_interface_vlan or '')
                # network_endpoints is a derived, IP-keyed cache.  If its row
                # has no VLAN/L2 evidence, prefer the latest ARP observation
                # instead of retaining a stale device/port chosen by a prior
                # tracker run.
                prefer_arp_location = bool(
                    arp_row['interface_name']
                    and arp_vlan
                    and (
                        not endpoint
                        or not endpoint['vlan']
                        or not endpoint['switch_id']
                        or not endpoint['switch_port']
                    )
                )
                if prefer_arp_location:
                    l2.update({
                        'mac': arp_row['mac_address'] or l2['mac'],
                        'switch_id': arp_row['device_id'] or l2['switch_id'],
                        'switch_name': arp_row['device_name'] or arp_row['device_id'] or l2['switch_name'],
                        'port': arp_row['interface_name'] or l2['port'],
                        'vlan': arp_vlan,
                        'vlan_source': 'arp_table' if arp_row['vlan_id'] else 'arp_interface',
                    })
                else:
                    set_if_empty(l2, 'mac', arp_row['mac_address'])
                    if not l2['vlan'] and arp_vlan:
                        l2['vlan'] = arp_vlan
                        l2['vlan_source'] = 'arp_table' if arp_row['vlan_id'] else 'arp_interface'
                context['freshness']['arp_last_updated'] = arp_row['last_updated'] or ''
                if not l2['switch_name']:
                    l2['switch_name'] = arp_row['device_name'] or arp_row['device_id'] or ''
                if not l2['port']:
                    l2['port'] = arp_row['interface_name'] or ''

            if result and result.get('mac'):
                set_if_empty(l2, 'mac', _format_mac(result['mac']))

            switch_id = l2.get('switch_id') or ''
            port = l2.get('port') or ''
            if switch_id and port:
                interface_rows = conn.execute(
                    '''SELECT i.interface_name, i.description, i.admin_status, i.oper_status,
                              i.switchport_mode, i.access_vlan, i.native_vlan, i.allowed_vlans,
                              i.last_seen, v.vrf_name
                       FROM interfaces i
                       LEFT JOIN vrfs v ON v.id = i.vrf_id
                       WHERE i.device_id = ?''',
                    (switch_id,),
                ).fetchall()
                port_key = normalize_interface_name(str(port)).lower()
                matching_interfaces = [
                    row for row in interface_rows
                    if normalize_interface_name(str(row['interface_name'] or '')).lower() == port_key
                ]
                interface = max(
                    matching_interfaces,
                    key=lambda row: (
                        str(row['oper_status'] or '').strip().lower() not in {'', 'unknown', '-', '--'},
                        str(row['admin_status'] or '').strip().lower() not in {'', 'unknown', '-', '--'},
                        bool(row['access_vlan'] or row['native_vlan'] or str(row['allowed_vlans'] or '').strip()),
                        bool(str(row['description'] or '').strip()),
                        str(row['last_seen'] or ''),
                    ),
                    default=None,
                )
                if interface:
                    interface_data = {key: interface[key] for key in interface.keys()}
                    for candidate in matching_interfaces:
                        for field in ('description', 'switchport_mode', 'access_vlan', 'native_vlan', 'allowed_vlans'):
                            current_value = str(interface_data.get(field) or '').strip().lower()
                            candidate_value = candidate[field]
                            if current_value in {'', 'unknown', '-', '--'} and candidate_value not in (None, ''):
                                interface_data[field] = candidate_value
                        for field in ('admin_status', 'oper_status'):
                            current_value = str(interface_data.get(field) or '').strip().lower()
                            candidate_value = str(candidate[field] or '').strip().lower()
                            if current_value in {'', 'unknown', '-', '--'} and candidate_value not in {'', 'unknown', '-', '--'}:
                                interface_data[field] = candidate[field]
                    l2.update({
                        'description': interface_data.get('description') or '',
                        'admin_status': interface_data.get('admin_status') or '',
                        'oper_status': interface_data.get('oper_status') or '',
                        'mode': interface_data.get('switchport_mode') or '',
                        'native_vlan': str(interface_data.get('native_vlan')) if interface_data.get('native_vlan') else '',
                        'allowed_vlans': interface_data.get('allowed_vlans') or '',
                    })
                    if not l2['vlan']:
                        interface_vlan = parse_vlan_id_from_interface(interface_data.get('interface_name'))
                        interface_vlan = interface_vlan or _parse_vlan_id(interface_data.get('access_vlan')) or _parse_vlan_id(interface_data.get('native_vlan'))
                        if interface_vlan:
                            l2['vlan'] = str(interface_vlan)
                            l2['vlan_source'] = 'interface_snapshot'
                    set_if_empty(context['l3'], 'vrf', interface_data.get('vrf_name'))
                    context['freshness']['interface_last_seen'] = interface_data.get('last_seen') or ''

                # VLAN discovery can create an access-port row before the
                # interface-status collector has a CLI/IP snapshot for that
                # port, leaving admin/oper status as ``unknown``.  The
                # network monitor already has a fresher IF-MIB status for the
                # same device/port; use it as the fallback for the locator.
                telemetry_rows = conn.execute(
                    '''SELECT interface_name, status, ts
                       FROM interface_telemetry_raw
                       WHERE device_id = ?
                       ORDER BY ts DESC
                       LIMIT 500''',
                    (switch_id,),
                ).fetchall()
                telemetry = next(
                    (
                        row for row in telemetry_rows
                        if normalize_interface_name(str(row['interface_name'] or '')).lower() == port_key
                    ),
                    None,
                )
                telemetry_status = str(telemetry['status'] or '').strip().lower() if telemetry else ''
                if telemetry_status in {'up', 'down', 'testing'}:
                    if str(l2.get('admin_status') or '').strip().lower() in {'', 'unknown', '-', '--'}:
                        l2['admin_status'] = telemetry_status
                    if str(l2.get('oper_status') or '').strip().lower() in {'', 'unknown', '-', '--'}:
                        l2['oper_status'] = telemetry_status
                    if not context['freshness']['interface_last_seen'] or str(telemetry['ts'] or '') > str(context['freshness']['interface_last_seen']):
                        context['freshness']['interface_last_seen'] = telemetry['ts'] or ''

            # Resolve the gateway SVI/VLANIF even when the endpoint is not
            # currently present in the access-switch tables.
            gateway_device_id = str(best_prefix['gateway_device_id'] or '') if best_prefix else ''
            gateway_ip = str(best_prefix['gateway'] or '') if best_prefix else ''
            if gateway_device_id:
                gateway_interfaces = conn.execute(
                    '''SELECT i.id, i.interface_name, i.primary_ip, i.ip_address,
                              i.admin_status, i.oper_status, i.last_seen, v.vrf_name,
                              d.hostname AS device_name
                       FROM interfaces i
                       LEFT JOIN vrfs v ON v.id = i.vrf_id
                       LEFT JOIN devices d ON d.id = i.device_id
                       WHERE i.device_id = ?''',
                    (gateway_device_id,),
                ).fetchall()
                current_vlan_id = _parse_vlan_id(l2.get('vlan'))
                gateway_interface = next(
                    (
                        row for row in gateway_interfaces
                        if (best_prefix and best_prefix['gateway_interface_id'] and row['id'] == best_prefix['gateway_interface_id'])
                        or (gateway_ip and gateway_ip in {row['primary_ip'], row['ip_address']})
                        or (current_vlan_id and parse_vlan_id_from_interface(row['interface_name']) == current_vlan_id)
                    ),
                    None,
                )
                if gateway_interface:
                    set_if_empty(context['l3'], 'gateway_device', gateway_interface['device_name'] or gateway_device_id)
                    set_if_empty(context['l3'], 'gateway_interface', gateway_interface['interface_name'])
                    set_if_empty(context['l3'], 'vrf', gateway_interface['vrf_name'])
                    gateway_vlan = parse_vlan_id_from_interface(gateway_interface['interface_name'])
                    if not l2['vlan'] and gateway_vlan:
                        l2['vlan'] = str(gateway_vlan)
                        l2['vlan_source'] = 'vlanif_interface'
                    context['freshness']['interface_last_seen'] = gateway_interface['last_seen'] or context['freshness']['interface_last_seen']

            resolved_site_id = str(best_prefix['site_id'] or '') if best_prefix else ''
            if not resolved_site_id and endpoint:
                resolved_site_id = str(endpoint['device_site_id'] or '')
            vlan_number = _parse_vlan_id(l2.get('vlan'))
            if vlan_number:
                vlan_row = conn.execute(
                    '''SELECT name FROM vlans
                       WHERE vlan_id = ? AND (? = '' OR COALESCE(site_id, '') = ?)
                       ORDER BY CASE WHEN COALESCE(site_id, '') = ? THEN 0 ELSE 1 END
                       LIMIT 1''',
                     (vlan_number, resolved_site_id, resolved_site_id, resolved_site_id),
                ).fetchone()
                if vlan_row:
                    l2['vlan_name'] = vlan_row['name'] or ''
                binding_rows = conn.execute(
                    '''SELECT business_system, department, owner, business_level
                       FROM vlan_business_bindings
                       WHERE vlan_id = ?
                         AND (site_id = ? OR (site_id = '' AND ? = ''))
                         AND status <> 'retired'
                       ORDER BY business_system''',
                     (vlan_number, resolved_site_id, resolved_site_id),
                ).fetchall()
                if binding_rows:
                    context['business']['business_systems'] = [row['business_system'] for row in binding_rows]
                    context['business']['department'] = context['business']['department'] or binding_rows[0]['department'] or ''
                    context['business']['owner'] = context['business']['owner'] or binding_rows[0]['owner'] or ''
                    context['business']['business_level'] = next(
                        (level for level in ('P1', 'P2', 'P3', 'P4') if any(row['business_level'] == level for row in binding_rows)),
                        '',
                    )

            asset = conn.execute(
                '''SELECT asset_type, hostname, department, status, notes, site_id
                   FROM physical_assets
                   WHERE business_ip = ? OR management_ip = ?
                   ORDER BY CASE WHEN business_ip = ? THEN 0 ELSE 1 END LIMIT 1''',
                (target_ip, target_ip, target_ip),
            ).fetchone()
            if asset:
                set_if_empty(context['business'], 'hostname', asset['hostname'])
                set_if_empty(context['business'], 'asset_type', asset['asset_type'])
                set_if_empty(context['business'], 'department', asset['department'])
                set_if_empty(context['business'], 'site', asset['site_id'])
                set_if_empty(context['business'], 'description', asset['notes'])
                if not context['address']['status']:
                    context['address']['status'] = asset['status'] or ''

            device_ids = {str(v) for v in (
                l2.get('switch_id'), best_prefix['gateway_device_id'] if best_prefix else ''
            ) if v}
            if device_ids:
                placeholders = ','.join('?' for _ in device_ids)
                backup = conn.execute(
                    f'''SELECT backup_time FROM config_backups
                        WHERE device_id IN ({placeholders})
                        ORDER BY backup_time DESC LIMIT 1''',
                    tuple(device_ids),
                ).fetchone()
                if backup:
                    context['business']['config_backup_at'] = backup['backup_time'] or ''

                alert_rows = conn.execute(
                    f'''SELECT id, severity, title, created_at, interface_name
                        FROM alert_events
                        WHERE resolved_at IS NULL
                          AND COALESCE(workflow_status, 'open') != 'suppressed'
                          AND (device_id IN ({placeholders}) OR title LIKE ? OR message LIKE ?)
                        ORDER BY created_at DESC LIMIT 5''',
                    (*device_ids, f'%{target_ip}%', f'%{target_ip}%'),
                ).fetchall()
                context['business']['open_alerts'] = [
                    {
                        'id': row['id'], 'severity': row['severity'], 'title': row['title'],
                        'created_at': row['created_at'], 'interface': row['interface_name'] or '',
                    }
                    for row in alert_rows
                ]

            route_rows = conn.execute(
                '''SELECT rt.destination, rt.next_hop, rt.protocol, rt.outgoing_interface,
                          rt.vrf_name, rt.last_updated, d.hostname AS device_name
                   FROM route_table rt
                   LEFT JOIN devices d ON d.id = rt.device_id
                   WHERE COALESCE(rt.active, 1) = 1
                   ORDER BY rt.last_updated DESC LIMIT 1000'''
            ).fetchall()
            best_route = None
            best_route_len = -1
            if ip_obj:
                for row in route_rows:
                    try:
                        network = ipaddress.ip_network(row['destination'], strict=False)
                    except (ValueError, TypeError, KeyError):
                        continue
                    if network.version == ip_obj.version and ip_obj in network and network.prefixlen > best_route_len:
                        best_route = row
                        best_route_len = network.prefixlen
            if best_route:
                context['l3'].update({
                    'next_hop': best_route['next_hop'] or '',
                    'route_source': best_route['protocol'] or '',
                    'route_interface': best_route['outgoing_interface'] or '',
                    'route_last_updated': best_route['last_updated'] or '',
                })
                set_if_empty(context['l3'], 'vrf', best_route['vrf_name'])
                set_if_empty(context['l3'], 'gateway_device', best_route['device_name'])

            # Build only an evidence-backed access-switch -> gateway path from LLDP topology.
            path: list[dict[str, Any]] = []
            if l2.get('mac'):
                path.extend([
                    {'kind': 'ip', 'label': target_ip, 'detail': context['address']['type'] or 'IP'},
                    {'kind': 'mac', 'label': l2['mac'], 'detail': 'ARP'},
                ])
            if l2.get('switch_name') or l2.get('switch_id'):
                path.append({
                    'kind': 'access',
                    'label': l2.get('switch_name') or l2.get('switch_id'),
                    'detail': l2.get('port') or '',
                })
            if l2.get('vlan'):
                path.append({
                    'kind': 'vlan',
                    'label': f"VLAN {l2['vlan']}",
                    'detail': l2.get('vlan_name') or l2.get('vlan_source') or '',
                })

            access_id = str(l2.get('switch_id') or '')
            gateway_id = str(best_prefix['gateway_device_id'] or '') if best_prefix else ''
            if access_id and gateway_id and access_id != gateway_id:
                link_rows = conn.execute(
                    '''SELECT source_device_id, source_hostname, source_port,
                              target_device_id, target_hostname, target_port,
                              status, last_seen
                       FROM topology_links
                       WHERE COALESCE(status, 'unknown') <> 'stale' '''
                ).fetchall()
                adjacency: dict[str, list[tuple[str, str, str, str]]] = {}
                for link in link_rows:
                    source_id = str(link['source_device_id'] or '')
                    target_id = str(link['target_device_id'] or '')
                    if not source_id or not target_id:
                        continue
                    adjacency.setdefault(source_id, []).append((
                        target_id, link['target_hostname'] or target_id,
                        link['source_port'] or '', link['target_port'] or '',
                    ))
                    adjacency.setdefault(target_id, []).append((
                        source_id, link['source_hostname'] or source_id,
                        link['target_port'] or '', link['source_port'] or '',
                    ))

                queue: list[tuple[str, list[tuple[str, str, str, str]]]] = [(access_id, [])]
                visited = {access_id}
                device_hops: list[tuple[str, str, str, str]] | None = None
                while queue and device_hops is None:
                    current, current_path = queue.pop(0)
                    if current == gateway_id:
                        device_hops = current_path
                        break
                    if len(current_path) >= 8:
                        continue
                    for neighbor_id, neighbor_name, local_port, neighbor_port in adjacency.get(current, []):
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)
                        next_path = current_path + [(neighbor_id, neighbor_name, local_port, neighbor_port)]
                        if neighbor_id == gateway_id:
                            device_hops = next_path
                            break
                        queue.append((neighbor_id, next_path))

                if device_hops:
                    context['l3']['upstream_devices'] = [
                        {
                            'device': device_name or device_id,
                            'device_id': device_id,
                            'port': local_port or '',
                            'peer_port': neighbor_port or '',
                        }
                        for device_id, device_name, local_port, neighbor_port in device_hops
                    ]
                    path_device_ids = {item[0] for item in device_hops}
                    # LLDP gives adjacency, not traffic direction.  A device
                    # that is not on the selected access-to-gateway path is
                    # therefore a peer/other neighbor, not a downstream device.
                    context['l3']['adjacent_devices'] = [
                        {
                            'device': neighbor_name or neighbor_id,
                            'device_id': neighbor_id,
                            'port': local_port or '',
                            'peer_port': neighbor_port or '',
                        }
                        for neighbor_id, neighbor_name, local_port, neighbor_port in adjacency.get(access_id, [])
                        if neighbor_id not in path_device_ids
                    ]
                    for index, (device_id, device_name, local_port, neighbor_port) in enumerate(device_hops):
                        is_gateway = device_id == gateway_id
                        path.append({
                            'kind': 'gateway' if is_gateway else 'transit',
                            'label': device_name or device_id,
                            'detail': (
                                f"{local_port} ↔ {neighbor_port}" if local_port or neighbor_port else ''
                            ),
                        })
            elif gateway_id and access_id == gateway_id:
                path.append({
                    'kind': 'gateway',
                    'label': context['l3']['gateway_device'] or gateway_id,
                    'detail': context['l3']['gateway_interface'] or '',
                })

            if context['address']['prefix']:
                path.append({
                    'kind': 'network',
                    'label': context['address']['prefix'],
                    'detail': context['address']['purpose'] or context['address']['network_type'] or '',
                })
            context['path'] = path
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"[IPLocator] context aggregation error for {target_ip}: {exc}")

    return context


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
    # Return the IPAM/L2/L3/business facts even when live ARP lookup is unavailable.
    result['context'] = _get_ip_locator_context(target_ip)

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
        cached_age = _age_seconds(cached_ep.get('last_seen')) if cached_ep else None
        if cached_ep and cached_age is not None and cached_age <= ENDPOINT_CACHE_TTL_SECONDS:
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
        if cached_ep:
            result['cache']['endpoint_cache_stale'] = True
            result['cache']['endpoint_cache_age_seconds'] = cached_age

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
    gateway_devices = filter_devices(all_eligible, "arp")

    target_mac: str = ''
    arp_source_info: dict | None = None

    # ── Step 1: ARP 懒加载缓存（仅按 IP 命中，不做全网预采集） ──
    if not force_refresh:
        cached_arp = _get_cached_arp(target_ip)
        if cached_arp:
            target_mac = str(cached_arp.get('mac') or '')
            arp_source_info = dict(cached_arp.get('arp_source') or {}) or None
            if arp_source_info is not None and cached_arp.get('vlan'):
                arp_source_info.setdefault('vlan', cached_arp['vlan'])
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
                        'vlan': arp_hit.get('vlan', ''),
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
    terminal_vlan_source = 'unknown'
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
                terminal_vlan_source = mac_rec.get('vlan_source', 'mac_table') if terminal_vlan else 'unknown'
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
            'vlan_source': terminal_vlan_source,
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
            'vlan': arp_source_info.get('vlan', ''),
            'vlan_source': arp_source_info.get('vlan_source', 'arp_vid') if arp_source_info.get('vlan') else 'unknown',
            'type': 'ARP_DIRECT',
            'is_uplink': False,
            'note': '该 MAC 未在交换机 MAC 表中发现，定位基于 ARP 记录',
        }]
    
    result['context'] = _get_ip_locator_context(target_ip, result)
    return result



async def locate_ip_async(target_ip: str) -> dict[str, Any]:
    """异步包装，在线程池中执行阻塞的 SSH 操作。"""
    return await asyncio.to_thread(locate_ip, target_ip)


async def locate_ip_async_with_options(target_ip: str, force_refresh: bool = False) -> dict[str, Any]:
    """异步包装（带选项），支持强制刷新跳过缓存。"""
    return await asyncio.to_thread(locate_ip, target_ip, force_refresh)


# ── 后台全量 ARP 采集 ──────────────────────────────────────────────

def _load_arp_collection_state() -> dict[str, dict[str, Any]]:
    """Load retry state once so a sweep does not query the DB per device."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT device_id, consecutive_failures, next_retry_at,
                   circuit_state, failure_class
            FROM device_collection_status
            WHERE collector = 'arp'
            """
        ).fetchall()
        return {str(row['device_id']): dict(row) for row in rows}
    except Exception as exc:
        logger.warning("[ARP Sweep] Could not load retry state: %s", exc)
        return {}
    finally:
        conn.close()


def _load_svi_evidence() -> set[str]:
    """Return device ids whose interface inventory proves an SVI/Vlanif."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT device_id, interface_name, ip_address, primary_ip, is_l3 FROM interfaces"
        ).fetchall()
    except Exception:
        try:
            rows = conn.execute(
                "SELECT device_id, interface_name, ip_address FROM interfaces"
            ).fetchall()
        except Exception as exc:
            logger.debug("[ARP Sweep] Could not load SVI evidence: %s", exc)
            return set()
    finally:
        conn.close()

    evidence: set[str] = set()
    for row in rows:
        row_data = dict(row) if hasattr(row, 'keys') else row
        name = str(row_data['interface_name'] or '').strip().lower()
        ip_value = str(row_data.get('ip_address') or row_data.get('primary_ip') or '').strip()
        is_svi = name.startswith(('vlan', 'vlanif', 'vlan-interface'))
        if is_svi and ip_value not in {'', '--', 'unassigned', '0.0.0.0'}:
            evidence.add(str(row_data['device_id']))
    return evidence


def _arp_device_is_due(state: dict[str, Any], now: datetime) -> bool:
    retry_at = state.get('next_retry_at')
    if not retry_at:
        return True
    try:
        parsed = datetime.fromisoformat(str(retry_at).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= now
    except (TypeError, ValueError):
        return True


def _load_arp_sweep_devices(run_id: str = '') -> tuple[list[dict], int, int]:
    """Select ARP-capable devices and skip devices in retry backoff."""
    all_eligible = _load_eligible_devices()
    svi_devices = _load_svi_evidence()
    state_by_device = _load_arp_collection_state()
    now = datetime.now(timezone.utc)
    candidates: list[dict] = []
    skipped_backoff = 0

    for device in all_eligible:
        role = str(device.get('role') or '').strip().lower()
        explicit = explicit_collector_override(device, 'arp')
        if explicit is False:
            continue
        capable_by_role = role in _ARP_L3_ROLES
        capable_by_svi = (
            str(device.get('id') or '') in svi_devices
            and role in _ARP_SVI_ROLES
        )
        if explicit is not True and not (capable_by_role or capable_by_svi):
            continue
        state = state_by_device.get(str(device.get('id') or ''), {})
        if not _arp_device_is_due(state, now):
            skipped_backoff += 1
            continue
        if capable_by_svi and explicit is None:
            device = dict(device)
            device['_arp_policy_override'] = True
        candidates.append(device)

    candidates.sort(key=lambda item: str(item.get('id') or item.get('ip_address') or ''))
    if not candidates:
        return [], len(all_eligible), skipped_backoff

    batch = reserve_collector_sweep_batch(
        'arp',
        total_candidates=len(candidates),
        batch_size=ARP_MAX_DEVICES_PER_SWEEP,
        run_id=run_id,
    )
    start = int(batch.get('start_cursor') or 0) % len(candidates)
    selected_count = min(len(candidates), int(batch.get('selected_count') or len(candidates)))
    selected = [candidates[(start + offset) % len(candidates)] for offset in range(selected_count)]
    return selected, len(all_eligible), skipped_backoff


def _classify_arp_failure(error: Any) -> str:
    text = str(error or '').lower()
    if 'authentication' in text or 'auth' in text or 'permission' in text:
        return 'auth_failed'
    if 'no command' in text or 'not supported' in text or 'unsupported' in text:
        return 'unsupported'
    if 'limit' in text or 'concurrency' in text or 'rate' in text:
        return 'rate_limited'
    if any(token in text for token in ('timeout', 'timed out', 'unreachable', 'refused', 'closed', 'network')):
        return 'unreachable'
    return 'collection_failed'


def _arp_retry_delay(failure_class: str, failure_count: int) -> int:
    if failure_class == 'unsupported':
        return _ARP_UNSUPPORTED_RETRY_SECONDS
    if failure_class == 'auth_failed':
        return _ARP_AUTH_RETRY_SECONDS
    if failure_class == 'rate_limited':
        return 60
    exponent = max(0, min(6, failure_count - 1))
    return min(_ARP_RETRY_MAX_SECONDS, _ARP_RETRY_BASE_SECONDS * (2 ** exponent))


def _collect_full_arp_result(device_info: dict) -> dict[str, Any]:
    """从单台设备采集完整 ARP 表，返回解析后的条目列表。"""
    try:
        payload = collect_operational_data(
            device_info,
            categories=['arp'],
            policy_override_categories={'arp'} if device_info.get('_arp_policy_override') else None,
        )
    except Exception as exc:
        logger.warning(
            "[ARP Sweep] collection failed on %s: %s",
            device_info.get('hostname') or device_info.get('ip_address'),
            exc,
        )
        return {
            'entries': [],
            'status': 'failed',
            'failure_class': _classify_arp_failure(exc),
            'error_message': str(exc),
        }

    entries = []
    dev_label = device_info.get('hostname') or device_info.get('ip_address')
    dev_id = device_info.get('id')
    arp_category_found = False
    failure_class = ''
    error_message = ''
    for cat in payload.get('categories', []):
        if cat.get('key') != 'arp':
            continue
        arp_category_found = True
        if not cat.get('success'):
            logger.warning(
                "[ARP Sweep] %s ARP command failed: %s",
                dev_label,
                cat.get('error') or 'unknown error',
            )
            failure_class = _classify_arp_failure(cat.get('error'))
            error_message = str(cat.get('error') or 'ARP command failed')
            continue

        for rec in cat.get('records', []):
            normalized = _normalize_arp_record(rec, device_info)
            if normalized:
                entries.append(normalized)

        # NTC/TextFSM records are normalized first.  If a platform's command
        # output is valid but its template is incomplete, use the conservative
        # vendor-neutral row parser as a fallback.
        if not entries:
            for raw_output in cat.get('raw_outputs') or []:
                entries.extend(_parse_arp_output_fallback(raw_output.get('output', ''), device_info))

        if not entries:
            command = ', '.join(cat.get('commands') or []) or 'unknown'
            raw_size = sum(len(str(item.get('output') or '')) for item in (cat.get('raw_outputs') or []))
            logger.warning(
                "[ARP Sweep] %s returned no parseable ARP entries (command=%s, parser=%s, raw_bytes=%d)",
                dev_label,
                command,
                cat.get('parser') or 'unknown',
                raw_size,
            )

    # A device should not produce duplicate IP/MAC rows when both a custom
    # template and the raw fallback recognize the same line.
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in entries:
        unique[(entry['ip'], entry['mac'], entry.get('interface') or '')] = entry
    entries = list(unique.values())
    if not arp_category_found:
        return {
            'entries': [],
            'status': 'failed',
            'failure_class': 'unsupported',
            'error_message': 'ARP category was not collected for this device',
        }
    if failure_class:
        return {
            'entries': [],
            'status': 'failed',
            'failure_class': failure_class,
            'error_message': error_message,
        }
    return {'entries': entries, 'status': 'success', 'failure_class': '', 'error_message': ''}


def _collect_full_arp_from_device(device_info: dict) -> list[dict]:
    """Backward-compatible list-returning wrapper for existing callers."""
    return _collect_full_arp_result(device_info).get('entries', [])


def _persist_arp_device_entries(device_info: dict, entries: list[dict]) -> dict[str, Any]:
    """Atomically replace one device's successful ARP snapshot."""
    if not entries:
        return {'entry_count': 0, 'mac_changes': 0}

    device_id = str(device_info.get('id') or '')
    if not device_id:
        raise ValueError('ARP result has no device id')
    cached_at = _beijing_now_iso()
    now_ts = time.time()
    expires_at = now_ts + ARP_CACHE_TTL_SECONDS
    placeholder = '%s' if _USE_PG else '?'
    normalized_entries = [dict(entry) for entry in entries]
    for entry in normalized_entries:
        entry['source_device_id'] = device_id
        entry['source_device'] = device_info.get('hostname') or device_info.get('ip_address') or ''

    conn = get_db_connection()
    mac_changes: list[dict[str, Any]] = []
    try:
        old_rows = conn.execute(
            f'SELECT target_ip, mac, arp_source FROM arp_cache WHERE source_device_id = {placeholder}',
            (device_id,),
        ).fetchall()
        old_by_ip: dict[str, tuple[str, str]] = {}
        for row in old_rows:
            try:
                source = _json.loads(row['arp_source'] or '{}')
            except (TypeError, ValueError):
                source = {}
            old_by_ip[str(row['target_ip'])] = (str(row['mac'] or ''), str(source.get('device') or ''))

        mac_vlan_map: dict[str, str] = {}
        for row in conn.execute(
            f'SELECT mac_address, vlan_id FROM mac_table WHERE device_id = {placeholder} AND vlan_id IS NOT NULL',
            (device_id,),
        ).fetchall():
            mac_key = _normalize_mac(row['mac_address'])
            vlan_value = _parse_vlan_id(row['vlan_id'])
            if mac_key and vlan_value is not None:
                mac_vlan_map.setdefault(mac_key, str(vlan_value))

        conn.execute(f'DELETE FROM arp_table WHERE device_id = {placeholder}', (device_id,))
        conn.execute(f'DELETE FROM arp_cache WHERE source_device_id = {placeholder}', (device_id,))

        for entry in normalized_entries:
            if not entry.get('vlan') and mac_vlan_map.get(entry.get('mac', '')):
                entry['vlan'] = mac_vlan_map[entry['mac']]
                entry['vlan_source'] = 'mac_table'
            vlan_id = _parse_vlan_id(entry.get('vlan')) or parse_vlan_id_from_interface(entry.get('interface'))
            source_dict = {
                'device_id': device_id,
                'device': entry.get('source_device') or '',
                'interface': entry.get('interface') or '',
                'vlan': entry.get('vlan') or '',
                'vlan_source': entry.get('vlan_source') or 'unknown',
            }
            conn.execute(
                f'''INSERT INTO arp_cache
                    (target_ip, mac, vlan_id, arp_source, cached_at, expires_at, source_device_id)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                    ON CONFLICT(target_ip) DO UPDATE SET
                        mac = excluded.mac, vlan_id = excluded.vlan_id,
                        arp_source = excluded.arp_source, cached_at = excluded.cached_at,
                        expires_at = excluded.expires_at, source_device_id = excluded.source_device_id''',
                (
                    entry['ip'], entry['mac'], vlan_id, _json.dumps(source_dict),
                    cached_at, expires_at, device_id,
                ),
            )
            conn.execute(
                f'''INSERT INTO arp_table
                    (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})''',
                (
                    str(uuid.uuid4()), device_id, entry['ip'], entry['mac'],
                    entry.get('interface') or '', vlan_id, cached_at,
                ),
            )
            old = old_by_ip.get(str(entry['ip']))
            if old and old[0] != entry['mac']:
                mac_changes.append({
                    'ip': entry['ip'],
                    'old_mac': old[0],
                    'new_mac': entry['mac'],
                    'old_vendor': lookup_vendor(old[0]),
                    'new_vendor': lookup_vendor(entry['mac']),
                    'old_device': old[1],
                    'new_device': entry.get('source_device') or '',
                })
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    with _ARP_CACHE_LOCK:
        for entry in normalized_entries:
            _ARP_CACHE[entry['ip']] = {
                'target_ip': entry['ip'],
                'mac': entry['mac'],
                'arp_source': {
                    'device_id': device_id,
                    'device': entry.get('source_device') or '',
                    'interface': entry.get('interface') or '',
                },
                'cached_at': cached_at,
                'created_at_epoch': now_ts,
                'expires_at': expires_at,
            }
        _prune_memory_cache(now_ts)

    if mac_changes:
        conn = get_db_connection()
        try:
            conn.executemany(
                f'''INSERT INTO mac_change_log
                    (ip, old_mac, new_mac, old_vendor, new_vendor, old_device, new_device, detected_at)
                    VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})''',
                [
                    (
                        change['ip'], change['old_mac'], change['new_mac'],
                        change['old_vendor'], change['new_vendor'], change['old_device'],
                        change['new_device'], cached_at,
                    )
                    for change in mac_changes
                ],
            )
            conn.commit()
        finally:
            conn.close()
    return {'entry_count': len(normalized_entries), 'mac_changes': len(mac_changes)}


def run_arp_sweep() -> dict[str, Any]:
    """
    后台全量 ARP 采集：并发 SSH 到所有网关设备，采集完整 ARP 表并写入缓存。
    由 APScheduler 定时调度（每 5 分钟）。
    """
    logger.info("[ARP Sweep] Starting full ARP table collection...")
    t0 = time.time()

    collection_run_id = str(uuid.uuid4())
    gateway_devices, total_eligible, skipped_backoff = _load_arp_sweep_devices(collection_run_id)
    # ARP 采集不按角色排除——access 路由器同样拥有 ARP 表
    if not gateway_devices:
        logger.info("[ARP Sweep] No eligible devices, skipping")
        return {
            'eligible_devices': 0,
            'total_eligible_devices': total_eligible,
            'skipped_backoff_devices': skipped_backoff,
            'collection_run_id': collection_run_id,
            'batch_size': 0,
            'max_batch_size': ARP_MAX_DEVICES_PER_SWEEP,
            'devices_with_entries': 0,
            'collected_entries': 0,
            'device_results': [],
        }

    logger.info(
        "[ARP Sweep] %s ARP-capable device(s) selected from %s eligible device(s); %s in retry backoff",
        len(gateway_devices), total_eligible, skipped_backoff,
    )

    all_entries: list[dict] = []
    device_results: list[dict[str, Any]] = []
    successful_device_ids: set[str] = set()
    workers = _calc_ssh_workers(len(gateway_devices))

    state_by_device = _load_arp_collection_state()
    status_updates: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_collect_full_arp_result, dev): dev for dev in gateway_devices}
        for future in as_completed(future_map):
            dev = future_map[future]
            try:
                result = future.result()
                entries = result.get('entries', [])
                result_status = result.get('status') or 'failed'
                failure_class = result.get('failure_class') or ''
                error_message = result.get('error_message') or ''
                all_entries.extend(entries)
                if result_status == 'success' and entries and dev.get('id'):
                    successful_device_ids.add(str(dev['id']))
                previous_failures = int(
                    state_by_device.get(str(dev.get('id') or ''), {}).get('consecutive_failures') or 0
                )
                failure_count = previous_failures + 1 if result_status != 'success' else 0
                retry_at = None
                circuit_state = 'closed'
                if result_status != 'success':
                    delay = _arp_retry_delay(failure_class, failure_count)
                    retry_at = (
                        datetime.now(timezone.utc) + timedelta(seconds=delay)
                    ).replace(microsecond=0).isoformat()
                    circuit_state = 'open' if failure_count >= _ARP_CIRCUIT_OPEN_AFTER else 'backoff'
                status_updates.append({
                    'device_id': str(dev.get('id') or ''),
                    'collector': 'arp',
                    'status': 'success' if result_status == 'success' else 'failed',
                    'transport': 'ssh',
                    'source': 'arp_sweep',
                    'coverage_total': len(entries),
                    'coverage_supported': 1 if result_status == 'success' else 0,
                    'error_code': failure_class,
                    'error_message': error_message,
                    'next_retry_at': retry_at,
                    'failure_class': failure_class,
                    'circuit_state': circuit_state,
                    'metadata': {
                        'collection_run_id': collection_run_id,
                        'entry_count': len(entries),
                        'failure_count': failure_count,
                    },
                })
                device_results.append({
                    'device_id': dev.get('id'),
                    'device': dev.get('hostname') or dev.get('ip_address'),
                    'entry_count': len(entries),
                    'status': 'success' if result_status == 'success' and entries else (
                        'no_data' if result_status == 'success' else 'failed'
                    ),
                    'failure_class': failure_class,
                })
            except Exception as exc:
                logger.warning("[ARP Sweep] Error from %s: %s", dev.get('hostname') or dev.get('ip_address'), exc)
                failure_class = _classify_arp_failure(exc)
                previous_failures = int(
                    state_by_device.get(str(dev.get('id') or ''), {}).get('consecutive_failures') or 0
                )
                failure_count = previous_failures + 1
                retry_at = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=_arp_retry_delay(failure_class, failure_count))
                ).replace(microsecond=0).isoformat()
                status_updates.append({
                    'device_id': str(dev.get('id') or ''),
                    'collector': 'arp',
                    'status': 'failed',
                    'transport': 'ssh',
                    'source': 'arp_sweep',
                    'coverage_total': 0,
                    'coverage_supported': 0,
                    'error_code': failure_class,
                    'error_message': str(exc),
                    'next_retry_at': retry_at,
                    'failure_class': failure_class,
                    'circuit_state': 'open' if failure_count >= _ARP_CIRCUIT_OPEN_AFTER else 'backoff',
                    'metadata': {
                        'collection_run_id': collection_run_id,
                        'entry_count': 0,
                        'failure_count': failure_count,
                    },
                })
                device_results.append({
                    'device_id': dev.get('id'),
                    'device': dev.get('hostname') or dev.get('ip_address'),
                    'entry_count': 0,
                    'status': 'failed',
                    'failure_class': failure_class,
                })

    record_collection_results(status_updates)

    if not all_entries:
        logger.info("[ARP Sweep] No ARP entries collected")
        complete_collector_sweep(
            'arp',
            run_id=collection_run_id,
            successful_devices=sum(1 for item in device_results if item.get('status') == 'success'),
            failed_devices=sum(1 for item in device_results if item.get('status') == 'failed'),
            collected_entries=0,
        )
        return {
            'eligible_devices': len(gateway_devices),
            'total_eligible_devices': total_eligible,
            'skipped_backoff_devices': skipped_backoff,
            'collection_run_id': collection_run_id,
            'batch_size': len(gateway_devices),
            'max_batch_size': ARP_MAX_DEVICES_PER_SWEEP,
            'devices_with_entries': 0,
            'collected_entries': 0,
            'device_results': sorted(device_results, key=lambda item: item.get('device') or ''),
        }

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

    # L2: 批量 upsert 配置数据库
    try:
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM arp_cache WHERE expires_at <= ?', (now_ts,))
            if successful_device_ids:
                for device_id in successful_device_ids:
                    conn.execute('DELETE FROM arp_table WHERE device_id = ?', (device_id,))
                stale_cache_ips: list[str] = []
                for cache_row in conn.execute('SELECT target_ip, arp_source FROM arp_cache').fetchall():
                    try:
                        source = _json.loads(cache_row['arp_source'] or '{}')
                    except (TypeError, ValueError):
                        source = {}
                    if str(source.get('device_id') or '') in successful_device_ids:
                        stale_cache_ips.append(str(cache_row['target_ip']))
                for target_ip in stale_cache_ips:
                    conn.execute('DELETE FROM arp_cache WHERE target_ip = ?', (target_ip,))
            mac_vlan_map: dict[tuple[str, str], str] = {}
            for mac_row in conn.execute('SELECT device_id, mac_address, vlan_id FROM mac_table WHERE vlan_id IS NOT NULL').fetchall():
                mac_key = _normalize_mac(mac_row['mac_address'])
                vlan_value = _parse_vlan_id(mac_row['vlan_id'])
                if mac_key and vlan_value is not None:
                    mac_vlan_map.setdefault((str(mac_row['device_id']), mac_key), str(vlan_value))
            for e in all_entries:
                if not e.get('vlan'):
                    learned_vlan = mac_vlan_map.get((str(e.get('source_device_id')), e['mac']))
                    if learned_vlan:
                        e['vlan'] = learned_vlan
                        e['vlan_source'] = 'mac_table'
                vlan_id = _parse_vlan_id(e.get('vlan')) or parse_vlan_id_from_interface(e.get('interface'))
                if vlan_id is not None and not e.get('vlan'):
                    e['vlan'] = str(vlan_id)
                    e['vlan_source'] = 'arp_interface'
                source_dict = {
                    'device_id': e['source_device_id'],
                    'device': e['source_device'],
                    'interface': e['interface'],
                    'vlan': e.get('vlan', ''),
                    'vlan_source': e.get('vlan_source', 'unknown'),
                }
                conn.execute(
                    '''INSERT INTO arp_cache (target_ip, mac, vlan_id, arp_source, cached_at, expires_at, source_device_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(target_ip) DO UPDATE SET
                           mac = excluded.mac,
                           vlan_id = excluded.vlan_id,
                           arp_source = excluded.arp_source,
                           cached_at = excluded.cached_at,
                           expires_at = excluded.expires_at,
                           source_device_id = excluded.source_device_id''',
                     (e['ip'], e['mac'], vlan_id, _json.dumps(source_dict), cached_at, expires_at, str(e.get('source_device_id') or '')),
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
                    conn.execute(
                        '''INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (str(uuid.uuid4()), dev_id, e['ip'], e['mac'], e['interface'] or '', vlan_id, cached_at)
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
    complete_collector_sweep(
        'arp',
        run_id=collection_run_id,
        successful_devices=sum(1 for item in device_results if item.get('status') == 'success'),
        failed_devices=sum(1 for item in device_results if item.get('status') == 'failed'),
        collected_entries=len(all_entries),
    )
    logger.info(f"[ARP Sweep] Collected {len(all_entries)} entries from {len(gateway_devices)} devices in {elapsed}s")
    return {
        'eligible_devices': len(gateway_devices),
        'total_eligible_devices': total_eligible,
        'skipped_backoff_devices': skipped_backoff,
        'collection_run_id': collection_run_id,
        'batch_size': len(gateway_devices),
        'max_batch_size': ARP_MAX_DEVICES_PER_SWEEP,
        'devices_with_entries': sum(1 for item in device_results if item.get('entry_count', 0) > 0),
        'collected_entries': len(all_entries),
        'device_results': sorted(device_results, key=lambda item: item.get('device') or ''),
        'elapsed_seconds': elapsed,
    }


async def run_arp_sweep_async():
    """异步包装，供 APScheduler 调度。"""
    return await asyncio.to_thread(run_arp_sweep)


def dispatch_arp_sweep() -> dict[str, Any]:
    """Queue one bounded ARP batch for the process-safe worker pool."""
    collection_run_id = str(uuid.uuid4())
    devices, total_eligible, skipped_backoff = _load_arp_sweep_devices(collection_run_id)
    if not devices:
        return {
            'collection_run_id': collection_run_id,
            'total_eligible_devices': total_eligible,
            'skipped_backoff_devices': skipped_backoff,
            'batch_size': 0,
            'queued_devices': 0,
            'max_batch_size': ARP_MAX_DEVICES_PER_SWEEP,
        }
    payload_by_device = {
        str(device.get('id')): {
            'arp_policy_override': bool(device.get('_arp_policy_override')),
        }
        for device in devices
        if device.get('id')
    }
    queued = enqueue_tasks(
        'arp',
        run_id=collection_run_id,
        device_ids=[str(device['id']) for device in devices if device.get('id')],
        payload_by_device=payload_by_device,
    )
    logger.info(
        '[ARP Dispatch] queued %s device task(s) for run %s; %s in backoff',
        queued, collection_run_id, skipped_backoff,
    )
    return {
        'collection_run_id': collection_run_id,
        'total_eligible_devices': total_eligible,
        'skipped_backoff_devices': skipped_backoff,
        'batch_size': len(devices),
        'queued_devices': queued,
        'max_batch_size': ARP_MAX_DEVICES_PER_SWEEP,
    }


# ── 全量 ARP 表查询 ────────────────────────────────────────────────

def get_arp_table() -> dict[str, Any]:
    """查询 PostgreSQL ARP 事实表，并兼容定位缓存中的临时条目。"""
    now_ts = time.time()
    entries_by_ip: dict[str, dict[str, Any]] = {}
    mac_vlan_map: dict[tuple[str, str], int] = {}
    try:
        conn = get_db_connection()
        try:
            for mac_row in conn.execute(
                'SELECT device_id, mac_address, vlan_id FROM mac_table WHERE vlan_id IS NOT NULL'
            ).fetchall():
                mac_key = _normalize_mac(mac_row['mac_address'])
                vlan_value = _parse_vlan_id(mac_row['vlan_id'])
                if mac_key and vlan_value is not None:
                    mac_vlan_map.setdefault((str(mac_row['device_id']), mac_key), vlan_value)
            cache_rows = conn.execute(
                'SELECT target_ip, mac, vlan_id, arp_source, cached_at, expires_at '
                'FROM arp_cache WHERE expires_at > ? ORDER BY target_ip',
                (now_ts,),
            ).fetchall()
            for row in cache_rows:
                source = _json.loads(row['arp_source'] or '{}')
                mac_raw = _normalize_mac(row['mac'])
                if not mac_raw:
                    continue
                vlan_id = row['vlan_id'] or _parse_vlan_id(source.get('vlan'))
                if vlan_id is None:
                    vlan_id = mac_vlan_map.get((str(source.get('device_id') or ''), mac_raw))
                entries_by_ip[row['target_ip']] = {
                    'ip': row['target_ip'],
                    'mac': _format_mac(mac_raw),
                    'mac_raw': mac_raw,
                    'vlan': str(vlan_id or ''),
                    'vlan_id': vlan_id,
                    'vlan_source': source.get('vlan_source') or ('mac_table' if vlan_id else 'unknown'),
                    'vendor': lookup_vendor(mac_raw),
                    'interface': source.get('interface', ''),
                    'device': source.get('device', ''),
                    'device_id': source.get('device_id'),
                    'cached_at': row['cached_at'],
                    'ttl_remaining': max(0, int(row['expires_at'] - now_ts)),
                    'age_seconds': _age_seconds(row['cached_at']),
                    'freshness': 'fresh' if row['expires_at'] > now_ts else 'stale',
                    'source': 'arp_cache',
                }

            # arp_table is the persistent PostgreSQL source used by NSOT and
            # scheduled endpoint collection.  Older code only read arp_cache,
            # which made this page show zero even when arp_table had records.
            arp_rows = conn.execute(
                'SELECT a.ip_address, a.mac_address, a.interface_name, a.vlan_id, a.device_id, '
                'a.last_updated, d.hostname AS device_hostname '
                'FROM arp_table a LEFT JOIN devices d ON d.id = a.device_id '
                'ORDER BY a.ip_address, a.last_updated DESC'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        arp_rows = []

    for row in arp_rows:
        ip_addr = str(row['ip_address'] or '').strip()
        mac_raw = _normalize_mac(row['mac_address'])
        if not ip_addr or not mac_raw or ip_addr in entries_by_ip:
            continue
        vlan_id = row['vlan_id'] or mac_vlan_map.get((str(row['device_id'] or ''), mac_raw))
        entries_by_ip[ip_addr] = {
            'ip': ip_addr,
            'mac': _format_mac(mac_raw),
            'mac_raw': mac_raw,
            'vlan': str(vlan_id or ''),
            'vlan_id': vlan_id,
            'vlan_source': 'arp_table' if row['vlan_id'] else ('mac_table' if vlan_id else 'unknown'),
            'vendor': lookup_vendor(mac_raw),
            'interface': row['interface_name'] or '',
            'device': row['device_hostname'] or '',
            'device_id': row['device_id'],
            'cached_at': row['last_updated'],
            'ttl_remaining': 0,
            'age_seconds': _age_seconds(row['last_updated']),
            'freshness': (
                'fresh' if _age_seconds(row['last_updated']) is not None and _age_seconds(row['last_updated']) <= ARP_CACHE_TTL_SECONDS
                else 'stale' if _age_seconds(row['last_updated']) is not None else 'unknown'
            ),
            'source': 'arp_table',
        }

    entries = sorted(entries_by_ip.values(), key=lambda item: item['ip'])

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
    """从配置数据库 network_endpoints 事实表中查询终端。"""
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT ne.id, ne.ip, ne.mac, ne.hostname, ne.vendor, ne.os_type, ne.asset_type, '
                'ne.switch_id, ne.switch_port, ne.vlan, ne.vrf, ne.site, ne.source_type, '
                'ne.confidence, ne.first_seen, ne.last_seen, ne.is_active, '
                'd.hostname AS switch_name, '
                "COALESCE(s.site_name, s.site_code, NULLIF(ne.site, ''), '未分配站点') AS site_name "
                'FROM network_endpoints ne '
                'LEFT JOIN devices d ON d.id = ne.switch_id '
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
                'WHERE ne.ip = ? AND ne.is_active = 1',
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
    res['switch_name'] = res.get('switch_name') or res.get('switch_id') or ''
    res['site'] = res.get('site_name') or res.get('site') or '未分配站点'
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
    if device_info.get('platform_profile_id'):
        try:
            from services.platform_registry_service import execute_platform_action
            result = execute_platform_action(
                str(device_info['id']),
                'get_mac_table',
                user={
                    'id': f"ip-locator:{device_info.get('id') or 'unknown'}",
                    'username': 'ip-locator',
                    'role': 'Operator',
                    'tenant_id': device_info.get('tenant_id') or '',
                },
            )
            return [
                {
                    'mac': str(_record_value(record, 'mac', 'mac_address') or '').strip(),
                    'vlan': str(_record_value(record, 'vlan', 'vlan_id') or '').strip(),
                    'port': str(_record_value(record, 'interface', 'destination_port', 'port') or '').strip(),
                    'type': str(_record_value(record, 'type', 'entry_type') or '').strip(),
                    'switch_id': device_info.get('id'),
                    'switch_name': device_info.get('hostname') or device_info.get('ip_address'),
                }
                for record in (result.get('records') or [] if result.get('success') else [])
            ]
        except Exception as exc:
            logger.debug("[MAC Collector] Registry collection failed: %s", exc)
            return []
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
                "SELECT ne.id, ne.ip, ne.mac, ne.hostname, ne.vendor, ne.os_type, ne.asset_type, "
                "ne.switch_id, ne.switch_port, ne.vlan, ne.vrf, ne.site, ne.source_type, "
                "ne.confidence, ne.first_seen, ne.last_seen, ne.is_active, "
                "d.hostname AS device_name, d.site_id AS device_site_id, "
                "COALESCE(s.site_name, s.site_code, s_ep.site_name, s_ep.site_code, "
                "NULLIF(d.site, ''), NULLIF(ne.site, ''), '未分配站点') AS site_name "
                "FROM network_endpoints ne "
                "LEFT JOIN devices d ON d.id = ne.switch_id "
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
                "LEFT JOIN sites s_ep ON s_ep.id = ne.site OR s_ep.site_code = ne.site OR s_ep.site_name = ne.site "
                "WHERE ne.is_active = 1 ORDER BY ne.last_seen DESC"
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
        e['switch_name'] = e.get('device_name') or e.get('switch_id') or ''
        # ``site`` is a legacy cache field and may contain an internal site ID.
        # Return the human-readable CMDB site name at the API boundary.
        e['site_id'] = e.get('device_site_id') or ''
        e['site'] = e.get('site_name') or e.get('site') or '未分配站点'
        if 'mac' in e:
            e['mac_display'] = _format_mac(e['mac']) if e['mac'] else '—'
        t = e.get('asset_type', 'host')
        stats[t] = stats.get(t, 0) + 1
        entries.append(e)

    site_stats = {}
    for entry in entries:
        site = entry.get('site') or '未分配站点'
        site_stats[site] = site_stats.get(site, 0) + 1
    return {
        'total': len(entries),
        'type_stats': stats,
        'site_stats': site_stats,
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
                "SELECT inv.ip, inv.mask, inv.device_id, inv.interface, inv.type, inv.last_seen, "
                "d.hostname AS device_name, "
                "COALESCE(s.site_name, s.site_code, NULLIF(d.site, ''), '未分配站点') AS site_name "
                "FROM ip_inventory inv LEFT JOIN devices d ON inv.device_id = d.id "
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
                'ORDER BY inv.last_seen DESC'
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        rows = []

    entries = [dict(row) for row in rows]
    type_stats = {}
    site_stats = {}
    for e in entries:
        t = e.get('type', 'unknown')
        type_stats[t] = type_stats.get(t, 0) + 1
        site = e.get('site_name') or '未分配站点'
        site_stats[site] = site_stats.get(site, 0) + 1

    return {
        'total': len(entries),
        'type_stats': type_stats,
        'site_stats': site_stats,
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
                "SELECT rc.id, rc.device_id, rc.vrf_name, rc.destination, rc.next_hop, rc.protocol, "
                "rc.outgoing_interface, rc.metric, rc.last_updated, d.hostname AS device_name, "
                "COALESCE(s.site_name, s.site_code, NULLIF(d.site, ''), '未分配站点') AS site_name "
                "FROM route_table rc LEFT JOIN devices d ON rc.device_id = d.id "
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
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
            'site_name': row_dict.get('site_name') or '未分配站点',
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
    site_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1
        site = e.get('site_name') or '未分配站点'
        site_stats[site] = site_stats.get(site, 0) + 1

    return {
        'total': len(entries),
        'protocol_stats': proto_stats,
        'device_stats': device_stats,
        'site_stats': site_stats,
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
                "SELECT rn.id, rn.device_id, rn.protocol, rn.neighbor_id, rn.neighbor_ip, "
                "rn.local_interface, rn.state, rn.uptime, rn.local_as, rn.remote_as, rn.area_id, "
                "rn.last_updated, d.hostname AS device_name, "
                "COALESCE(s.site_name, s.site_code, NULLIF(d.site, ''), '未分配站点') AS site_name "
                "FROM routing_neighbors rn LEFT JOIN devices d ON rn.device_id = d.id "
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
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
            'site_name': row_dict.get('site_name') or '未分配站点',
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
    site_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1
        site = e.get('site_name') or '未分配站点'
        site_stats[site] = site_stats.get(site, 0) + 1

    return {
        'total': len(entries),
        'protocol_stats': proto_stats,
        'device_stats': device_stats,
        'site_stats': site_stats,
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
                "SELECT br.id, br.device_id, br.vrf_name, br.prefix, br.next_hop, br.metric, "
                "br.loc_pref, br.weight, br.as_path, br.local_as, br.is_best, br.is_active, "
                "br.last_updated, d.hostname AS device_name, "
                "COALESCE(s.site_name, s.site_code, NULLIF(d.site, ''), '未分配站点') AS site_name "
                "FROM bgp_route_table br LEFT JOIN devices d ON br.device_id = d.id "
                "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, '')) "
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
            'site_name': row_dict.get('site_name') or '未分配站点',
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
    site_stats = {}
    for e in entries:
        dn = e.get('device_name') or e.get('device_id', 'unknown')
        device_stats[dn] = device_stats.get(dn, 0) + 1
        site = e.get('site_name') or '未分配站点'
        site_stats[site] = site_stats.get(site, 0) + 1

    return {
        'total': len(entries),
        'device_stats': device_stats,
        'site_stats': site_stats,
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
    if device_info.get('platform_profile_id'):
        try:
            from services.platform_registry_service import execute_platform_action
            result = execute_platform_action(
                str(device_info['id']),
                'get_ip_interfaces',
                user={
                    'id': f"ip-locator:{device_info.get('id') or 'unknown'}",
                    'username': 'ip-locator',
                    'role': 'Operator',
                    'tenant_id': device_info.get('tenant_id') or '',
                },
            )
            return [
                {
                    'ip': str(record.get('ip_address') or record.get('ip') or '').strip(),
                    'mask': str(record.get('prefix_length') or record.get('mask') or '').strip(),
                    'interface': str(record.get('interface') or record.get('local_interface') or '').strip(),
                    'device_id': device_info.get('id'),
                    'device_name': device_info.get('hostname') or device_info.get('ip_address'),
                }
                for record in (result.get('records') or [] if result.get('success') else [])
                if str(record.get('ip_address') or record.get('ip') or '').strip()
            ]
        except Exception as exc:
            logger.debug("[IP Inventory] Registry interface collection failed: %s", exc)
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
        logger.warning(
            "[IP Inventory] Detailed interface IP collection failed for %s (%s); falling back to brief",
            device_info.get('hostname') or device_info.get('ip_address'),
            type(exc).__name__,
        )
        if platform in ('huawei_vrp', 'h3c_comware'):
            cmd_fallback = 'display ip interface brief'
        else:
            cmd_fallback = 'show ip interface brief'
        try:
            output = _send_command(device_info, cmd_fallback)
            return _parse_brief_interface_ips(output, device_info)
        except Exception as fallback_exc:
            logger.warning(
                "[IP Inventory] Interface IP collection failed for %s (%s)",
                device_info.get('hostname') or device_info.get('ip_address'),
                type(fallback_exc).__name__,
            )
            return []


# ── IP Inventory 同步 ────────────────────────────────────

def _sync_prefixes_from_current_interfaces() -> dict[str, int]:
    """Bridge inventory/full-sync results into automatic Prefix discovery."""
    try:
        conn = get_db_connection()
        try:
            device_rows = conn.execute(
                """
                SELECT DISTINCT i.device_id
                FROM interfaces i
                JOIN devices d ON d.id = i.device_id
                WHERE COALESCE(i.primary_ip, '') <> ''
                   OR COALESCE(i.ip_address, '') <> ''
                ORDER BY i.device_id
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("[Prefix Sync] Unable to load interface snapshots: %s", exc, exc_info=True)
        return {"devices": 0, "created": 0, "updated": 0, "failed": 0}

    from services.prefix_discovery_service import discover_prefixes_from_interface_snapshot

    totals = {"devices": len(device_rows), "created": 0, "updated": 0, "failed": 0}
    run_id = f"ip-inventory-sync-{uuid.uuid4().hex[:12]}"
    for row in device_rows:
        device_id = str(row["device_id"] or "")
        if not device_id:
            continue
        try:
            result = discover_prefixes_from_interface_snapshot(device_id, collection_run_id=run_id)
            totals["created"] += int(result.get("created") or 0)
            totals["updated"] += int(result.get("updated") or 0)
        except Exception as exc:
            totals["failed"] += 1
            logger.warning("[Prefix Sync] Interface snapshot failed for %s: %s", device_id, exc, exc_info=True)
    logger.info(
        "[Prefix Sync] Synced interface snapshots: devices=%d created=%d updated=%d failed=%d",
        totals["devices"], totals["created"], totals["updated"], totals["failed"],
    )
    return totals


def _sync_ip_inventory_impl():
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
            device_record_counts: dict[str, int] = {}
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_collect_device_interface_ips, dev): dev
                    for dev in all_devices
                }
                for future in as_completed(future_map):
                    dev = future_map[future]
                    try:
                        records = future.result()
                        device_ips.extend(records)
                        device_record_counts[dev['id']] = len(records)
                    except Exception as exc:
                        device_record_counts[dev['id']] = 0
                        logger.warning(
                            "[IP Inventory Sync] Device collection failed for %s (%s)",
                            dev.get('hostname') or dev.get('ip_address'),
                            type(exc).__name__,
                        )

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
                    successful_devices = sum(1 for count in device_record_counts.values() if count > 0)
                    logger.info(
                        "[IP Inventory Sync] Phase 2 (Devices): synced %d IPs from %d/%d devices; no usable records from %s",
                        total_device,
                        successful_devices,
                        len(all_devices),
                        ', '.join(
                            dev.get('hostname') or dev.get('ip_address') or dev['id']
                            for dev in all_devices
                            if device_record_counts.get(dev['id'], 0) == 0
                        ) or 'none',
                    )
                finally:
                    conn.close()
    except Exception as e:
        logger.error(f"[IP Inventory Sync] Phase 2 (Devices) failed: {e}")

    logger.info(f"[IP Inventory Sync] Complete — IPAM: {total_ipam}, Devices: {total_device}")


# ── 终端事实库后台同步 ──────────────────────────────────

def sync_ip_inventory():
    """Sync IP inventory and immediately project current interfaces to Prefixes."""
    result = _sync_ip_inventory_impl()
    _sync_prefixes_from_current_interfaces()
    return result


def run_unified_nsot_sync() -> dict[str, Any]:
    """Run the Network Reality refresh as one ordered, auditable workflow.

    Prefix projection deliberately runs after topology/interface collection so
    the final Prefix view uses the same interface snapshot that the CMDB page
    displays, including Loopback interfaces.
    """
    from services.scheduler_service import (
        sync_bgp_routes_job,
        sync_routing_neighbors_job,
        sync_topology_and_interfaces_job,
    )
    from services.interface_collection_service import collect_interface_status_for_online_devices

    topology_result: dict[str, Any] = {}
    interface_status_result: dict[str, Any] = {}
    prefix_result: dict[str, int] = {"devices": 0, "created": 0, "updated": 0, "failed": 0}
    try:
        run_arp_sweep()
        run_endpoint_collector(refresh_arp=False)
        run_route_collector()
        sync_routing_neighbors_job()
        sync_bgp_routes_job()
        topology_result = sync_topology_and_interfaces_job() or {}
        interface_status_result = collect_interface_status_for_online_devices()
    finally:
        # Even if an auxiliary collector fails, the interface/IPAM projection
        # must run against the newest interface snapshot that is available.
        prefix_result = _sync_prefixes_from_current_interfaces()
    return {
        "topology": topology_result if isinstance(topology_result, dict) else {},
        "interface_status": interface_status_result,
        "prefixes": prefix_result,
    }


def run_endpoint_collector(*, refresh_arp: bool = True):
    """
    后台终端事实库同步任务：
    1. 触发 ARP Sweep 以确保本地 ARP 缓存最新。
    2. 获取所有的在线交换机设备，并发采集其完整的 MAC 地址表。
    3. 获取所有的 LLDP 拓扑连接，构建上联口白名单。
    4. 对比 ARP 和 MAC，找出每个活跃 IP 的最佳接入端口，写入 network_endpoints 表。
    5. 同步 IP Inventory 表。
    """
    logger.info("[Endpoint Collector] Starting endpoint cache sync...")
    t0 = time.time()

    # 1. 确保 ARP 缓存最新
    if refresh_arp:
        try:
            run_arp_sweep()
        except Exception as e:
            logger.error(f"[Endpoint Collector] ARP sweep failed: {e}")

    arp_data = get_arp_table()
    arp_entries = arp_data.get('entries', [])
    if not arp_entries:
        logger.info("[Endpoint Collector] No active ARP entries found; continuing with eligible L2 MAC collection.")

    # 2. 获取所有在线交换机
    all_eligible = _load_eligible_devices()
    _MAC_EXCLUDED_ROLES = frozenset({'router', 'firewall', 'gateway', 'server', 'linux', 'windows'})
    switch_devices = [d for d in filter_devices(all_eligible, "mac_table") if should_collect(d, "endpoint_location")]
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

    # 3. 收集 LLDP 邻居以判定上联口
    conn = get_db_connection()
    uplink_ports = set()
    interface_modes: dict[tuple[str, str], str] = {}
    try:
        rows = conn.execute("SELECT source_device_id, source_port, target_device_id, target_port FROM topology_links").fetchall()
        for r in rows:
            if r['source_device_id'] and r['source_port']:
                uplink_ports.add((r['source_device_id'], normalize_interface_name(r['source_port']).lower()))
            if r['target_device_id'] and r['target_port']:
                uplink_ports.add((r['target_device_id'], normalize_interface_name(r['target_port']).lower()))
        interface_rows = conn.execute(
            "SELECT device_id, interface_name, switchport_mode FROM interfaces"
        ).fetchall()
        for row in interface_rows:
            key = (str(row['device_id'] or ''), normalize_interface_name(row['interface_name']).lower())
            interface_modes[key] = str(row['switchport_mode'] or '').strip().lower()
    except Exception as e:
        logger.debug(f"[Endpoint Collector] Error querying topology links: {e}")
    finally:
        conn.close()

    # 4. 对比匹配
    mac_counts: dict[tuple[str, str], int] = {}
    for item in all_mac_records:
        key = (str(item.get('switch_id') or ''), normalize_interface_name(item.get('port')).lower())
        mac_counts[key] = mac_counts.get(key, 0) + 1

    mac_to_locations = {}
    for rec in all_mac_records:
        mac = rec['mac']
        switch_id = rec['switch_id']
        port_norm = normalize_interface_name(rec['port']).lower()

        mode = interface_modes.get((str(switch_id), port_norm), '')
        is_bundle = any(kw in port_norm for kw in ('po', 'port-channel', 'lag', 'eth-trunk'))
        is_trunk = mode in {'trunk', 'tagged', 'hybrid'}
        is_access_with_single_mac = mode in {'access', 'untagged'} and mac_counts.get((str(switch_id), port_norm), 0) <= 1
        is_uplink = (switch_id, port_norm) in uplink_ports or is_bundle or (is_trunk and not is_access_with_single_mac)
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


def run_endpoint_fact_collector() -> None:
    """Refresh MAC/interface endpoint facts using the latest ARP snapshot."""
    run_endpoint_collector(refresh_arp=False)


# ── 路由表解析与采集 ─────────────────────────────────────

def _int_to_netmask(prefix_len: int) -> str:
    """把前缀长度 (0-32) 转换为子网掩码字符串。"""
    mask = (0xffffffff >> (32 - prefix_len)) << (32 - prefix_len)
    return f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"


_ROUTE_PROTOCOL_ALIASES = {
    'c': 'connected', 'connected': 'connected', 'direct': 'connected',
    'directly connected': 'connected', 'l': 'local', 'local': 'local',
    's': 'static', 'static': 'static', 'p': 'periodic_static',
    'periodic static': 'periodic_static', 'u': 'user_static',
    'user static': 'user_static', 'o': 'ospf', 'ospf': 'ospf',
    'b': 'bgp', 'bgp': 'bgp', 'ebgp': 'bgp', 'ibgp': 'bgp',
    'd': 'eigrp', 'eigrp': 'eigrp',
    'r': 'rip', 'rip': 'rip', 'i': 'isis', 'isis': 'isis',
    'is-is': 'isis', 'h': 'nhrp', 'nhrp': 'nhrp', 'lisp': 'lisp',
    'a': 'application', 'application': 'application',
}


def normalize_route_protocol(value: object) -> str:
    """Map Cisco codes and vendor protocol names to one canonical value."""
    raw = re.sub(r'[^a-z0-9 -]+', ' ', str(value or '').strip().lower())
    raw = re.sub(r'\s+', ' ', raw).strip()
    if not raw:
        return 'unknown'
    base = raw.split()[0]
    return _ROUTE_PROTOCOL_ALIASES.get(raw, _ROUTE_PROTOCOL_ALIASES.get(base, base))


def parse_routing_table(output: str, platform: str) -> list[dict]:
    """解析完整的 show ip route / display ip routing-table 输出，提取前缀、掩码、下一跳、出接口和协议类型。"""
    platform = platform.lower()
    routes = []

    # ── Huawei/H3C ──
    if any(p in platform for p in ('huawei', 'vrp', 'comware', 'h3c', 'hp')):
        current_destination = ''
        for line in output.splitlines():
            tokens = line.split()
            if not tokens:
                continue

            # VRP5/VRP8 tabular output has either a destination column or a
            # blank continuation row for ECMP routes. Keep the last
            # destination so all routes in the table reach NSOT.
            if '/' in tokens[0] and re.match(r'^\d+\.\d+\.\d+\.\d+/\d+$', tokens[0]):
                destination = tokens[0]
                fields = tokens[1:]
                current_destination = destination
            else:
                destination = current_destination
                fields = tokens
            if not destination or len(fields) < 6:
                continue

            proto, preference, cost, _flags, next_hop, interface = fields[:6]
            if not preference.isdigit() or not cost.isdigit():
                continue
            dest, mask_len_str = destination.split('/', 1)
            netmask = _int_to_netmask(int(mask_len_str))
            routes.append({
                'prefix': dest,
                'mask': netmask,
                'next_hop': "directly connected" if proto.lower() == 'direct' else next_hop,
                'protocol': normalize_route_protocol(proto),
                'interface': interface,
                'metric': int(cost),
                'preference': int(preference),
            })
        return routes

    # ── Juniper ──
    if 'juniper' in platform or 'junos' in platform:
        current_dest = None
        current_mask = None
        current_protocol = 'static'
        for line in output.splitlines():
            m_dest = re.search(r'(\d+\.\d+\.\d+\.\d+)/(\d+)', line)
            if m_dest:
                current_dest = m_dest.group(1)
                current_mask = _int_to_netmask(int(m_dest.group(2)))
                protocol_match = re.search(r'\*\[\s*([^/\]]+)', line)
                current_protocol = normalize_route_protocol(
                    protocol_match.group(1) if protocol_match else 'static'
                )
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
                        'protocol': current_protocol,
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
            r'^(?P<proto>[A-Za-z])\*?(?:\s+(?P<qualifier>IA|EX2|E2|E1|L1|L2))?\s+'
            r'(?P<dest>\d+\.\d+\.\d+\.\d+)(?P<mask_len_part>/\d+)?',
            line
        )
        if m_route:
            gd = m_route.groupdict()
            proto = normalize_route_protocol(
                f"{gd['proto']} {gd.get('qualifier') or ''}"
            )
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
    if dev.get('platform_profile_id'):
        configured = dev.get('vrf') or dev.get('vrf_name')
        return [str(configured).strip()] if configured else ['default']
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
    _L3_ROLES = {'router', 'gateway', 'core', 'dist', 'distribution', 'aggregation', 'l3switch'}
    route_devices = [
        d for d in filter_devices(all_eligible, "routes")
        if (d.get('role') or '').lower().strip() in _L3_ROLES
    ]

    if not route_devices:
        logger.info("[Route Collector] No eligible L3 routing devices found.")
        return

    workers = min(5, len(route_devices))
    all_routes_to_save = []

    def collect_device_routes(dev: dict) -> list[dict]:
        if dev.get('platform_profile_id'):
            from services.platform_registry_service import execute_platform_action
            registry_user = {
                'id': f"route-collector:{dev.get('id')}",
                'username': 'route-collector',
                'role': 'Operator',
                'tenant_id': dev.get('tenant_id') or '',
            }
            vrfs = [str(dev.get('vrf') or 'default')]
            all_device_routes: list[dict] = []
            for vrf in vrfs:
                action_code = 'get_route_table_vrf' if vrf != 'default' else 'get_route_table'
                try:
                    result = execute_platform_action(
                        str(dev['id']), action_code,
                        user=registry_user,
                        parameters={'vrf': vrf} if vrf != 'default' else None,
                    )
                    for record in result.get('records') or [] if result.get('success') else []:
                        prefix = str(record.get('prefix') or record.get('destination') or '').strip()
                        if not prefix:
                            continue
                        all_device_routes.append({
                            'device_id': dev['id'],
                            'vrf_name': vrf,
                            'prefix': prefix.split('/', 1)[0],
                            'mask': prefix.split('/', 1)[1] if '/' in prefix else '',
                            'next_hop': str(record.get('next_hop') or record.get('nexthop') or '').strip(),
                            'protocol': str(record.get('protocol') or record.get('route_type') or '').strip(),
                            'interface': str(record.get('interface') or record.get('outgoing_interface') or '').strip(),
                            'metric': record.get('metric') or 0,
                            'preference': record.get('preference'),
                        })
                except Exception as exc:
                    logger.debug(
                        "[Route Collector] Registry route collection failed for %s/%s: %s",
                        dev.get('hostname') or dev.get('ip_address'), vrf, exc,
                    )
            return all_device_routes

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
                if any(p in platform for p in ('huawei', 'vrp', 'comware', 'h3c', 'hp')):
                    cmd = "display ip routing-table"
                elif platform in ('juniper_junos',):
                    cmd = "show route"
                else:
                    cmd = "show ip route"
            else:
                if any(p in platform for p in ('huawei', 'vrp', 'comware', 'h3c', 'hp')):
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
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
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
                    
                    pref_val = r.get('preference')
                    try:
                        pref_val = int(pref_val) if pref_val not in (None, '') else None
                    except (TypeError, ValueError):
                        pref_val = None
                    if pref_val is None:
                        pref_val = 1
                        proto_lower = (r.get('protocol') or '').lower()
                        if proto_lower in {'connected', 'local'}:
                            pref_val = 0
                        elif proto_lower in {'static', 'periodic_static', 'user_static'}:
                            pref_val = 1
                        elif proto_lower == 'eigrp':
                            pref_val = 90
                        elif proto_lower == 'ospf':
                            pref_val = 110
                        elif proto_lower == 'isis':
                            pref_val = 115
                        elif proto_lower == 'rip':
                            pref_val = 120
                        elif proto_lower == 'bgp':
                            pref_val = 200

                    conn.execute(
                        '''INSERT INTO route_table (
                            id, device_id, vrf_name, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)''',
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
