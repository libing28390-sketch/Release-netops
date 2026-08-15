"""
Connectivity Probe Service — 全链路连通性探测（PING + TCP + Traceroute）

支持两种模式:
1. 服务器侧探测：从 NetOps 后端直接 PING/TCP/Traceroute 目标 IP
2. 设备侧探测：SSH 到指定设备执行 ping/traceroute/telnet，解析输出
"""

import asyncio
import logging
import platform
import re
import socket
import subprocess
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from database import get_db_connection
from core.crypto import decrypt_credential
from services.vault_service import resolve_device_credentials
from services.operational_data_service import collect_operational_data

logger = logging.getLogger(__name__)


_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')


# ──────────────────────────────────────────────
# 服务器侧探测
# ──────────────────────────────────────────────

def _server_ping(target: str, count: int = 4, timeout: int = 3) -> dict[str, Any]:
    """从服务器发起 ICMP ping。"""
    is_win = platform.system().lower() == 'windows'
    cmd = ['ping', '-n' if is_win else '-c', str(count),
           '-w' if is_win else '-W', str(timeout * (1000 if is_win else 1)),
           target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=count * timeout + 5)
        output = proc.stdout + proc.stderr

        # 解析丢包率
        loss_match = re.search(r'(\d+)%\s*(loss|丢失|packet loss)', output, re.I)
        loss_pct = int(loss_match.group(1)) if loss_match else 100

        # 解析延迟 (Windows: min/max/avg, Linux: min/avg/max/mdev)
        rtt = {}
        if is_win:
            m = re.search(r'Minimum\s*=\s*(\d+)\s*ms.*Maximum\s*=\s*(\d+)\s*ms.*Average\s*=\s*(\d+)\s*ms', output, re.I)
            if not m:
                m = re.search(r'最短\s*=\s*(\d+)\s*ms.*最长\s*=\s*(\d+)\s*ms.*平均\s*=\s*(\d+)\s*ms', output, re.I)
            if m:
                rtt = {'min': int(m.group(1)), 'max': int(m.group(2)), 'avg': int(m.group(3))}
        else:
            m = re.search(r'([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms', output)
            if m:
                rtt = {'min': float(m.group(1)), 'avg': float(m.group(2)), 'max': float(m.group(3))}

        return {
            'success': loss_pct < 100,
            'loss_percent': loss_pct,
            'rtt': rtt,
            'output': output.strip(),
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'loss_percent': 100, 'rtt': {}, 'output': 'Ping timed out'}
    except Exception as exc:
        return {'success': False, 'loss_percent': 100, 'rtt': {}, 'output': str(exc)}


def _server_tcp(target: str, port: int, timeout: int = 3) -> dict[str, Any]:
    """从服务器发起 TCP 连接探测。"""
    start = time.monotonic()
    try:
        # Close the probe socket even when DNS/connect raises an exception.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            result_code = s.connect_ex((target, port))
            elapsed = round((time.monotonic() - start) * 1000, 1)

        if result_code == 0:
            return {'success': True, 'port': port, 'latency_ms': elapsed, 'detail': 'Connection established'}
        else:
            return {'success': False, 'port': port, 'latency_ms': elapsed, 'detail': f'Connection failed (errno={result_code})'}
    except socket.timeout:
        elapsed = round((time.monotonic() - start) * 1000, 1)
        return {'success': False, 'port': port, 'latency_ms': elapsed, 'detail': 'Connection timed out'}
    except socket.gaierror:
        return {'success': False, 'port': port, 'latency_ms': 0, 'detail': 'DNS resolution failed'}
    except Exception as exc:
        elapsed = round((time.monotonic() - start) * 1000, 1)
        return {'success': False, 'port': port, 'latency_ms': elapsed, 'detail': str(exc)}


def _server_traceroute(target: str, max_hops: int = 15, timeout: int = 3) -> dict[str, Any]:
    """从服务器发起 traceroute。"""
    is_win = platform.system().lower() == 'windows'
    if is_win:
        cmd = ['tracert', '-d', '-h', str(max_hops), '-w', str(timeout * 1000), target]
    else:
        cmd = ['traceroute', '-n', '-m', str(max_hops), '-w', str(timeout), target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * timeout + 10)
        output = proc.stdout + proc.stderr

        # 解析跳数
        hops = []
        for line in output.splitlines():
            m = re.match(r'\s*(\d+)\s+(.+)', line)
            if m:
                hop_num = int(m.group(1))
                rest = m.group(2).strip()
                # 尝试提取 IP
                ips = re.findall(r'(\d+\.\d+\.\d+\.\d+)', rest)
                # 提取延迟
                rtts = re.findall(r'(\d+)\s*ms', rest)
                is_timeout = '*' in rest and not ips
                hops.append({
                    'hop': hop_num,
                    'ip': ips[0] if ips else '*',
                    'rtt_ms': [int(r) for r in rtts] if rtts else [],
                    'timeout': is_timeout,
                })

        return {
            'success': len(hops) > 0,
            'hops': hops,
            'output': output.strip(),
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'hops': [], 'output': 'Traceroute timed out'}
    except Exception as exc:
        return {'success': False, 'hops': [], 'output': str(exc)}


# ──────────────────────────────────────────────
# 设备侧探测
# ──────────────────────────────────────────────

def _load_device(device_id: str | int) -> dict | None:
    """加载设备信息并解密密码。"""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, asset_id, hostname, ip_address, platform, username, password, enable_password, priv_username, management_port AS port, credential_source, vault_path, cpu_usage, memory_usage, "
            "platform_profile_id, platform_source, platform_locked, tenant_id, site_id, site, device_group_id "
            "FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d['device_type'] = d.get('platform') or 'cisco_ios'
        creds = resolve_device_credentials(d)
        d['username'] = creds.get('normal_username') or ''
        d['password'] = creds.get('normal_password') or ''
        d['enable_password'] = creds['enable_password']
        return d
    finally:
        conn.close()


def _build_device_info(dev: dict) -> dict:
    """构建 netmiko/scrapli 设备连接字典。"""
    return {
        'id': dev['id'],
        'hostname': dev.get('hostname') or dev.get('ip_address'),
        'ip_address': dev['ip_address'],
        'device_type': dev.get('device_type', 'cisco_ios'),
        'platform': dev.get('platform') or dev.get('device_type') or 'cisco_ios',
        'username': dev.get('username', ''),
        'password': dev.get('password', ''),
        'enable_password': dev.get('enable_password', ''),
        'port': dev.get('port') or dev.get('management_port') or 22,
        'platform_profile_id': dev.get('platform_profile_id'),
        'platform_source': dev.get('platform_source'),
        'platform_locked': dev.get('platform_locked'),
        'tenant_id': dev.get('tenant_id'),
        'site_id': dev.get('site_id') or dev.get('site'),
        'device_group_id': dev.get('device_group_id'),
    }


def _device_ping(device_info: dict, target: str, count: int = 4, source: str = '') -> dict[str, Any]:
    if device_info.get('platform_profile_id'):
        # The registry does not currently publish a ping action. Fail closed
        # instead of sending an arbitrary command to a bound device.
        raise ValueError('platform_registry:UNSUPPORTED_ACTION: ping is not a published platform action')
    """通过 SSH 到设备执行 ping 命令，解析结果。"""
    dtype = (device_info.get('device_type') or '').lower()
    ip = device_info.get('ip_address', '')

    # 构建命令
    if 'huawei' in dtype or 'vrp' in dtype:
        cmd = f'ping -c {count} {target}'
        if source:
            cmd = f'ping -c {count} -a {source} {target}'
    elif 'h3c' in dtype or 'comware' in dtype:
        cmd = f'ping -c {count} {target}'
        if source:
            cmd = f'ping -c {count} -a {source} {target}'
    else:
        # Cisco IOS / IOS-XE / NX-OS / Arista / Juniper
        cmd = f'ping {target} repeat {count}'
        if source:
            cmd = f'ping {target} repeat {count} source {source}'

    try:
        from services.automation_service import AutomationService
        svc = AutomationService()
        # Avoid using connection pool for transient connectivity tests
        device_info_run = {**device_info, 'use_pool': False}
        results = svc.execute_commands(device_info_run, [cmd])
        if results and results[0].get('success'):
            output = results[0].get('output') or results[0].get('stdout') or ''
        else:
            err = (results[0].get('error') or results[0].get('stderr') or 'Connection failed') if results else 'Connection failed'
            raise Exception(err)

        # 解析丢包率
        loss_match = re.search(r'(\d+)\s*(%|percent)\s*(loss|packet loss|丢失)', output, re.I)
        loss_pct = int(loss_match.group(1)) if loss_match else None

        # 解析成功率 (Cisco 格式: Success rate is 100 percent)
        if loss_pct is None:
            sr = re.search(r'Success rate is (\d+) percent', output, re.I)
            if sr:
                loss_pct = 100 - int(sr.group(1))

        if loss_pct is None:
            loss_pct = 100 if 'timeout' in output.lower() or '!!!' not in output else 0

        # 解析 RTT
        rtt: dict[str, Any] = {}
        m = re.search(r'([\d.]+)/([\d.]+)/([\d.]+)', output)
        if m:
            rtt = {'min': float(m.group(1)), 'avg': float(m.group(2)), 'max': float(m.group(3))}

        return {
            'success': loss_pct < 100,
            'loss_percent': loss_pct,
            'rtt': rtt,
            'output': output.strip(),
            'device': device_info.get('hostname') or ip,
        }
    except Exception as exc:
        logger.debug(f"[ConnProbe] device ping from {ip} failed: {exc}")
        return {
            'success': False,
            'loss_percent': 100,
            'rtt': {},
            'output': str(exc),
            'device': device_info.get('hostname') or ip,
        }


def _device_traceroute(device_info: dict, target: str, source: str = '') -> dict[str, Any]:
    if device_info.get('platform_profile_id'):
        raise ValueError('platform_registry:UNSUPPORTED_ACTION: traceroute is not a published platform action')
    """通过 SSH 到设备执行 traceroute 命令。"""
    dtype = (device_info.get('device_type') or '').lower()
    ip = device_info.get('ip_address', '')

    if 'huawei' in dtype or 'vrp' in dtype:
        cmd = f'tracert -q 1 {target}'
        if source:
            cmd = f'tracert -q 1 -a {source} {target}'
    elif 'h3c' in dtype or 'comware' in dtype:
        cmd = f'tracert -q 1 {target}'
    else:
        cmd = f'traceroute {target}'
        if source:
            cmd = f'traceroute {target} source {source}'

    try:
        from services.automation_service import AutomationService
        svc = AutomationService()
        # Avoid using connection pool for transient connectivity tests
        device_info_run = {**device_info, 'use_pool': False}
        results = svc.execute_commands(device_info_run, [cmd])
        if results and results[0].get('success'):
            output = results[0].get('output') or results[0].get('stdout') or ''
        else:
            err = (results[0].get('error') or results[0].get('stderr') or 'Connection failed') if results else 'Connection failed'
            raise Exception(err)

        hops = []
        for line in output.splitlines():
            m = re.match(r'\s*(\d+)\s+(.+)', line)
            if m:
                hop_num = int(m.group(1))
                rest = m.group(2).strip()
                ips = re.findall(r'(\d+\.\d+\.\d+\.\d+)', rest)
                rtts = re.findall(r'(\d+)\s*ms', rest)
                hops.append({
                    'hop': hop_num,
                    'ip': ips[0] if ips else '*',
                    'rtt_ms': [int(r) for r in rtts] if rtts else [],
                    'timeout': '*' in rest and not ips,
                })

        return {
            'success': len(hops) > 0,
            'hops': hops,
            'output': output.strip(),
            'device': device_info.get('hostname') or ip,
        }
    except Exception as exc:
        logger.debug(f"[ConnProbe] device traceroute from {ip} failed: {exc}")
        return {
            'success': False,
            'hops': [],
            'output': str(exc),
            'device': device_info.get('hostname') or ip,
        }


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def run_probe(
    target: str,
    tests: list[str] | None = None,
    tcp_ports: list[int] | None = None,
    source_device_id: str | int | None = None,
    source_interface: str = '',
    ping_count: int = 4,
) -> dict[str, Any]:
    """
    执行连通性探测。

    Args:
        target: 目标 IP 地址
        tests: 要执行的测试类型列表，可选 ['ping', 'tcp', 'traceroute']
        tcp_ports: TCP 端口列表，如 [22, 80, 443]
        source_device_id: 如果提供，从该设备发起探测（设备侧模式）
        source_interface: 设备侧 ping/traceroute 的源接口/IP
        ping_count: PING 次数
    """
    if tests is None:
        tests = ['ping', 'tcp', 'traceroute']
    if tcp_ports is None:
        tcp_ports = [22, 80, 443]

    result: dict[str, Any] = {
        'target': target,
        'mode': 'device' if source_device_id else 'server',
        'source_device': None,
        'timestamp': _beijing_now_iso(),
        'tests': {},
    }

    device_info: dict | None = None
    if source_device_id:
        dev = _load_device(source_device_id)
        if dev:
            device_info = _build_device_info(dev)
            result['source_device'] = device_info.get('hostname') or device_info.get('ip_address')
        else:
            result['tests']['error'] = f'Device ID {source_device_id} not found'
            return result

    # ── PING ──
    if 'ping' in tests:
        if device_info:
            result['tests']['ping'] = _device_ping(device_info, target, count=ping_count, source=source_interface)
        else:
            result['tests']['ping'] = _server_ping(target, count=ping_count)

    # ── TCP ──
    if 'tcp' in tests and tcp_ports:
        tcp_results = []
        for port in tcp_ports[:10]:  # 最多 10 个端口
            tcp_results.append(_server_tcp(target, port))
        result['tests']['tcp'] = tcp_results

    # ── Traceroute ──
    if 'traceroute' in tests:
        if device_info:
            result['tests']['traceroute'] = _device_traceroute(device_info, target, source=source_interface)
        else:
            result['tests']['traceroute'] = _server_traceroute(target)

    return result


async def run_probe_async(
    target: str,
    tests: list[str] | None = None,
    tcp_ports: list[int] | None = None,
    source_device_id: str | int | None = None,
    source_interface: str = '',
    ping_count: int = 4,
) -> dict[str, Any]:
    """异步包装，在线程池中执行阻塞的探测操作。"""
    return await asyncio.to_thread(
        run_probe, target, tests, tcp_ports,
        source_device_id, source_interface, ping_count,
    )
