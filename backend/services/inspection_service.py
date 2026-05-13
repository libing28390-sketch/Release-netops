"""
Device Inspection Service — 设备巡检引擎

支持:
- 手动触发巡检（单台/批量/全网）
- 定时巡检计划（cron 表达式）
- 分层连通性验证（ICMP → SSH）
- 服务器：Shell 脚本执行 + 数值提取
- 网络设备：CLI 采集 + TextFSM 结构化解析 + 阈值/计数/对比判定
- 合规检查集成
- 结构化巡检报告
"""

import json
import logging
import platform
import re
import socket
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection
from services.device_health_service import (
    evaluate_device_health,
    _build_open_alert_stats,
)
from core.textfsm import parse_with_textfsm
from core.analysis import analyze_device_inspection, summarize_run_analysis


logger = logging.getLogger(__name__)

_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_CONCURRENT = 20          # 同时巡检的设备数（提升至 20）
_SSH_CONNECT_TIMEOUT = 15     # SSH 建立超时
_SSH_COMMAND_TIMEOUT = 30     # 单条命令超时

# 识别为"网络设备"的 platform（走 NetmikoDriver CLI 采集）
_NETWORK_PLATFORMS = {
    'cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd',
    'huawei_vrp', 'huawei_vrpv8', 'huawei',
    'h3c_comware', 'hp_comware',
    'juniper_junos', 'juniper',
    'arista_eos',
    'paloalto_panos', 'fortinet', 'checkpoint_gaia',
    'hillstone_stoneos', 'ruijie_os', 'zte_zxros',
}

# 识别为"服务器/Linux 主机"的 platform（走 Shell 脚本采集）
_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat', 'Linux'}


def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ──────────────────────────────────────────────
# 连通性探测
# ──────────────────────────────────────────────

def _ping_device(ip: str, count: int = 3, timeout: int = 2) -> dict[str, Any]:
    is_win = platform.system().lower() == 'windows'
    cmd = ['ping', '-n' if is_win else '-c', str(count),
           '-w' if is_win else '-W', str(timeout * (1000 if is_win else 1)), ip]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=count * timeout + 5)
        output = proc.stdout + proc.stderr
        loss_match = re.search(r'(\d+)%\s*(loss|丢失|packet loss)', output, re.I)
        loss_pct = int(loss_match.group(1)) if loss_match else 100

        rtt_avg = None
        if is_win:
            m = re.search(r'(Average|平均)\s*=\s*(\d+)\s*ms', output, re.I)
            if m:
                rtt_avg = float(m.group(2))
        else:
            m = re.search(r'([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms', output)
            if m:
                rtt_avg = float(m.group(2))

        return {'success': loss_pct < 100, 'latency_ms': rtt_avg, 'loss_percent': loss_pct}
    except Exception:
        return {'success': False, 'latency_ms': None, 'loss_percent': 100}


def _check_ssh(ip: str, port: int = 22, timeout: int = 3) -> dict[str, Any]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        start = time.monotonic()
        result_code = s.connect_ex((ip, port))
        elapsed = round((time.monotonic() - start) * 1000, 1)
        s.close()
        return {'success': result_code == 0, 'latency_ms': elapsed, 'error': '' if result_code == 0 else f'errno={result_code}'}
    except socket.timeout:
        return {'success': False, 'latency_ms': None, 'error': 'connection timed out'}
    except Exception as exc:
        return {'success': False, 'latency_ms': None, 'error': str(exc)}


# ──────────────────────────────────────────────
# 单台设备巡检
# ──────────────────────────────────────────────

def _execute_shell_script(ip: str, script_content: str, device: dict) -> str:
    """真实执行 Shell 脚本并返回输出"""
    import paramiko
    try:
        username = device.get('username') or 'root'
        # 获取解密后的密码 (假设系统中已有加密处理逻辑，此处简写)
        password = device.get('password') or ''
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=username, password=password, timeout=10)
        stdin, stdout, stderr = ssh.exec_command(script_content)
        output = stdout.read().decode('utf-8', errors='ignore').strip()
        ssh.close()
        return output
    except Exception as e:
        return f"ERROR: {str(e)}"

def _extract_numeric_value(output: str) -> float | None:
    """从输出中提取最后一个数字结果"""
    if not output or "ERROR" in output: return None
    lines = output.split('\n')
    for line in reversed(lines):
        line = line.strip()
        if not line: continue
        # 寻找数字，支持 85.5% -> 85.5
        match = re.search(r"([-+]?\d*\.\d+|\d+)", line)
        if match:
            try: return float(match.group(1))
            except: continue
    return None


# ══════════════════════════════════════════════════════════════════
# 网络设备 CLI 巡检（Netmiko + TextFSM）
# ══════════════════════════════════════════════════════════════════

def _netmiko_platform_type(platform: str) -> str:
    """将平台名映射到 Netmiko device_type。"""
    mapping = {
        'cisco_ios': 'cisco_ios',
        'cisco_nxos': 'cisco_nxos',
        'cisco_xr': 'cisco_xr',
        'cisco_asa': 'cisco_asa',
        'cisco_ftd': 'cisco_ftd',
        'huawei_vrp': 'huawei',
        'huawei_vrpv8': 'huawei_vrpv8',
        'huawei': 'huawei',
        'h3c_comware': 'hp_comware',
        'hp_comware': 'hp_comware',
        'juniper_junos': 'juniper_junos',
        'juniper': 'juniper_junos',
        'arista_eos': 'arista_eos',
        'paloalto_panos': 'paloalto_panos',
        'fortinet': 'fortinet',
        'checkpoint_gaia': 'checkpoint_gaia',
        'hillstone_stoneos': 'hillstone_stoneos',
        'ruijie_os': 'ruijie_os',
        'zte_zxros': 'zte_zxros',
    }
    return mapping.get(platform, 'cisco_ios')


def _netmiko_collect(device: dict[str, Any], commands: list[str]) -> dict[str, str]:
    """
    一次 SSH 连接执行多条命令，返回 {command: output} 字典。
    命令失败单条用 '__ERROR__: xxx' 标记，整体连接失败抛异常。
    """
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs
    from core.crypto import decrypt_credential

    platform = (device.get('platform') or 'cisco_ios').lower()
    is_slow = platform in {'huawei_vrp', 'huawei_vrpv8', 'h3c_comware', 'hp_comware'}

    # 凭据解密 — 与 scheduler_service 保持一致的多级回退策略
    # 优先 normal → 回退 username → 最终 admin
    normal_user = (device.get('normal_username') or '').strip()
    normal_pass = (device.get('normal_password') or '').strip()
    if normal_user and normal_pass:
        username = normal_user
        try:
            password = decrypt_credential(normal_pass) or normal_pass
        except Exception:
            password = normal_pass
    else:
        username = (device.get('username') or '').strip()
        raw_password = (device.get('password') or '').strip()
        if not username or not raw_password:
            username = (device.get('admin_username') or '').strip() or username
            raw_password = (device.get('admin_password') or '').strip() or raw_password
        try:
            password = decrypt_credential(raw_password) or raw_password
        except Exception:
            password = raw_password

    params = {
        'device_type': _netmiko_platform_type(platform),
        'host': device.get('ip_address'),
        'username': username,
        'password': password,
        'port': int(device.get('port') or device.get('management_port') or 22),
        'timeout': _SSH_CONNECT_TIMEOUT,
        'session_timeout': 60,
        'fast_cli': not is_slow,
        'global_delay_factor': 1.5 if is_slow else 0.5,
        'blocking_timeout': 30,
    }
    params.update(build_netmiko_compatibility_kwargs())

    secret = device.get('enable_password') or device.get('secret') or ''
    if secret:
        try:
            params['secret'] = decrypt_credential(secret) or secret
        except Exception:
            params['secret'] = secret

    results: dict[str, str] = {}
    try:
        with ConnectHandler(**params) as conn:
            # ── Cisco 系列：智能 enable 提权 ─────────────────────────────
            # 三种场景自适应：
            # 1. 账号已经是 privilege 15 → 提示符 '#' → 跳过 enable()
            # 2. 账号是 privilege 1 → 提示符 '>' → 调用 enable()
            #    a. 设备配置了 enable secret → 用 secret 提权
            #    b. 设备配置了 'aaa authentication enable default none' → 无需密码
            #    c. 两者都没配 → enable 失败，抛警告但不阻断（后续 show 命令可能仍可执行）
            if params['device_type'] in ('cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa'):
                try:
                    prompt = conn.find_prompt()
                    if prompt.strip().endswith('>'):
                        # 需要 enable 提权
                        try:
                            conn.enable()
                        except Exception as en_err:
                            logger.warning(
                                f"[Inspection] Enable mode failed for {device.get('hostname') or device.get('ip_address')}: {en_err}. "
                                f"Continuing with user exec mode — some show commands may be denied. "
                                f"If you need full access, configure either 'enable secret' or "
                                f"'aaa authentication enable default none' on the device."
                            )
                    # 已经是 '#'（privilege 15）则跳过，nothing to do
                except Exception as prompt_err:
                    # 读取提示符失败，尝试盲 enable（兼容某些设备 find_prompt 超时）
                    logger.debug(f"[Inspection] find_prompt failed, trying blind enable(): {prompt_err}")
                    try:
                        conn.enable()
                    except Exception:
                        pass

            for cmd in commands:
                try:
                    output = conn.send_command(
                        cmd,
                        cmd_verify=False,
                        strip_prompt=True,
                        strip_command=True,
                        read_timeout=_SSH_COMMAND_TIMEOUT,
                    )
                    results[cmd] = output
                except Exception as ce:
                    results[cmd] = f"__ERROR__: {ce}"
    except NetmikoAuthenticationException as e:
        raise RuntimeError(f"SSH 认证失败: {e}") from e
    except NetmikoTimeoutException as e:
        raise RuntimeError(f"SSH 连接超时: {e}") from e
    except Exception as e:
        raise RuntimeError(f"SSH 连接失败: {e}") from e

    return results


def _apply_parse_filter(records: list[dict], parse_filter_json: str) -> list[dict]:
    """
    应用 parse_filter JSON 条件过滤记录。
    支持 op: ==, !=, >, <, >=, <=, in, not_in, not_numeric
    """
    if not parse_filter_json or not records:
        return records
    try:
        cond = json.loads(parse_filter_json)
    except Exception:
        return records

    field = cond.get('field') or ''
    op = cond.get('op') or '=='
    value = cond.get('value')

    def _match(row: dict) -> bool:
        rv = row.get(field)
        if op == '==':
            return str(rv) == str(value)
        if op == '!=':
            return str(rv) != str(value)
        if op == 'in':
            return str(rv) in (value or [])
        if op == 'not_in':
            return str(rv) not in (value or [])
        if op == 'not_numeric':
            try:
                float(str(rv))
                return False
            except Exception:
                return True
        if op in ('>', '<', '>=', '<='):
            try:
                rvn = float(rv)
                vn = float(value)
            except Exception:
                return False
            return {'>': rvn > vn, '<': rvn < vn, '>=': rvn >= vn, '<=': rvn <= vn}[op]
        return True

    return [r for r in records if _match(r)]


def _extract_item_value(item: dict, raw_outputs: dict[str, str]) -> tuple[Any, str]:
    """
    根据指标定义从原始输出中提取值。
    返回 (value, error_msg)：成功时 error_msg 为空串。

    parse_type 含义：
      numeric — 返回第一条记录的 parse_field 字段（转 float）
      status  — 返回第一条记录的 parse_field 字段（字符串）
      count   — 返回满足 parse_filter 的记录数（int）
      diff    — 同 numeric，由上层与历史对比
      info    — 返回第一条记录的 parse_field 字段（原值）
    """
    command = item.get('command') or ''
    parse_type = (item.get('parse_type') or 'numeric').lower()
    parse_field = item.get('parse_field') or ''
    parse_filter = item.get('parse_filter') or ''
    textfsm_template = item.get('textfsm_template') or ''
    fallback_regex = item.get('fallback_regex') or ''
    platform_vendor = (item.get('vendor') or '').lower()

    # 1. 找到命令对应的原始输出
    raw = raw_outputs.get(command)
    if raw is None:
        # 命令未被收集或无匹配 — 尝试模糊匹配
        for k, v in raw_outputs.items():
            if k.strip().lower() == command.strip().lower():
                raw = v
                break
    if raw is None:
        return None, f"未采集到命令输出: {command}"
    if str(raw).startswith("__ERROR__"):
        return None, str(raw)

    # 2. TextFSM 解析
    records: list[dict] = []
    if textfsm_template:
        # textfsm_template 可能是模板名（如 huawei_vrp_display_cpu_usage），拆出 platform + command
        # 由于模板查找规则是 {platform}_{command}.textfsm，这里直接用 platform + command 查找
        try:
            records = parse_with_textfsm(platform_vendor or 'cisco_ios', command, raw) or []
        except Exception as e:
            logger.debug(f"TextFSM parse error for {textfsm_template}: {e}")

    # 3. 失败时用 fallback_regex 兜底（仅 numeric/status 类型）
    if not records and fallback_regex and parse_type in ('numeric', 'status'):
        m = re.search(fallback_regex, raw, re.MULTILINE)
        if m:
            val = m.group(1) if m.groups() else m.group(0)
            if parse_type == 'numeric':
                try:
                    return float(val), ''
                except Exception:
                    return None, f"fallback_regex 提取值无法转为数字: {val}"
            return val, ''

    if not records:
        return None, "TextFSM 解析为空，且无 fallback_regex 命中"

    # 4. 按 parse_filter 过滤
    if parse_filter:
        records = _apply_parse_filter(records, parse_filter)

    # 5. 按 parse_type 提取值
    if parse_type == 'count':
        return len(records), ''

    if parse_type in ('numeric', 'diff'):
        if not records:
            return None, "过滤后记录为空"
        first = records[0]
        raw_val = first.get(parse_field) if parse_field else None
        if raw_val is None or raw_val == '':
            return None, f"字段 {parse_field} 为空"
        try:
            return float(str(raw_val).strip().rstrip('%')), ''
        except Exception:
            return None, f"字段 {parse_field} 值无法转为数字: {raw_val}"

    # status / info
    if records and parse_field:
        return records[0].get(parse_field), ''
    return str(records[0]) if records else None, ''


def _get_last_metric_value(device_id: str, check_key: str) -> float | None:
    """
    查询该设备该指标的上一次巡检值（用于 diff 对比）。
    """
    if not device_id:
        return None
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT metrics_json FROM inspection_results '
            'WHERE device_id=? AND metrics_json IS NOT NULL AND metrics_json != ? '
            'ORDER BY checked_at DESC LIMIT 5',
            (device_id, '{}')
        ).fetchall()
        for row in rows:
            try:
                metrics = json.loads(row['metrics_json'] or '{}')
            except Exception:
                continue
            val = metrics.get(check_key)
            if val is None:
                continue
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    except Exception:
        return None
    finally:
        conn.close()
    return None

def _get_last_metrics_dict(device_id: str) -> dict | None:
    """获取该设备上一次巡检的所有指标字典。"""
    if not device_id: return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT metrics_json FROM inspection_results '
            'WHERE device_id=? AND metrics_json IS NOT NULL AND metrics_json != ? '
            'ORDER BY checked_at DESC LIMIT 1',
            (device_id, '{}')
        ).fetchone()
        if row:
            return json.loads(row['metrics_json'] or '{}')
    except Exception:
        pass
    finally:
        conn.close()
    return None


def _inspect_network_device(device: dict, alert_stats: dict, inspection_items: list[dict]) -> dict[str, Any]:
    """
    网络设备巡检：一次 SSH 连接采集所有命令，TextFSM 解析，阈值/计数/对比判定。
    """
    device_id = str(device.get('id') or '')
    ip = device.get('ip_address') or ''
    hostname = device.get('hostname') or ip
    platform_name = device.get('platform') or 'cisco_ios'
    now = _beijing_now_iso()

    result = {
        'id': str(uuid.uuid4()),
        'device_id': device_id,
        'hostname': hostname,
        'ip_address': ip,
        'platform': platform_name,
        'role': device.get('role') or '',
        'site': device.get('site') or '',
        'ping_ok': 0, 'ssh_ok': 0, 'ssh_error': '',
        'ping_latency_ms': None,
        'health_score': 100,
        'health_status': 'healthy',
        'metrics_json': '{}',
        'findings_json': '[]',
        'checked_at': now,
        'cpu_usage': None, 'memory_usage': None, 'temperature': None,
        'fan_status': '', 'psu_status': '',
        'interface_total': 0, 'interface_up': 0, 'interface_down': 0,
        'interface_flapping': 0, 'interface_high_util': 0, 'interface_errors': 0,
        'open_alerts': alert_stats.get('open_alert_count', 0),
        'critical_alerts': alert_stats.get('critical_open_alerts', 0),
        'compliance_status': 'unknown', 'compliance_findings': 0,
    }

    findings: list[dict] = []
    metrics: dict[str, Any] = {}

    # 1. ICMP 连通性
    ping_result = _ping_device(ip, count=2, timeout=2)
    result['ping_ok'] = 1 if ping_result.get('success') else 0
    result['ping_latency_ms'] = ping_result.get('latency_ms')

    if not result['ping_ok']:
        findings.append({'severity': 'critical', 'message': '设备 ICMP 不可达'})
        result['health_status'] = 'critical'
        result['health_score'] = 0
        result['findings_json'] = json.dumps(findings, ensure_ascii=False)
        return result

    # 2. SSH 端口探测
    mgmt_port = int(device.get('management_port') or 22)
    ssh_check = _check_ssh(ip, port=mgmt_port, timeout=3)
    if not ssh_check.get('success'):
        result['ssh_ok'] = 0
        result['ssh_error'] = ssh_check.get('error', '')
        findings.append({'severity': 'critical', 'message': f'SSH 端口 {mgmt_port} 不通: {ssh_check.get("error", "")}'})
        result['health_status'] = 'critical'
        result['health_score'] = 20
        result['findings_json'] = json.dumps(findings, ensure_ascii=False)
        return result

    # 3. 收集所有需要的命令（去重）
    commands_needed = sorted({item.get('command') or '' for item in inspection_items if item.get('command')})
    if not commands_needed:
        result['ssh_ok'] = 1
        result['findings_json'] = '[]'
        return result

    # 4. 一次 SSH 连接采集所有命令
    try:
        raw_outputs = _netmiko_collect(device, commands_needed)
        result['ssh_ok'] = 1
    except Exception as e:
        result['ssh_ok'] = 0
        result['ssh_error'] = str(e)
        findings.append({'severity': 'critical', 'message': f'SSH 采集失败: {e}'})
        result['health_status'] = 'critical'
        result['health_score'] = 30
        result['findings_json'] = json.dumps(findings, ensure_ascii=False)
        return result

    # 5. 对每个指标进行解析和判定
    health_deduct = 0
    for item in inspection_items:
        check_key = item.get('check_key') or ''
        name_zh = item.get('name_zh') or item.get('name') or check_key
        parse_type = (item.get('parse_type') or 'numeric').lower()
        warn_threshold = item.get('warning_threshold')
        crit_threshold = item.get('critical_threshold')

        value, err = _extract_item_value(item, raw_outputs)

        if err and value is None:
            metrics[check_key] = {'value': None, 'error': err}
            continue

        metrics[check_key] = value

        # 阈值判定
        if parse_type in ('numeric', 'count') and isinstance(value, (int, float)):
            if crit_threshold is not None and value >= float(crit_threshold):
                findings.append({'severity': 'critical', 'message': f"{name_zh} 严重超标: {value} (阈值 {crit_threshold})"})
                health_deduct += 25
                if result['health_status'] != 'critical':
                    result['health_status'] = 'critical'
            elif warn_threshold is not None and value >= float(warn_threshold):
                findings.append({'severity': 'warning', 'message': f"{name_zh} 达到告警线: {value} (阈值 {warn_threshold})"})
                health_deduct += 14
                if result['health_status'] == 'healthy':
                    result['health_status'] = 'warning'

        elif parse_type == 'diff' and isinstance(value, (int, float)):
            last_val = _get_last_metric_value(device_id, check_key)
            if last_val is not None and last_val > 0:
                change_pct = abs(value - last_val) / last_val * 100.0
                metrics[f"{check_key}_last"] = last_val
                metrics[f"{check_key}_change_pct"] = round(change_pct, 2)
                if crit_threshold is not None and change_pct >= float(crit_threshold):
                    findings.append({
                        'severity': 'critical',
                        'message': f"{name_zh} 变化异常: 上次 {last_val} → 本次 {value}（变化 {change_pct:.1f}%，阈值 {crit_threshold}%）",
                    })
                    health_deduct += 20
                    if result['health_status'] != 'critical':
                        result['health_status'] = 'critical'
                elif warn_threshold is not None and change_pct >= float(warn_threshold):
                    findings.append({
                        'severity': 'warning',
                        'message': f"{name_zh} 变化提醒: 上次 {last_val} → 本次 {value}（变化 {change_pct:.1f}%）",
                    })
                    health_deduct += 10
                    if result['health_status'] == 'healthy':
                        result['health_status'] = 'warning'

    # 6. 汇总健康评分
    result['health_score'] = max(0, 100 - health_deduct)
    result['metrics_json'] = json.dumps(metrics, ensure_ascii=False)
    result['findings_json'] = json.dumps(findings, ensure_ascii=False)
    result['raw_outputs_json'] = json.dumps(raw_outputs, ensure_ascii=False)

    # 7. 智能分析
    try:
        # 尝试获取上一次的指标用于对比
        last_metrics_raw = _get_last_metrics_dict(device_id)
        analysis = analyze_device_inspection(device, metrics, inspection_items, last_metrics_raw)
        result['analysis_json'] = json.dumps(analysis, ensure_ascii=False)
    except Exception as ae:
        logger.warning(f"Analysis failed for {hostname}: {ae}")
        result['analysis_json'] = '[]'

    # 映射常用字段以保证 Dashboard 兼容
    result['raw_outputs_json'] = json.dumps(raw_outputs, ensure_ascii=False)

    # 映射常用字段以保证 Dashboard 兼容
    for key_pair in (('cpu_util', 'cpu_usage'), ('mem_util', 'memory_usage'), ('memory', 'memory_usage')):
        mkey, rkey = key_pair
        for k, v in metrics.items():
            if k.endswith(mkey) and isinstance(v, (int, float)):
                result[rkey] = v
                break

    return result

def _inspect_single_device(device: dict[str, Any], alert_stats: dict[str, int], check_items: list[str] | None = None) -> dict[str, Any]:
    device_id = str(device.get('id') or '')
    ip = device.get('ip_address') or ''
    hostname = device.get('hostname') or ip
    platform_name = (device.get('platform') or 'Linux').lower()

    # ── 加载该平台适用的巡检指标（enabled=1，vendor 匹配或为 Generic/空）──
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM inspection_items "
            "WHERE (vendor = ? OR LOWER(vendor) = 'generic' OR vendor = '') "
            "AND COALESCE(enabled, 1) = 1",
            (platform_name,)
        ).fetchall()
        matched_items = [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to load inspection items for {platform_name}: {e}")
        matched_items = []
    finally:
        conn.close()

    # ── 按平台类型路由 ──
    # 网络设备：走 NetmikoDriver CLI 采集 + TextFSM 解析
    # 服务器：走 Paramiko Shell 脚本采集（原有逻辑）
    is_network_device = platform_name in _NETWORK_PLATFORMS
    is_server = platform_name in {p.lower() for p in _SERVER_PLATFORMS}

    if is_network_device:
        # 只选 CLI 方式的指标
        cli_items = [it for it in matched_items if (it.get('method') or '').upper() == 'CLI']
        return _inspect_network_device(device, alert_stats, cli_items)

    if is_server:
        # 只选 Shell 方式的指标（原有逻辑）
        shell_items = [it for it in matched_items if (it.get('method') or '') == 'Shell']
        return _inspect_server_device(device, alert_stats, shell_items)

    # 默认当服务器处理（兼容旧数据）
    shell_items = [it for it in matched_items if (it.get('method') or '') == 'Shell']
    return _inspect_server_device(device, alert_stats, shell_items)


def _inspect_server_device(device: dict[str, Any], alert_stats: dict[str, int], shell_items: list[dict]) -> dict[str, Any]:
    """服务器巡检（Shell 脚本方式），保留原有逻辑。"""
    device_id = str(device.get('id') or '')
    ip = device.get('ip_address') or ''
    hostname = device.get('hostname') or ip
    platform_name = device.get('platform') or 'Linux'
    now = _beijing_now_iso()

    result = {
        'id': str(uuid.uuid4()),
        'device_id': device_id,
        'hostname': hostname,
        'ip_address': ip,
        'platform': platform_name,
        'role': device.get('role') or '',
        'site': device.get('site') or '',
        'ping_ok': 1, 'ssh_ok': 1, 'ssh_error': '',
        'health_score': 100,
        'health_status': 'healthy',
        'metrics_json': '{}',
        'findings_json': '[]',
        'checked_at': now,
        # Default placeholders for backward compatibility
        'cpu_usage': None, 'memory_usage': None, 'temperature': None,
        'fan_status': '', 'psu_status': '',
        'interface_total': 0, 'interface_up': 0, 'interface_down': 0,
        'interface_flapping': 0, 'interface_high_util': 0, 'interface_errors': 0,
        'open_alerts': alert_stats.get('open_alert_count', 0),
        'critical_alerts': alert_stats.get('critical_open_alerts', 0),
        'compliance_status': 'unknown', 'compliance_findings': 0,
    }

    metrics_results = {}
    findings = []

    conn = get_db_connection()
    try:
        for item in shell_items:
            script_id = item.get('script_id') or ''
            if not script_id:
                continue

            script_row = conn.execute("SELECT content FROM scripts WHERE id = ?", (script_id,)).fetchone()
            if not script_row:
                continue

            raw_output = _execute_shell_script(ip, script_row['content'], device)
            val = _extract_numeric_value(raw_output)

            if val is not None:
                metrics_results[item['check_key']] = val
                w = item.get('warning_threshold')
                c = item.get('critical_threshold')

                if c is not None and val >= c:
                    findings.append({'severity': 'critical', 'message': f"{item['name_zh']} 严重超标: {val} (阈值 {c})"})
                    result['health_status'] = 'critical'
                elif w is not None and val >= w:
                    findings.append({'severity': 'warning', 'message': f"{item['name_zh']} 达到告警线: {val} (阈值 {w})"})
                    if result['health_status'] != 'critical':
                        result['health_status'] = 'warning'
            else:
                metrics_results[item['check_key']] = "Fetch Failed"

    except Exception as e:
        findings.append({'severity': 'critical', 'message': f"精细化巡检引擎异常: {str(e)}"})
    finally:
        conn.close()

    result['metrics_json'] = json.dumps(metrics_results)
    result['findings_json'] = json.dumps(findings, ensure_ascii=False)

    # 映射常用字段以保证 Dashboard 兼容
    result['cpu_usage'] = metrics_results.get('cpu_util')
    result['memory_usage'] = metrics_results.get('mem_avail')

    return result


def _inspect_single_device_legacy(device: dict[str, Any], alert_stats: dict[str, int], check_items: list[str] | None = None) -> dict[str, Any]:
    """[DEPRECATED] 旧的巡检入口，保留用于兼容。请使用 _inspect_single_device。"""
    return _inspect_single_device(device, alert_stats, check_items)


# ──────────────────────────────────────────────
# 批量巡检执行
# ──────────────────────────────────────────────

def run_inspection(
    scope_type: str = 'all',
    scope_filter: str = '',
    trigger_type: str = 'manual',
    schedule_id: str | None = None,
    created_by: str = 'system',
    check_items: list[str] | None = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        run_id = str(uuid.uuid4())
        started_at = _beijing_now_iso()

        # 1) 获取设备列表
        devices = _load_devices(conn, scope_type, scope_filter)
        if not devices:
            return {'success': False, 'message': '未找到匹配的设备', 'run_id': run_id}

        # 创建 run 记录
        conn.execute(
            '''INSERT INTO inspection_runs
                (id, schedule_id, trigger_type, scope_type, scope_filter, status,
                 started_at, total_devices, created_by)
               VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)''',
            (run_id, schedule_id, trigger_type, scope_type, scope_filter,
             started_at, len(devices), created_by),
        )
        conn.commit()

        # 2) 预加载告警统计
        device_ids = [str(d.get('id') or '') for d in devices if d.get('id')]
        alert_stats_map = _build_open_alert_stats(conn, device_ids)

        # 3) 并发巡检
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT, len(devices))) as executor:
            futures = {
                executor.submit(
                    _inspect_single_device, dict(d), alert_stats_map.get(str(d.get('id') or ''), {}), check_items
                ): d
                for d in devices
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    result['run_id'] = run_id
                    results.append(result)
                except Exception as exc:
                    device = futures[future]
                    logger.error(f"Inspection failed for {device.get('hostname')}: {exc}")
                    results.append({
                        'id': str(uuid.uuid4()),
                        'run_id': run_id,
                        'device_id': str(device.get('id') or ''),
                        'hostname': device.get('hostname') or '',
                        'ip_address': device.get('ip_address') or '',
                        'platform': device.get('platform') or '',
                        'health_status': 'critical',
                        'findings_json': json.dumps([{'severity': 'critical', 'message': f'巡检异常: {exc}'}], ensure_ascii=False),
                        'checked_at': _beijing_now_iso(),
                        'ping_ok': 0, 'ssh_ok': 0, 'metrics_json': '{}'
                    })

        # 4) 存储结果 (增加 metrics_json 存储)
        conn.executemany(
            '''INSERT INTO inspection_results
                (id, run_id, device_id, hostname, ip_address, platform, role, site,
                 ping_ok, ping_latency_ms, ssh_ok, ssh_error,
                 health_score, health_status,
                 cpu_usage, memory_usage, temperature, fan_status, psu_status,
                 interface_total, interface_up, interface_down, interface_flapping,
                 interface_high_util, interface_errors,
                 open_alerts, critical_alerts,
                 compliance_status, compliance_findings, findings_json, metrics_json, 
                 raw_outputs_json, analysis_json, checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            [(
                r.get('id'), r.get('run_id'), r.get('device_id'), r.get('hostname'), r.get('ip_address'),
                r.get('platform'), r.get('role', ''), r.get('site', ''),
                r.get('ping_ok', 0), r.get('ping_latency_ms'), r.get('ssh_ok', 0), r.get('ssh_error', ''),
                r.get('health_score', 100), r.get('health_status', 'unknown'),
                r.get('cpu_usage'), r.get('memory_usage'), r.get('temperature'),
                r.get('fan_status', ''), r.get('psu_status', ''),
                r.get('interface_total', 0), r.get('interface_up', 0), r.get('interface_down', 0),
                r.get('interface_flapping', 0), r.get('interface_high_util', 0), r.get('interface_errors', 0),
                r.get('open_alerts', 0), r.get('critical_alerts', 0),
                r.get('compliance_status', 'unknown'), r.get('compliance_findings', 0),
                r.get('findings_json', '[]'), r.get('metrics_json', '{}'),
                r.get('raw_outputs_json', '{}'), r.get('analysis_json', '[]'), r.get('checked_at'),
            ) for r in results],
        )
        # 5) 汇总统计
        success_count = sum(1 for r in results if r['ping_ok'] or r['ssh_ok'])
        failed_count = sum(1 for r in results if not r['ping_ok'] and not r['ssh_ok'] and r['health_status'] == 'critical')
        unreachable_count = sum(1 for r in results if not r['ping_ok'] and not r['ssh_ok'])
        healthy_count = sum(1 for r in results if r['health_status'] == 'healthy')
        warning_count = sum(1 for r in results if r['health_status'] == 'warning')
        critical_count = sum(1 for r in results if r['health_status'] == 'critical')
        scores = [r['health_score'] for r in results if r['health_score'] is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        # 汇总全网分析结论
        run_analysis_sum = summarize_run_analysis(results)
        analysis_sum_json = json.dumps(run_analysis_sum, ensure_ascii=False)

        completed_at = _beijing_now_iso()
        conn.execute(
            '''UPDATE inspection_runs SET
                status='completed', completed_at=?, success_count=?, failed_count=?,
                unreachable_count=?, healthy_count=?, warning_count=?, critical_count=?,
                avg_health_score=?, analysis_summary_json=?
               WHERE id=?''',
            (completed_at, success_count, failed_count, unreachable_count,
             healthy_count, warning_count, critical_count, avg_score, 
             analysis_sum_json, run_id),
        )

        # 更新 schedule 的 last_run_at
        if schedule_id:
            conn.execute(
                'UPDATE inspection_schedules SET last_run_at=? WHERE id=?',
                (completed_at, schedule_id),
            )

        conn.commit()

        logger.info(f"[Inspection] Run {run_id} completed: {len(results)} devices, "
                     f"healthy={healthy_count}, warning={warning_count}, critical={critical_count}")

        return {
            'success': True,
            'run_id': run_id,
            'total_devices': len(results),
            'success_count': success_count,
            'unreachable_count': unreachable_count,
            'healthy_count': healthy_count,
            'warning_count': warning_count,
            'critical_count': critical_count,
            'avg_health_score': avg_score,
        }
    except Exception as exc:
        logger.error(f"[Inspection] Run failed: {exc}")
        try:
            conn.execute(
                "UPDATE inspection_runs SET status='failed', completed_at=? WHERE id=?",
                (_beijing_now_iso(), run_id),
            )
            conn.commit()
        except Exception:
            pass
        return {'success': False, 'message': str(exc), 'run_id': run_id}
    finally:
        conn.close()


def _load_devices(conn, scope_type: str, scope_filter: str) -> list[dict[str, Any]]:
    select = (
        'id, hostname, ip_address, platform, status, compliance, role, site, '
        'cpu_usage, memory_usage, temp, fan_status, psu_status, interface_data, '
        'username, password, normal_username, normal_password, '
        'admin_username, admin_password, management_port, enable_password'
    )
    if scope_type == 'all':
        rows = conn.execute(f'SELECT {select} FROM devices ORDER BY hostname').fetchall()
    elif scope_type == 'site':
        rows = conn.execute(f'SELECT {select} FROM devices WHERE site=? ORDER BY hostname', (scope_filter,)).fetchall()
    elif scope_type == 'device':
        rows = conn.execute(f'SELECT {select} FROM devices WHERE id=? ORDER BY hostname', (scope_filter,)).fetchall()
    elif scope_type == 'devices':
        ids = [x.strip() for x in scope_filter.split(',') if x.strip()]
        if not ids:
            return []
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(f'SELECT {select} FROM devices WHERE id IN ({placeholders}) ORDER BY hostname', tuple(ids)).fetchall()
    elif scope_type == 'role':
        rows = conn.execute(f'SELECT {select} FROM devices WHERE role=? ORDER BY hostname', (scope_filter,)).fetchall()
    elif scope_type == 'ip':
        ips = [x.strip() for x in scope_filter.split(',') if x.strip()]
        if not ips:
            return []
        placeholders = ','.join('?' for _ in ips)
        rows = conn.execute(f'SELECT {select} FROM devices WHERE ip_address IN ({placeholders}) ORDER BY hostname', tuple(ips)).fetchall()
    elif scope_type == 'tags':
        tags = [x.strip() for x in scope_filter.split(',') if x.strip()]
        if not tags:
            return []
        from services.tag_service import find_devices_by_tags
        # In tag_service, find_devices_by_tags takes tag_ids. If tags in filter are just tag values, we might need a custom query
        placeholders = ','.join('?' for _ in tags)
        
        # We try to match tags by td.value or td.id
        device_ids = conn.execute(f'''
            SELECT DISTINCT dt.device_id
            FROM device_tags dt
            JOIN tag_definitions td ON td.id = dt.tag_id
            WHERE td.value IN ({placeholders}) OR td.id IN ({placeholders})
        ''', tuple(tags) * 2).fetchall()
        
        ids = [str(r['device_id']) for r in device_ids]
        if not ids:
            return []
        id_placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(f'SELECT {select} FROM devices WHERE id IN ({id_placeholders}) ORDER BY hostname', tuple(ids)).fetchall()
    else:
        rows = conn.execute(f'SELECT {select} FROM devices ORDER BY hostname').fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# 查询 API
# ──────────────────────────────────────────────

def get_inspection_runs(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT COUNT(*) FROM inspection_runs').fetchone()[0]
        rows = conn.execute(
            'SELECT * FROM inspection_runs ORDER BY started_at DESC LIMIT ? OFFSET ?',
            (limit, offset),
        ).fetchall()
        return {
            'total': total,
            'items': [dict(r) for r in rows],
        }
    finally:
        conn.close()


def get_inspection_run_detail(run_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        run = conn.execute('SELECT * FROM inspection_runs WHERE id=?', (run_id,)).fetchone()
        if not run:
            return None
        results = conn.execute(
            'SELECT * FROM inspection_results WHERE run_id=? ORDER BY health_score ASC, hostname ASC',
            (run_id,),
        ).fetchall()
        run_dict = dict(run)
        run_dict['results'] = [dict(r) for r in results]
        return run_dict
    finally:
        conn.close()


def get_device_inspection_history(device_id: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT * FROM inspection_results WHERE device_id=? ORDER BY checked_at DESC LIMIT ?',
            (device_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 巡检计划管理
# ──────────────────────────────────────────────

def list_schedules(limit: int = 100, offset: int = 0) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT COUNT(*) FROM inspection_schedules').fetchone()[0]
        rows = conn.execute(
            'SELECT * FROM inspection_schedules ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall()
        return {
            'total': total,
            'items': [dict(r) for r in rows]
        }
    finally:
        conn.close()


def create_schedule(
    name: str,
    cron_expr: str = '',
    scope_type: str = 'all',
    scope_filter: str = '',
    created_by: str = 'system',
    scheduled_at: str = '',
    expires_at: str = '',
    description: str = '',
    check_items: list[str] = [],
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        schedule_id = str(uuid.uuid4())
        now = _beijing_now_iso()
        conn.execute(
            '''INSERT INTO inspection_schedules
                (id, name, cron_expr, scope_type, scope_filter, enabled, created_by, created_at, updated_at, scheduled_at, expires_at, description, check_items)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)''',
            (schedule_id, name, cron_expr, scope_type, scope_filter, created_by, now, now, scheduled_at, expires_at, description, json.dumps(check_items)),
        )
        conn.commit()
        return {'id': schedule_id, 'name': name, 'cron_expr': cron_expr,
                'scheduled_at': scheduled_at, 'expires_at': expires_at,
                'scope_type': scope_type, 'scope_filter': scope_filter, 'enabled': True, 'description': description, 'check_items': check_items}
    finally:
        conn.close()


def update_schedule(schedule_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM inspection_schedules WHERE id=?', (schedule_id,)).fetchone()
        if not row:
            return None
        allowed = {'name', 'cron_expr', 'scope_type', 'scope_filter', 'enabled', 'scheduled_at', 'expires_at', 'description', 'check_items'}
        sets = []
        params = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f'{k}=?')
                params.append(json.dumps(v) if k == 'check_items' else v)
        if not sets:
            return dict(row)
        sets.append('updated_at=?')
        params.append(_beijing_now_iso())
        params.append(schedule_id)
        conn.execute(f'UPDATE inspection_schedules SET {", ".join(sets)} WHERE id=?', tuple(params))
        conn.commit()
        updated = conn.execute('SELECT * FROM inspection_schedules WHERE id=?', (schedule_id,)).fetchone()
        return dict(updated) if updated else None
    finally:
        conn.close()


def delete_schedule(schedule_id: str) -> bool:
    conn = get_db_connection()
    try:
        cursor = conn.execute('DELETE FROM inspection_schedules WHERE id=?', (schedule_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 定时巡检触发
# ──────────────────────────────────────────────

def run_scheduled_inspections():
    """由 APScheduler 调用，执行所有到期的巡检计划。"""
    conn = get_db_connection()
    try:
        schedules = conn.execute(
            'SELECT * FROM inspection_schedules WHERE enabled=1'
        ).fetchall()
    finally:
        conn.close()

    for schedule in schedules:
        schedule = dict(schedule)
        schedule_id = schedule['id']
        logger.info(f"[Inspection] Running scheduled inspection: {schedule.get('name')} ({schedule_id})")
        try:
            check_items_raw = schedule.get('check_items')
            check_items = None
            try:
                if check_items_raw:
                    check_items = json.loads(check_items_raw)
            except Exception:
                pass
            run_inspection(
                scope_type=schedule.get('scope_type') or 'all',
                scope_filter=schedule.get('scope_filter') or '',
                trigger_type='scheduled',
                schedule_id=schedule_id,
                created_by='scheduler',
                check_items=check_items,
            )
        except Exception as exc:
            logger.error(f"[Inspection] Scheduled inspection {schedule_id} failed: {exc}")


# ──────────────────────────────────────────────
# 巡检报告对比
# ──────────────────────────────────────────────

def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        results_a = conn.execute(
            'SELECT * FROM inspection_results WHERE run_id=?', (run_id_a,)
        ).fetchall()
        results_b = conn.execute(
            'SELECT * FROM inspection_results WHERE run_id=?', (run_id_b,)
        ).fetchall()

        map_a = {r['device_id']: dict(r) for r in results_a}
        map_b = {r['device_id']: dict(r) for r in results_b}

        all_ids = set(map_a.keys()) | set(map_b.keys())
        changes: list[dict[str, Any]] = []

        for device_id in all_ids:
            a = map_a.get(device_id)
            b = map_b.get(device_id)
            if a and not b:
                changes.append({'device_id': device_id, 'hostname': a.get('hostname'), 'change': 'removed'})
            elif b and not a:
                changes.append({'device_id': device_id, 'hostname': b.get('hostname'), 'change': 'added'})
            elif a and b:
                diffs = []
                if a.get('health_status') != b.get('health_status'):
                    diffs.append(f'健康状态: {a.get("health_status")} → {b.get("health_status")}')
                score_a = a.get('health_score') or 0
                score_b = b.get('health_score') or 0
                if abs(score_a - score_b) >= 10:
                    diffs.append(f'健康评分: {score_a} → {score_b}')
                if a.get('ping_ok') != b.get('ping_ok'):
                    diffs.append(f'Ping: {"通" if a.get("ping_ok") else "不通"} → {"通" if b.get("ping_ok") else "不通"}')
                if diffs:
                    changes.append({
                        'device_id': device_id,
                        'hostname': b.get('hostname'),
                        'change': 'changed',
                        'details': diffs,
                    })

        return {
            'run_a': run_id_a,
            'run_b': run_id_b,
            'total_devices_a': len(map_a),
            'total_devices_b': len(map_b),
            'changes': changes,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 巡检指标项管理 (Inspection Items)
# ──────────────────────────────────────────────

def list_inspection_items() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT * FROM inspection_items ORDER BY category ASC, name ASC').fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def create_inspection_item(item_data: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        item_id = str(uuid.uuid4())
        now = _beijing_now_iso()
        conn.execute(
            '''INSERT INTO inspection_items
                (id, name, name_zh, category, check_key, description, method, command, vendor, oid, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (item_id, item_data['name'], item_data['name_zh'], item_data['category'],
             item_data['check_key'], item_data.get('description', ''), 
             item_data.get('method', 'SNMP'), item_data.get('command', ''),
             item_data.get('vendor', ''), item_data.get('oid', ''), now, now)
        )
        conn.commit()
        item_data['id'] = item_id
        item_data['created_at'] = now
        item_data['updated_at'] = now
        return item_data
    finally:
        conn.close()

def update_inspection_item(item_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        allowed = {'name', 'name_zh', 'category', 'check_key', 'description', 'method', 'command', 'vendor', 'oid'}
        sets = []
        params = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return None
        sets.append('updated_at=?')
        params.append(_beijing_now_iso())
        params.append(item_id)
        conn.execute(f'UPDATE inspection_items SET {", ".join(sets)} WHERE id=?', tuple(params))
        conn.commit()
        row = conn.execute('SELECT * FROM inspection_items WHERE id=?', (item_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_inspection_item(item_id: str) -> bool:
    conn = get_db_connection()
    try:
        cursor = conn.execute('DELETE FROM inspection_items WHERE id=?', (item_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
