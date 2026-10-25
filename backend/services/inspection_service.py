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
import math
import platform
import re
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncio
from database import get_db_connection, fetch_interface_data
from core.interface_utils import normalize_interface_name
from services.device_health_service import (
    evaluate_device_health,
    _build_open_alert_stats,
)
from services.network_access_limiter import limited_connect_handler
from core.config import settings
from core.subprocess_utils import run_console_command
from core.textfsm import parse_with_textfsm
from core.analysis import analyze_device_inspection, summarize_run_analysis, correlate_risk_patterns
from core.exception_classifier import make_finding


logger = logging.getLogger(__name__)

_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_CONCURRENT = max(1, int(getattr(settings, 'NETWORK_INSPECTION_CONCURRENCY', 10)))
_SSH_CONNECT_TIMEOUT = 15     # SSH 建立超时
_SSH_COMMAND_TIMEOUT = 30     # 单条命令超时

# 关联规则进程级缓存（批量巡检时避免每台设备各查一次数据库）
_CORR_RULES_CACHE: dict[str, Any] = {'rules': None, 'ts': 0.0}
_CORR_RULES_TTL = 60.0        # 缓存有效期（秒）

# 识别为"网络设备"的 platform（走 NetmikoDriver CLI 采集）
_NETWORK_PLATFORMS = {
    'cisco_ios', 'cisco_xe', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd',
    'huawei_vrp', 'huawei_vrpv8', 'huawei',
    'h3c_comware',
    'juniper_junos', 'juniper',
    'arista_eos',
    'paloalto_panos', 'fortinet', 'checkpoint_gaia',
    'hillstone_stoneos', 'ruijie_os', 'ruijie_rgos', 'zte_zxros', 'raisecom_ros', 'maipu',
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
        proc = run_console_command(cmd, timeout=count * timeout + 5)
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
        # Always close the probe socket, including DNS/connect exceptions.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            start = time.monotonic()
            result_code = s.connect_ex((ip, port))
            elapsed = round((time.monotonic() - start) * 1000, 1)
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
    import socket as _socket
    from services.vault_service import resolve_device_credentials
    try:
        creds = resolve_device_credentials(device)
        username = creds.get('normal_username') or ''
        password = creds.get('normal_password') or ''
        port = int(device.get('management_port') or device.get('port') or 22)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        from drivers.ssh_compat import build_paramiko_compatibility_kwargs
        ssh.connect(
            ip,
            port=port,
            username=username,
            password=password,
            timeout=10,
            **build_paramiko_compatibility_kwargs(
                device.get('ssh_algorithm_profile')
            ),
        )
        try:
            # timeout 限制 stdout/stderr 的阻塞读取，避免命令挂死导致采集线程
            # 永不返回（进而拖垮 ThreadPoolExecutor.shutdown 与定时任务调度）。
            stdin, stdout, stderr = ssh.exec_command(script_content, timeout=_SSH_COMMAND_TIMEOUT)
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            err_output = stderr.read().decode('utf-8', errors='ignore').strip()
            exit_status = stdout.channel.recv_exit_status()
        finally:
            ssh.close()
        if exit_status != 0:
            # A script process failure is a collection error even if stdout
            # happened to contain a plausible number or an NA sentinel.
            return f"ERROR: 脚本进程退出状态 {exit_status}"
        if not output and err_output:
            return f"ERROR: {err_output}"
        return output
    except _socket.timeout:
        return f"ERROR: 脚本执行超时（>{_SSH_COMMAND_TIMEOUT}s），目标主机响应缓慢或脚本阻塞"
    except Exception as e:
        return f"ERROR: {str(e)}"

def _extract_numeric_value(output: str) -> float | None:
    """从输出中提取最后一个数字结果"""
    if not output or "ERROR" in output: return None
    lines = output.split('\n')
    last_line = next((line.strip() for line in reversed(lines) if line.strip()), '')
    if re.search(r"(?:^|[:=])\s*(?:NA|N/A|NOT[_ ]COLLECTED|UNAVAILABLE)(?:\s|$)", last_line, re.IGNORECASE):
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line: continue
        # 寻找数字，支持 85.5% -> 85.5
        match = re.search(r"([-+]?\d*\.\d+|\d+)", line)
        if match:
            try: return float(match.group(1))
            except: continue
    return None


def _is_no_data_metric_output(output: Any) -> bool:
    """Recognize explicit missing-value output from seeded shell scripts."""
    lines = [line.strip() for line in str(output or '').splitlines() if line.strip()]
    if not lines:
        return True
    return bool(re.search(
        r"(?:^|[:=])\s*(?:NA|N/A|NOT[_ ]COLLECTED|UNAVAILABLE)(?:\s|$)",
        lines[-1],
        re.IGNORECASE,
    ))


# ══════════════════════════════════════════════════════════════════
# 网络设备 CLI 巡检（Netmiko + TextFSM）
# ══════════════════════════════════════════════════════════════════

def _netmiko_platform_type(platform: str) -> str:
    """将平台名映射到 Netmiko device_type。"""
    mapping = {
        'cisco_ios': 'cisco_ios',
        'cisco_xe': 'cisco_ios',
        'cisco_nxos': 'cisco_nxos',
        'cisco_xr': 'cisco_xr',
        'cisco_asa': 'cisco_asa',
        'cisco_ftd': 'cisco_ftd',
        'huawei_vrp': 'huawei',
        'huawei_vrpv8': 'huawei_vrpv8',
        'huawei': 'huawei',
        'h3c_comware': 'hp_comware',
        'h3c_comware_v3': 'hp_comware',
        'juniper_junos': 'juniper_junos',
        'juniper': 'juniper_junos',
        'arista_eos': 'arista_eos',
        'paloalto_panos': 'paloalto_panos',
        'fortinet': 'fortinet',
        'checkpoint_gaia': 'checkpoint_gaia',
        'hillstone_stoneos': 'hillstone_stoneos',
        'ruijie_os': 'ruijie_os',
        'ruijie_rgos': 'ruijie_os',
        'zte_zxros': 'zte_zxros',
        'raisecom_ros': 'raisecom_ros',
        'maipu': 'maipu',
        'dptech': 'dptech_ios',
        'dptech_ios': 'dptech_ios',
        'dptech_conplat': 'dptech_ios',
        'dptech_conplat_fw': 'dptech_ios',
    }
    return mapping.get(platform, 'cisco_ios')


def _netmiko_collect(device: dict[str, Any], commands: list[str], use_admin_creds: bool = False) -> dict[str, str]:
    """
    一次 SSH 连接执行多条命令，返回 {command: output} 字典。
    命令失败单条用 '__ERROR__: xxx' 标记，整体连接失败抛异常。

    特殊键：'__ENABLE_FAILED__' — 当 enable 提权失败时记录原始错误（R2.8）。
    """
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs
    from services.vault_service import resolve_device_credentials

    registry_outputs: dict[str, str] = {}
    remaining_commands = list(commands)
    if device.get('platform_profile_id'):
        from services.platform_registry_service import execute_platform_action, resolve_device_action_code

        registry_user = {
            'id': f"inspection:{device.get('id') or 'unknown'}",
            'username': 'inspection-collector',
            'role': 'Administrator' if use_admin_creds else 'Operator',
            'tenant_id': device.get('tenant_id') or '',
        }
        remaining_commands = []
        for command in commands:
            action_code = resolve_device_action_code(str(device.get('id') or ''), command)
            if not action_code:
                registry_outputs[command] = '__ERROR__: platform_registry: UNSUPPORTED_ACTION: command is not mapped by the published release'
                continue
            try:
                action_result = execute_platform_action(
                    str(device['id']),
                    action_code,
                    user=registry_user,
                    include_raw_output=True,
                )
                if action_result.get('success'):
                    registry_outputs[command] = str(action_result.get('raw_output') or '')
                else:
                    registry_outputs[command] = f"__ERROR__: {action_result.get('error_code') or 'ACTION_FAILED'}: {action_result.get('error') or 'Platform action failed'}"
            except Exception as exc:
                registry_outputs[command] = f"__ERROR__: platform_registry: {exc}"

    if not remaining_commands:
        return registry_outputs

    platform = (device.get('platform') or 'cisco_ios').lower()
    is_slow = platform in {'huawei_vrp', 'huawei_vrpv8', 'h3c_comware', 'raisecom_ros'}

    # 统一使用 Vault 凭据解析服务
    creds = resolve_device_credentials(device)
    if use_admin_creds:
        username = creds.get('admin_username') or ''
        password = creds.get('admin_password') or ''
    else:
        username = creds.get('normal_username') or ''
        password = creds.get('normal_password') or ''

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
    params.update(
        build_netmiko_compatibility_kwargs(
            profile=device.get('ssh_algorithm_profile')
        )
    )

    secret = creds.get('enable_password') or ''
    if secret:
        params['secret'] = secret

    results: dict[str, str] = {}
    try:
        with limited_connect_handler(device, ConnectHandler, **params) as conn:
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
                            # R2.8: Enable 提权失败 — 记录到特殊键，由调用方转换为 finding
                            results['__ENABLE_FAILED__'] = str(en_err)
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
                    except Exception as en_err:
                        results['__ENABLE_FAILED__'] = str(en_err)

            for cmd in remaining_commands:
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

    return {**registry_outputs, **results}


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

    错误消息使用标准化文案，对应 R2.9–R2.16：
      - 命令级异常（R2.9–R2.12）：% Invalid input、% Authorization failed、--More--、__ERROR__
      - 解析级异常（R2.13–R2.16）：模板不存在、解析为空、字段缺失、数值转换失败

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

    raw_str = str(raw)

    # ── 命令级异常检测（R2.9–R2.12）─────────────────────────────
    # R2.11: __ERROR__ 前缀（命令执行失败）
    if raw_str.startswith("__ERROR__"):
        # 提取 __ERROR__ 后的原始错误信息
        err_detail = raw_str[len("__ERROR__:"):].strip() if raw_str.startswith("__ERROR__:") else raw_str[len("__ERROR__"):].strip()
        return None, f"命令执行失败: {err_detail}"

    # R2.9: % Invalid input detected
    if "% Invalid input detected" in raw_str:
        return None, "命令不存在或设备不支持该命令"

    # R2.10: % Authorization failed
    if "% Authorization failed" in raw_str:
        return None, "命令执行权限不足，请检查账号授权级别"

    # R2.12: --More-- 残留（说明分页符未清除）
    if "--More--" in raw_str:
        return None, "命令输出分页符未清除，请检查终端分页配置"

    # Never let an SNMP community string enter metrics, findings, or analysis.
    # The local compliance contract treats empty/public/private/netops as
    # unsafe. Parse every reported community in memory and return only a
    # coarse safe/unsafe state; an absent row is a parse/collection failure.
    if str(item.get('check_key') or '').casefold() == 'cisco_ios_snmp_community':
        community_rows = re.findall(
            r'^\s*Community\s+name\s*:\s*([^\r\n]*)$',
            raw_str,
            re.MULTILINE | re.IGNORECASE,
        )
        if not community_rows:
            return None, 'SNMP community 输出解析失败：未包含 Community name 条目'
        insecure_names = {'', 'public', 'private', 'netops'}
        community_names = []
        for row in community_rows:
            value = row.strip()
            first_token = value.split()[0].rstrip(',;') if value else ''
            community_names.append(first_token.casefold())
        return ('unsafe' if any(name in insecure_names for name in community_names) else 'safe'), ''

    # ── 2. TextFSM 解析（R2.13/R2.14）──────────────────────────
    records: list[dict] = []
    template_found = True
    parse_state_error: str = ''
    # A filtered running-config count is not represented by an NTC TextFSM
    # template. Count its explicitly configured rows before TextFSM lookup;
    # an empty successful response is a valid zero, while a non-empty response
    # with no matching row proceeds to parser validation and fails closed.
    if parse_type == 'count' and fallback_regex:
        try:
            matches = list(re.finditer(fallback_regex, raw_str, re.MULTILINE | re.IGNORECASE))
        except re.error as exc:
            return None, f"Count fallback regex is invalid: {exc}"
        if matches:
            return len(matches), ''
        if not raw_str.strip():
            return 0, ''

    if textfsm_template or platform_vendor:
        try:
            records = parse_with_textfsm(platform_vendor or 'cisco_ios', command, raw) or []
        except Exception as e:
            # TextFSM State Error 或其他解析异常
            parse_state_error = str(e)
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
                    # R2.16: 数值转换失败
                    return None, f"字段值 '{val}' 无法转换为数字"
            return val, ''

    if not records:
        # 区分模板不存在 vs 解析结果为空
        if parse_state_error:
            # R2.13 派生：解析过程出错
            return None, f"TextFSM 解析异常: {parse_state_error}"
        # 检测是否模板缺失（fallback 也失败）
        try:
            from core.textfsm import _find_template
            tpl = _find_template(platform_vendor or 'cisco_ios', command)
            if tpl is None:
                # R2.13: 模板不存在
                return None, f"未找到 {platform_vendor or 'cisco_ios'}/{command} 的解析模板"
        except Exception:
            pass
        # R2.14: 模板存在但解析结果为空
        return None, "TextFSM 解析结果为空，输出格式可能与模板不匹配"

    # 4. 按 parse_filter 过滤
    if parse_filter:
        records = _apply_parse_filter(records, parse_filter)

    # 5. 按 parse_type 提取值
    if parse_type == 'count':
        return len(records), ''

    if parse_type in ('numeric', 'diff'):
        if not records:
            return None, "TextFSM 解析结果为空，输出格式可能与模板不匹配"
        first = records[0]
        # R2.15: 字段缺失
        if parse_field and parse_field not in first:
            return None, f"解析字段 {parse_field} 在结果中不存在"
        raw_val = first.get(parse_field) if parse_field else None
        if raw_val is None or raw_val == '':
            return None, f"解析字段 {parse_field} 在结果中不存在"
        try:
            return float(str(raw_val).strip().rstrip('%')), ''
        except Exception:
            # R2.16: 数值转换失败
            return None, f"字段值 '{raw_val}' 无法转换为数字"

    # status / info
    if records and parse_field:
        if parse_field not in records[0]:
            return None, f"解析字段 {parse_field} 在结果中不存在"
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


def _inspection_routing_protocol(item: dict) -> str | None:
    """Recognize explicit BGP/OSPF neighbor metrics without treating route metrics as peers."""
    check_key = str(item.get('check_key') or '').casefold()
    tokens = set(re.split(r'[^a-z0-9]+', check_key))
    if 'bgp' in tokens and tokens.intersection({'neighbor', 'peer', 'down', 'adjacency'}):
        return 'bgp'
    if 'ospf' in tokens and tokens.intersection({'neighbor', 'peer', 'down', 'adjacency'}):
        return 'ospf'
    return None


def _routing_neighbor_is_healthy(state: str, protocol: str) -> bool:
    if protocol == 'bgp':
        return state in {'established', 'up'}
    return state in {'full', 'two_way', 'twoway', '2way', 'up'} or state.startswith(('full_', 'two_way_'))


def _routing_neighbor_state_snapshot(
    records: list[dict],
    protocol: str,
) -> tuple[int, dict[str, str], str]:
    """Normalize a complete SNMP table to a down count and stable peer states."""
    allowed_states = (
        {'idle', 'connect', 'active', 'opensent', 'openconfirm', 'established', 'up'}
        if protocol == 'bgp'
        else {'down', 'attempt', 'init', 'two_way', 'twoway', '2way', 'exchange_start', 'exchange', 'loading', 'full', 'up'}
    )
    peer_states: dict[str, str] = {}
    for record in records:
        if protocol == 'bgp':
            peer = str(
                record.get('neighbor_ip') or record.get('peer_ip')
                or record.get('bgp_neigh') or record.get('neighbor') or ''
            ).strip()
        else:
            peer_id = str(
                record.get('router_id') or record.get('neighbor_id')
                or record.get('neighbor_ip') or record.get('address') or ''
            ).strip()
            interface = str(record.get('interface') or record.get('if_index') or '').strip()
            peer = f'{peer_id}@{interface}' if interface else peer_id
        raw_state = record.get('state') or record.get('state_pfxrcd') or record.get('status') or record.get('up_down') or ''
        state = re.sub(r'[^a-z0-9]+', '_', str(raw_state).strip().casefold()).strip('_')
        if protocol == 'bgp' and state.isdigit():
            state = 'established'
        if not peer:
            return 0, {}, f'{protocol.upper()} SNMP neighbor row has no peer identity'
        if protocol == 'bgp' and str(record.get('admin_status') or '').casefold() == 'stopped':
            state = 'idle'
        if state not in allowed_states and not (protocol == 'ospf' and state.startswith(('full_', 'two_way_'))):
            return 0, {}, f'{protocol.upper()} SNMP neighbor row has an unknown state'
        if peer in peer_states:
            return 0, {}, f'{protocol.upper()} SNMP neighbor table contains duplicate peers'
        peer_states[peer] = state

    down_count = sum(1 for state in peer_states.values() if not _routing_neighbor_is_healthy(state, protocol))
    return down_count, peer_states, ''


def _record_routing_neighbor_state_changes(
    item: dict,
    peer_states: dict[str, str],
    previous_metrics: dict,
    metrics: dict,
    findings: list[dict],
) -> int:
    """Persist per-peer states and add findings for changes since the last run."""
    check_key = str(item.get('check_key') or '')
    state_key = f'{check_key}_neighbor_states'
    previous = previous_metrics.get(state_key)
    previous_states = previous if isinstance(previous, dict) else {}
    current_states = dict(peer_states)
    for peer, old_state in previous_states.items():
        if peer not in current_states:
            current_states[str(peer)] = 'missing'

    metrics[state_key] = current_states
    if not isinstance(previous, dict):
        return 0

    changes = 0
    protocol = _inspection_routing_protocol(item) or 'routing'
    name = item.get('name_zh') or item.get('name') or check_key
    for peer, current_state in current_states.items():
        old_state = str(previous_states.get(peer) or '').strip().casefold()
        if not old_state or old_state == str(current_state).casefold():
            continue
        changes += 1
        is_down = current_state == 'missing' or not _routing_neighbor_is_healthy(str(current_state), protocol)
        direction = '状态异常' if is_down else '状态恢复'
        findings.append(make_finding(
            'data_error' if is_down else 'data_change',
            f'{name} 邻居 {peer} 状态变化: {old_state} → {current_state}（{direction}）',
            severity='warning' if is_down else 'info',
        ))

    # Missing peers are part of the observed down count after a complete
    # snapshot; persisting "missing" prevents repeating the same transition.
    metrics[check_key] = sum(
        1 for state in current_states.values()
        if not _routing_neighbor_is_healthy(str(state), protocol)
    )
    return changes


def _extract_snmp_item_value(item: dict, snmp_metrics: dict, snmp_interfaces: list[dict]) -> tuple[Any, str]:
    """
    从 SNMP 采集结果中提取指标值。
    snmp_metrics 来自 LibreNMS 原生硬件快照；接口状态来自最近一次完整的
    SNMP/IF-MIB CMDB 快照，避免巡检重复轮询设备。
    snmp_interfaces: [{name, status, admin_status}, ...]

    根据 check_key 后缀匹配:
      *_cpu / *cpu           -> cpu_usage
      *_mem / *memory        -> memory_usage
      *_temp / *temperature  -> temp
      *_fan                  -> fan_status
      *_psu                  -> psu_status
      *_intf_down / *interface_down -> 统计 down 接口数
    """
    check_key = (item.get('check_key') or '').lower()

    # CPU
    if check_key.endswith('_cpu') or check_key.endswith('cpu'):
        val = snmp_metrics.get('cpu_usage')
        if val is None:
            return None, 'SNMP 采集 CPU 利用率失败或设备不支持'
        return float(val), ''

    # Memory
    if check_key.endswith('_mem') or check_key.endswith('memory') or check_key.endswith('_memory'):
        val = snmp_metrics.get('memory_usage')
        if val is None:
            return None, 'SNMP 采集内存利用率失败或设备不支持'
        return float(val), ''

    # Temperature
    if check_key.endswith('_temp') or check_key.endswith('temperature'):
        val = snmp_metrics.get('temp')
        if val is None:
            return None, 'SNMP 采集温度失败或设备不支持'
        return float(val), ''

    # Fan
    if check_key.endswith('_fan'):
        val = snmp_metrics.get('fan_status')
        if val is None:
            return None, 'SNMP 采集风扇状态失败或设备不支持'
        return val, ''

    # PSU
    if check_key.endswith('_psu'):
        val = snmp_metrics.get('psu_status')
        if val is None:
            return None, 'SNMP 采集电源状态失败或设备不支持'
        return val, ''

    # Interface Down count
    if 'intf_down' in check_key or 'interface_down' in check_key:
        if not snmp_interfaces:
            return None, snmp_metrics.get('interface_status_error') or '没有可用的完整 IF-MIB 接口状态快照'
        unknown_count = sum(
            1 for iface in snmp_interfaces
            if str(iface.get('status') or '').casefold() == 'unknown'
            or str(iface.get('admin_status') or '').casefold() == 'unknown'
        )
        if unknown_count:
            return None, f'IF-MIB 完整快照中有 {unknown_count} 个接口状态无法判定'
        down_count = sum(
            1 for iface in snmp_interfaces
            if str(iface.get('status', '')).lower() in ('down', '2', 'notconnect')
            and str(iface.get('admin_status', '')).lower() not in ('down', '2')  # 排除管理员手动 shutdown 的
        )
        return down_count, ''

    return None, f'未知的 SNMP 指标 check_key: {check_key}'


_INSPECTION_COMPONENT_STATE_CODES = {0: 'ok', 1: 'warning', 2: 'failed', 3: 'unknown'}
_INSPECTION_UNKNOWN_STATES = {'', 'unknown', 'unavailable', 'not_collected', 'not collected', 'n/a', 'na', 'null', 'none', '--'}
_INSPECTION_HEALTHY_STATES = {'normal', 'ok', 'up', 'true', '1', 'running', 'operational', 'ready', 'active'}
_INSPECTION_FAILURE_STATES = {'fail', 'failed', 'failure', 'error', 'down', 'offline', 'alarm', 'false', '0'}


def _normalize_inspection_status(value: Any, *, component_state: bool = False) -> str:
    """Normalize known typed component states without guessing unknown values.

    LibreNMS component-state samples use 0=ok, 1=warning, 2=failed,
    3=unknown. Their inspection snapshot normally exposes the corresponding
    lower-case labels, but accepting numeric values here keeps imported and
    legacy status rows on the same contract.
    """
    if isinstance(value, bool):
        return 'ok' if value else 'failed'
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return str(value or '').strip().casefold()
        if component_state and number.is_integer() and int(number) in _INSPECTION_COMPONENT_STATE_CODES:
            return _INSPECTION_COMPONENT_STATE_CODES[int(number)]
        if math.isfinite(number) and number.is_integer():
            return str(int(number))
        return str(value).strip().casefold()

    normalized = str(value or '').strip().casefold()
    if component_state and normalized in {'0', '1', '2', '3'}:
        return _INSPECTION_COMPONENT_STATE_CODES[int(normalized)]
    return normalized


def _classify_inspection_status(
    value: Any,
    expected_value: Any = '',
    *,
    component_state: bool = False,
    allow_expected_substring: bool = False,
) -> tuple[str, str]:
    """Return (metric status, finding severity) for a status-valued item."""
    normalized = _normalize_inspection_status(value, component_state=component_state)
    if normalized in _INSPECTION_UNKNOWN_STATES:
        return 'NOT_COLLECTED', ''

    expected = _normalize_inspection_status(expected_value, component_state=component_state)
    has_expected = expected not in _INSPECTION_UNKNOWN_STATES

    # The source-defined component enum is more precise than substring checks:
    # warning is a warning, failed is critical for fan/PSU, and unknown is not
    # a successful sample (handled above).
    if normalized == 'warning':
        return 'WARNING', 'warning'
    if normalized in {'failed', 'fail', 'failure'}:
        return ('ERROR', 'critical' if component_state else 'warning')

    if has_expected:
        matches_expected = (
            normalized == expected
            if component_state
            else _inspection_status_matches_expected(
                value,
                expected,
                allow_substring=allow_expected_substring,
            )
        )
        if matches_expected:
            return 'SUCCESS', ''
        return 'WARNING', 'warning'

    if normalized in _INSPECTION_HEALTHY_STATES:
        return 'SUCCESS', ''
    if normalized in _INSPECTION_FAILURE_STATES:
        return ('ERROR', 'critical' if component_state else 'warning')
    # Keep unfamiliar non-empty states visible as a warning rather than
    # silently accepting them as healthy.
    return 'WARNING', 'warning'


def _inspection_status_matches_expected(
    value: Any,
    expected_value: Any,
    *,
    allow_substring: bool = False,
) -> bool:
    """Compare normalized status values, optionally preserving compliance phrases.

    Compliance checks historically accepted an expected phrase inside a longer
    CLI status, while SNMP component states require an exact enum match. A
    leading negation must never satisfy a positive expected phrase.
    """
    actual = _normalize_inspection_status(value)
    expected = _normalize_inspection_status(expected_value)
    if not expected or actual in _INSPECTION_UNKNOWN_STATES:
        return False
    if actual == expected:
        return True
    if not allow_substring or expected not in actual:
        return False
    prefix = actual.split(expected, 1)[0].strip()
    if prefix in {'un', 'not', 'no', 'non'} or prefix.endswith(('not', 'no', 'non')):
        return False
    return True


def _is_unavailable_snmp_snapshot_error(error: Any) -> bool:
    """Identify unsupported or stale snapshot data, not transport/parse errors."""
    message = str(error or '').casefold()
    return any(
        marker in message
        for marker in (
            '失败或设备不支持',
            '没有可用的完整 if-mib 接口状态快照',
            'if-mib 完整快照中有',
            '接口状态快照不存在或已过期',
            '最近一次完整接口状态快照来自 cli，不是 snmp/if-mib',
        )
    )


def _inspection_threshold_is_crossed(value: Any, threshold: Any, direction: Any = 'above') -> bool:
    """Apply the shared threshold contract: above is >=, below is strict <."""
    if threshold is None:
        return False
    try:
        actual_number = float(value)
        threshold_number = float(threshold)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(actual_number) or not math.isfinite(threshold_number):
        return False
    if str(direction or 'above').strip().casefold() == 'below':
        return actual_number < threshold_number
    return actual_number >= threshold_number


def _inspection_threshold_relation(direction: Any = 'above') -> str:
    return '低于' if str(direction or 'above').strip().casefold() == 'below' else '达到或超过'


def _load_fresh_snmp_interface_snapshot(device_id: str) -> tuple[list[dict], str]:
    """Read the latest complete SNMP-owned interface snapshot from CMDB."""
    try:
        from services.collection_status_service import list_collection_status

        status_rows = list_collection_status(device_id=device_id, collector='interface_status')
        snapshot = next((item for item in status_rows if item.get('collector') == 'interface_status'), None)
        if not snapshot or snapshot.get('effective_status') != 'success':
            return [], 'IF-MIB 接口状态快照不存在或已过期，请先完成设备接口刷新'
        metadata = snapshot.get('metadata') if isinstance(snapshot.get('metadata'), dict) else {}
        if str(metadata.get('parser') or '').casefold() != 'snmp':
            return [], '最近一次完整接口状态快照来自 CLI，不是 SNMP/IF-MIB'
        if metadata.get('complete') is not True:
            return [], '最近一次 IF-MIB 接口状态快照未标记为完整'
        observed_from = metadata.get('snapshot_started_at')
        expected_count = int(snapshot.get('coverage_total') or 0)
        if not observed_from or expected_count <= 0:
            return [], 'IF-MIB 接口状态快照缺少完整性标记'

        conn = get_db_connection()
        try:
            rows = conn.execute(
                '''SELECT interface_name, admin_status, oper_status, last_seen
                   FROM interfaces WHERE device_id = ?''',
                (device_id,),
            ).fetchall()
        finally:
            conn.close()

        observed_at = _parse_sample_datetime(observed_from)
        if observed_at is None:
            return [], 'IF-MIB 接口状态快照时间无效'
        by_name: dict[str, dict] = {}
        for row in rows:
            item = dict(row)
            row_seen = _parse_sample_datetime(item.get('last_seen'))
            key = normalize_interface_name(item.get('interface_name'))
            if not key or row_seen is None or row_seen < observed_at:
                continue
            current = by_name.get(key)
            if current is None or str(item.get('last_seen') or '') > str(current.get('last_seen') or ''):
                by_name[key] = item
        if len(by_name) != expected_count:
            return [], 'IF-MIB 接口状态快照不完整，CMDB 当前行数与采集覆盖数不一致'
        return [
            {
                'name': item.get('interface_name') or '',
                'status': item.get('oper_status') or 'unknown',
                'admin_status': item.get('admin_status') or 'unknown',
            }
            for item in by_name.values()
        ], ''
    except Exception as exc:
        logger.info('SNMP interface snapshot lookup failed for %s (%s)', device_id, type(exc).__name__)
        return [], '读取 IF-MIB 接口状态快照失败'


def _parse_sample_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _collect_snmp_for_inspection(
    device: dict,
    *,
    include_interface_snapshot: bool = False,
) -> tuple[dict, list[dict]]:
    """
    Read fresh hardware values from the existing LibreNMS binding.

    Hardware rows without a native sample timestamp are deliberately excluded
    from inspection thresholds. Interface status is read from the latest
    complete SNMP-owned CMDB snapshot to avoid a second IF-MIB walk.
    """
    ip = device.get('ip_address') or ''

    snmp_metrics: dict = {}
    snmp_interfaces: list[dict] = []

    try:
        loop = asyncio.new_event_loop()
        try:
            from services.librenms_diagnostic_service import diagnose_librenms_hardware

            native = loop.run_until_complete(diagnose_librenms_hardware(device))
            processor_rows = native.get('processor_sensors') or []
            memory_rows = native.get('memory_pools') or []
            temperature_rows = [
                row for row in native.get('hardware_sensors') or []
                if str(row.get('sensor_class') or '').casefold() in {'temperature', 'temp'}
            ]

            def fresh_values(rows: list[dict]) -> list[float]:
                values: list[float] = []
                for row in rows:
                    if row.get('value_status') != 'available' or row.get('freshness') != 'fresh':
                        continue
                    value = row.get('sensor_current')
                    if isinstance(value, bool):
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if number == number and abs(number) != float('inf'):
                        values.append(number)
                return values

            for key, rows in (
                ('cpu_usage', processor_rows),
                ('memory_usage', memory_rows),
                ('temp', temperature_rows),
            ):
                if key == 'memory_usage':
                    rows = [row for row in rows if str(row.get('sensor_type') or '').casefold() == 'memory_usage_percent']
                values = fresh_values(rows)
                if values:
                    # Keep every native entity in the diagnostic response. The
                    # legacy inspection rule contract accepts one scalar, so
                    # its device-level threshold uses the highest fresh row.
                    snmp_metrics[key] = max(values)

            state_codes = {0: 'ok', 1: 'warning', 2: 'failed', 3: 'unknown'}
            state_priorities = {'ok': 0, 'unknown': 1, 'warning': 2, 'failed': 3}
            status_rows = {'fan_state': [], 'power_supply_state': []}
            for row in native.get('hardware_sensors') or []:
                sensor_class = str(row.get('sensor_class') or '').casefold()
                if sensor_class not in status_rows:
                    continue
                if (
                    not row.get('active')
                    or row.get('sensor_type') != 'component_state'
                    or row.get('value_status') != 'available'
                    or row.get('freshness') != 'fresh'
                ):
                    continue
                try:
                    state_number = float(row.get('sensor_current'))
                except (TypeError, ValueError, OverflowError):
                    continue
                if (
                    state_number == state_number
                    and abs(state_number) != float('inf')
                    and state_number.is_integer()
                    and int(state_number) in state_codes
                ):
                    status_rows[sensor_class].append(state_codes[int(state_number)])

            for source_class, metric_name in (('fan_state', 'fan_status'), ('power_supply_state', 'psu_status')):
                values = status_rows[source_class]
                if values:
                    snmp_metrics[metric_name] = max(values, key=lambda value: state_priorities[value])
        except Exception as e:
            logger.warning("LibreNMS inspection snapshot failed for %s: %s", ip, type(e).__name__)
            snmp_metrics = {}
        finally:
            loop.close()
    except Exception as e:
        logger.warning(f"SNMP event loop creation failed for {ip}: {e}")

    snmp_interfaces: list[dict] = []
    if include_interface_snapshot:
        snmp_interfaces, interface_error = _load_fresh_snmp_interface_snapshot(str(device.get('id') or ''))
        if interface_error:
            snmp_metrics['interface_status_error'] = interface_error
    return snmp_metrics, snmp_interfaces


def _get_correlation_rules_cached() -> list[dict]:
    """获取启用的关联规则，进程级短缓存（TTL 60s）。

    关联规则是全局配置，批量巡检时无需每台设备各查一次数据库——
    缓存后一轮巡检（几十上百台）只需 1 次查询，显著降低并发连接峰值。
    """
    now = time.time()
    cache = _CORR_RULES_CACHE
    if cache['rules'] is not None and (now - cache['ts']) < _CORR_RULES_TTL:
        return cache['rules']
    rules_list: list[dict] = []
    try:
        conn_rules = get_db_connection()
        try:
            rule_rows = conn_rules.execute(
                'SELECT * FROM inspection_correlation_rules WHERE enabled = 1'
            ).fetchall()
            rules_list = [dict(r) for r in rule_rows]
        finally:
            conn_rules.close()
    except Exception:
        rules_list = []
    cache['rules'] = rules_list
    cache['ts'] = now
    return rules_list


def _inspect_network_device(device: dict, alert_stats: dict, inspection_items: list[dict], use_admin_creds: bool = False, check_items: list[str] | None = None) -> dict[str, Any]:
    """
    网络设备巡检：支持 SNMP 性能指标采集 + SSH/CLI 协议/合规指标采集。
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
        'ping_ok': 0, 'ssh_ok': None, 'ssh_error': '',
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
    icmp_items = [it for it in inspection_items if (it.get('method') or '').upper() == 'ICMP']
    tcp_items = [it for it in inspection_items if (it.get('method') or '').upper() == 'TCP']
    cli_items = [it for it in inspection_items if (it.get('method') or '').upper() == 'CLI']
    snmp_items = [it for it in inspection_items if (it.get('method') or '').upper() == 'SNMP']
    ssh_check: dict[str, Any] | None = None
    direct_probe_health_deduct = 0

    def _record_connection_probe_item(item: dict, value: Any, unavailable_reason: str) -> None:
        nonlocal direct_probe_health_deduct
        key = str(item.get('check_key') or '')
        if value is None:
            metrics[key] = {'value': None, 'error': unavailable_reason}
            metrics[f'{key}_status'] = 'NOT_COLLECTED'
            return
        metrics[key] = value
        direction = item.get('threshold_direction') or 'above'
        relation = _inspection_threshold_relation(direction)
        critical = item.get('critical_threshold')
        warning = item.get('warning_threshold')
        if _inspection_threshold_is_crossed(value, critical, direction):
            findings.append(make_finding(
                'data_error',
                f"{item.get('name_zh') or key} 严重超标: {value} {relation}阈值 {critical}",
                severity='critical',
            ))
            result['health_status'] = 'critical'
            direct_probe_health_deduct += 25
            metrics[f'{key}_status'] = 'ERROR'
        elif _inspection_threshold_is_crossed(value, warning, direction):
            findings.append(make_finding(
                'data_error',
                f"{item.get('name_zh') or key} 达到告警线: {value} {relation}阈值 {warning}",
                severity='warning',
            ))
            if result['health_status'] == 'healthy':
                result['health_status'] = 'warning'
            direct_probe_health_deduct += 14
            metrics[f'{key}_status'] = 'WARNING'
        else:
            metrics[f'{key}_status'] = 'SUCCESS'

    # 1. ICMP 连通性
    ping_result = _ping_device(ip, count=2, timeout=2)
    result['ping_ok'] = 1 if ping_result.get('success') else 0
    result['ping_latency_ms'] = ping_result.get('latency_ms')

    if not result['ping_ok']:
        # R2.3: ICMP 不可达
        findings.append(make_finding(
            'connectivity_error',
            '设备 ICMP 不可达，请检查设备电源及网络路径',
        ))
        for item in icmp_items:
            _record_connection_probe_item(item, None, '设备 ICMP 探测失败，本轮未采集时延指标')
        for item in tcp_items:
            _record_connection_probe_item(item, None, '设备 ICMP 探测失败，本轮未执行 TCP 端口探测')
        result['health_status'] = 'critical'
        result['health_score'] = 0
        result['metrics_json'] = json.dumps(metrics, ensure_ascii=False)
        result['findings_json'] = json.dumps(findings, ensure_ascii=False)
        return result

    for item in icmp_items:
        _record_connection_probe_item(
            item,
            ping_result.get('latency_ms'),
            'ICMP 探测未提供可解析的 RTT 样本',
        )

    # ── 分流：SNMP 性能指标 vs CLI 协议/合规指标 ──
    routing_protocol_items = {
        protocol: [it for it in snmp_items if _inspection_routing_protocol(it) == protocol]
        for protocol in ('bgp', 'ospf')
    }
    routing_protocol_items = {protocol: items for protocol, items in routing_protocol_items.items() if items}
    routing_protocol_snapshots: dict[str, dict[str, Any]] = {}
    routing_protocol_errors: dict[str, str] = {}
    routing_cli_fallback_failed = False

    for protocol in routing_protocol_items:
        try:
            from services.routing_neighbor_service import collect_device_routing_neighbors_snmp

            snapshot = collect_device_routing_neighbors_snmp(device, protocol)
            if snapshot.get('status') == 'no_neighbors':
                raise RuntimeError(f'{protocol.upper()} SNMP neighbor table returned no rows')
            down_count, peer_states, state_error = _routing_neighbor_state_snapshot(snapshot['records'], protocol)
            if state_error:
                raise RuntimeError(state_error)
            routing_protocol_snapshots[protocol] = {
                'records': snapshot['records'],
                'down_count': down_count,
                'peer_states': peer_states,
                'source': 'snmp',
            }
        except Exception as exc:
            # Do not expose transport details or secrets in ordinary results.
            routing_protocol_errors[protocol] = f'SNMP {protocol.upper()} 邻居采集失败（{type(exc).__name__}）'

    if routing_protocol_errors:
        try:
            from services.operational_data_service import collect_operational_data

            fallback_protocols = list(routing_protocol_errors)
            fallback_payload = collect_operational_data(device, categories=fallback_protocols)
            fallback_categories = {
                str(category.get('key') or ''): category
                for category in (fallback_payload.get('categories') or [])
                if isinstance(category, dict)
            }
            for protocol in fallback_protocols:
                category = fallback_categories.get(protocol) or {}
                if not category.get('success'):
                    error_code = str(category.get('error_code') or 'CLI fallback unavailable')
                    routing_protocol_errors[protocol] = f'{protocol.upper()} SNMP 失败且 CLI 回退失败（{error_code}）'
                    routing_cli_fallback_failed = True
                    continue
                records = category.get('records') or []
                if not records:
                    routing_protocol_errors[protocol] = f'{protocol.upper()} CLI 回退未返回邻居记录'
                    routing_cli_fallback_failed = True
                    continue
                down_count, peer_states, state_error = _routing_neighbor_state_snapshot(records, protocol)
                if state_error:
                    routing_protocol_errors[protocol] = f'{protocol.upper()} CLI 回退解析失败'
                    routing_cli_fallback_failed = True
                    continue
                routing_protocol_snapshots[protocol] = {
                    'records': records,
                    'down_count': down_count,
                    'peer_states': peer_states,
                    'source': 'cli_fallback',
                }
                routing_protocol_errors.pop(protocol, None)
        except Exception as exc:
            for protocol in list(routing_protocol_errors):
                routing_protocol_errors[protocol] = f'{protocol.upper()} SNMP 失败且 CLI 回退失败（{type(exc).__name__}）'
            routing_cli_fallback_failed = True

    # 2a. SNMP 采集（不需要 SSH）
    snmp_metrics: dict = {}
    snmp_interfaces: list[dict] = []
    non_protocol_snmp_items = [item for item in snmp_items if _inspection_routing_protocol(item) is None]
    if non_protocol_snmp_items:
        needs_interface_snapshot = any(
            'intf_down' in str(item.get('check_key') or '').casefold()
            or 'interface_down' in str(item.get('check_key') or '').casefold()
            for item in non_protocol_snmp_items
        )
        snmp_metrics, snmp_interfaces = _collect_snmp_for_inspection(
            device,
            include_interface_snapshot=needs_interface_snapshot,
        )
        # 填充 result 的标准字段
        if snmp_metrics.get('cpu_usage') is not None:
            result['cpu_usage'] = snmp_metrics['cpu_usage']
        if snmp_metrics.get('memory_usage') is not None:
            result['memory_usage'] = snmp_metrics['memory_usage']
        if snmp_metrics.get('temp') is not None:
            result['temperature'] = snmp_metrics['temp']
        if snmp_metrics.get('fan_status') is not None:
            result['fan_status'] = snmp_metrics['fan_status']
        if snmp_metrics.get('psu_status') is not None:
            result['psu_status'] = snmp_metrics['psu_status']
        # 接口统计
        if snmp_interfaces:
            result['interface_total'] = len(snmp_interfaces)
            result['interface_up'] = sum(1 for i in snmp_interfaces if str(i.get('status', '')).lower() in ('up', '1'))
            result['interface_down'] = sum(
                1 for i in snmp_interfaces
                if str(i.get('status', '')).lower() in ('down', '2', 'notconnect')
                and str(i.get('admin_status', '')).lower() not in ('down', '2')
            )

    # 2b. SSH/CLI 采集（仅在有 CLI 指标或自定义 check_items 时执行）
    raw_outputs: dict[str, str] = {}
    if cli_items or tcp_items or check_items:
        mgmt_port = int(device.get('management_port') or 22)
        ssh_check = _check_ssh(ip, port=mgmt_port, timeout=3)
        if not ssh_check.get('success'):
            result['ssh_ok'] = 0
            result['ssh_error'] = ssh_check.get('error', '')
            for item in tcp_items:
                _record_connection_probe_item(
                    item,
                    None,
                    'SSH 管理端口探测失败；连接错误已在巡检结果中记录',
                )
            findings.append(make_finding(
                'connectivity_error',
                f'SSH 端口 {mgmt_port} 不通，请检查防火墙策略或 SSH 服务状态',
                raw_error=ssh_check.get('error', ''),
            ))
            # SSH 失败但 SNMP 已采集，不直接 return，降低 health 继续处理 SNMP 指标
            if not snmp_items:
                result['health_status'] = 'critical'
                result['health_score'] = 20
                result['metrics_json'] = json.dumps(metrics, ensure_ascii=False)
                result['findings_json'] = json.dumps(findings, ensure_ascii=False)
                return result
            # 有 SNMP 指标，继续处理
            result['health_status'] = 'warning'
            cli_items = []  # 清空 CLI 指标，不再尝试 SSH 采集
        else:
            for item in tcp_items:
                _record_connection_probe_item(
                    item,
                    ssh_check.get('latency_ms'),
                    'TCP 管理端口探测未提供可解析的连接时延',
                )
            # 3. 收集所有需要的命令（去重）
            commands_set = {
                item.get('command') or ''
                for item in cli_items
                if item.get('command')
            }
            if check_items:
                matched_cmds_and_keys = {item.get('command') for item in inspection_items} | {item.get('check_key') for item in inspection_items}
                for ci in check_items:
                    ci_clean = ci.strip()
                    if ci_clean and ci_clean not in matched_cmds_and_keys:
                        commands_set.add(ci_clean)

            commands_needed = sorted(list(commands_set))
            if commands_needed:
                # 如果有任何单个指标要求特权，则开启特权
                if any(item.get('use_admin_creds', 0) == 1 for item in cli_items):
                    use_admin_creds = True

                # 4. 一次 SSH 连接采集所有命令
                try:
                    raw_outputs = _netmiko_collect(device, commands_needed, use_admin_creds)
                    result['ssh_ok'] = 1
                except Exception as e:
                    result['ssh_ok'] = 0
                    err_str = str(e)
                    result['ssh_error'] = err_str
                    # R2.5/R2.6/R2.7: SSH 认证失败 / 连接超时 / 会话中断
                    err_lower = err_str.lower()
                    if 'authentication' in err_lower or '认证失败' in err_str:
                        findings.append(make_finding(
                            'auth_error',
                            'SSH 认证失败，请核查账号密码或密钥配置',
                            raw_error=err_str,
                        ))
                    elif 'timeout' in err_lower or 'timed out' in err_lower or '连接超时' in err_str:
                        findings.append(make_finding(
                            'connectivity_error',
                            'SSH 连接超时，设备响应缓慢或网络延迟过高',
                            raw_error=err_str,
                        ))
                    elif 'reset' in err_lower or 'disconnected' in err_lower or '中断' in err_str:
                        findings.append(make_finding(
                            'connectivity_error',
                            'SSH 会话意外中断，设备可能已重启或连接被重置',
                            raw_error=err_str,
                            severity='warning',
                        ))
                    else:
                        findings.append(make_finding(
                            'connectivity_error',
                            f'SSH 采集失败: {err_str}',
                            raw_error=err_str,
                        ))
                    # SSH 失败：如果有 SNMP 指标，不直接 return
                    if not snmp_items:
                        result['health_status'] = 'critical'
                        result['health_score'] = min(
                            30,
                            max(0, 100 - direct_probe_health_deduct),
                        )
                        result['metrics_json'] = json.dumps(metrics, ensure_ascii=False)
                        result['findings_json'] = json.dumps(findings, ensure_ascii=False)
                        return result
                    result['health_status'] = 'warning'
                    cli_items = []  # 不再处理 CLI 指标
            result['ssh_ok'] = 1
    else:
        # No CLI checks means SSH was not tested. A successful CLI fallback
        # for a routing-protocol SNMP item is the exception: that path did
        # open an SSH session and can report it as checked.
        result['ssh_ok'] = (
            1 if any(
                snapshot.get('source') == 'cli_fallback'
                for snapshot in routing_protocol_snapshots.values()
            ) else None
        )
    if routing_cli_fallback_failed:
        result['ssh_ok'] = 0

    # R2.8: Enable 提权失败 — 记录 warning finding，但继续执行
    enable_err = raw_outputs.pop('__ENABLE_FAILED__', None)
    if enable_err:
        findings.append(make_finding(
            'auth_error',
            'Enable 提权失败，部分 show 命令可能被拒绝，请检查 enable secret 或 AAA 配置',
            raw_error=str(enable_err),
            severity='warning',
        ))
        if result['health_status'] == 'healthy':
            result['health_status'] = 'warning'

    # 5. 对每个指标进行解析和判定（合并 CLI + SNMP 指标）
    health_deduct = 0
    active_items = cli_items + snmp_items  # 实际要评估的指标列表
    # 预取上次巡检指标（一次 DB 连接），供 diff 对比 / 智能分析 / 关联分析复用，
    # 避免循环内每个 diff 指标都单独开一个数据库连接（降低并发连接峰值）。
    last_metrics_raw = _get_last_metrics_dict(device_id) or {}
    for item in active_items:
        check_key = item.get('check_key') or ''
        name_zh = item.get('name_zh') or item.get('name') or check_key
        parse_type = (item.get('parse_type') or 'numeric').lower()
        warn_threshold = item.get('warning_threshold')
        crit_threshold = item.get('critical_threshold')
        item_method = (item.get('method') or '').upper()
        item_protocol = _inspection_routing_protocol(item) if item_method == 'SNMP' else None
        item_peer_states: dict[str, str] | None = None

        # 根据采集方式调度提取器
        if item_method == 'SNMP':
            if item_protocol and item_protocol in routing_protocol_snapshots:
                protocol_snapshot = routing_protocol_snapshots[item_protocol]
                value = protocol_snapshot['down_count']
                item_peer_states = protocol_snapshot['peer_states']
                err = ''
            elif item_protocol:
                value, err = None, routing_protocol_errors.get(item_protocol, f'{item_protocol.upper()} SNMP 邻居采集失败')
            else:
                value, err = _extract_snmp_item_value(item, snmp_metrics, snmp_interfaces)
        else:
            value, err = _extract_item_value(item, raw_outputs)

        if err and value is None:
            if item_method == 'SNMP' and _is_unavailable_snmp_snapshot_error(err):
                metrics[check_key] = {'value': None, 'error': err}
                metrics[f"{check_key}_status"] = 'NOT_COLLECTED'
                continue
            # 命令级 / 解析级异常：写入 metrics_json 的 error 子字段（R2.9–R2.16）
            metrics[check_key] = {'value': None, 'error': err}
            metrics[f"{check_key}_status"] = "ERROR"
            findings.append(make_finding(
                'parse_error' if 'TextFSM' in err or '解析' in err or '模板' in err or '字段' in err else 'command_error',
                f"{name_zh} 数据采集/解析失败: {err}",
                raw_error=err,
            ))
            health_deduct += 10
            if result['health_status'] == 'healthy':
                result['health_status'] = 'warning'
            continue

        if value is None:
            metrics[check_key] = {'value': None, 'error': '指标未采集'}
            metrics[f"{check_key}_status"] = 'NOT_COLLECTED'
            continue

        metrics[check_key] = value
        if item_protocol and item_protocol in routing_protocol_snapshots:
            metrics[f'{check_key}_collector'] = routing_protocol_snapshots[item_protocol].get('source', 'snmp')
        if item_peer_states is not None:
            _record_routing_neighbor_state_changes(
                item,
                item_peer_states,
                last_metrics_raw,
                metrics,
                findings,
            )
            value = metrics.get(check_key, value)
        is_abnormal = False
        metric_status = 'SUCCESS'
        threshold_direction = item.get('threshold_direction') or 'above'
        threshold_relation = _inspection_threshold_relation(threshold_direction)

        # 阈值判定
        if parse_type in ('numeric', 'count') and isinstance(value, (int, float)):
            if _inspection_threshold_is_crossed(value, crit_threshold, threshold_direction):
                findings.append(make_finding(
                    'data_error',
                    f"{name_zh} 严重超标: {value} {threshold_relation}阈值 {crit_threshold}",
                    severity='critical',
                ))
                health_deduct += 25
                if result['health_status'] != 'critical':
                    result['health_status'] = 'critical'
                is_abnormal = True
            elif _inspection_threshold_is_crossed(value, warn_threshold, threshold_direction):
                findings.append(make_finding(
                    'data_error',
                    f"{name_zh} 达到告警线: {value} {threshold_relation}阈值 {warn_threshold}",
                    severity='warning',
                ))
                health_deduct += 14
                if result['health_status'] == 'healthy':
                    result['health_status'] = 'warning'
                is_abnormal = True

        elif parse_type == 'diff' and isinstance(value, (int, float)):
            last_val = None
            _lv = last_metrics_raw.get(check_key)
            if _lv is not None:
                try:
                    last_val = float(_lv)
                except (TypeError, ValueError):
                    last_val = None
            if last_val is not None and last_val > 0:
                change_pct = abs(value - last_val) / last_val * 100.0
                metrics[f"{check_key}_last"] = last_val
                metrics[f"{check_key}_change_pct"] = round(change_pct, 2)
                if _inspection_threshold_is_crossed(change_pct, crit_threshold, threshold_direction):
                    findings.append(make_finding(
                        'data_error',
                        f"{name_zh} 变化异常: 上次 {last_val} → 本次 {value}（变化 {change_pct:.1f}%，{threshold_relation}阈值 {crit_threshold}%）",
                        severity='critical',
                    ))
                    health_deduct += 20
                    if result['health_status'] != 'critical':
                        result['health_status'] = 'critical'
                    is_abnormal = True
                elif _inspection_threshold_is_crossed(change_pct, warn_threshold, threshold_direction):
                    findings.append(make_finding(
                        'data_error',
                        f"{name_zh} 变化提醒: 上次 {last_val} → 本次 {value}（变化 {change_pct:.1f}%，{threshold_relation}阈值 {warn_threshold}%）",
                        severity='warning',
                    ))
                    health_deduct += 10
                    if result['health_status'] == 'healthy':
                        result['health_status'] = 'warning'
                    is_abnormal = True

        elif parse_type == 'status' and value is not None:
            component_state = (
                item_method == 'SNMP'
                and (
                    check_key.casefold().endswith('_fan')
                    or check_key.casefold().endswith('_psu')
                )
            )
            metric_status, finding_severity = _classify_inspection_status(
                value,
                item.get('expected_value'),
                component_state=component_state,
                allow_expected_substring=(item.get('category') or '').casefold() == 'compliance',
            )
            if metric_status == 'NOT_COLLECTED':
                # Keep the observed unknown value for diagnostics, but never
                # report it as SUCCESS or compare it against a passing value.
                metrics[f"{check_key}_status"] = metric_status
                continue
            if finding_severity:
                expected = str(item.get('expected_value') or '').strip()
                title = (
                    f"{name_zh} 状态异常: {value}"
                    if not expected
                    else f"{name_zh} 状态不符合期望值: 期望 '{expected}'，实际 '{value}'"
                )
                findings.append(make_finding(
                    'data_error',
                    title,
                    severity=finding_severity,
                ))
                health_deduct += 20 if finding_severity == 'critical' else 5 if (item.get('category') or '').casefold() == 'compliance' else 10
                if finding_severity == 'critical':
                    result['health_status'] = 'critical'
                elif result['health_status'] == 'healthy':
                    result['health_status'] = 'warning'
                is_abnormal = True

        metrics[f"{check_key}_status"] = (
            metric_status if parse_type == 'status' else 'ERROR' if is_abnormal else 'SUCCESS'
        )

    # 5b. 计算合规状态（R8.5）
    compliance_items = [it for it in inspection_items if (it.get('category') or '').lower() == 'compliance']
    if compliance_items:
        compliance_pass = 0
        compliance_total = len(compliance_items)
        for ci in compliance_items:
            ck = ci.get('check_key', '')
            val = metrics.get(ck)
            if val is None or isinstance(val, dict):
                continue  # 采集失败不计入
            if metrics.get(f"{ck}_status") != 'SUCCESS':
                continue
            expected = ci.get('expected_value', '')
            if not expected:
                compliance_pass += 1  # 无期望值的视为通过
            elif _inspection_status_matches_expected(
                val,
                expected,
                allow_substring=True,
            ):
                compliance_pass += 1
        if compliance_total > 0:
            if compliance_pass == compliance_total:
                result['compliance_status'] = 'compliant'
            elif compliance_pass == 0:
                result['compliance_status'] = 'non_compliant'
            else:
                result['compliance_status'] = 'partial'

    # 6. 汇总健康评分
    result['health_score'] = max(0, 100 - health_deduct - direct_probe_health_deduct)
    result['metrics_json'] = json.dumps(metrics, ensure_ascii=False)

    # R10.3: raw_outputs_json 大小限制 — 超过 10MB 时截断最长的命令输出
    _RAW_OUTPUTS_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    # Inspection needs the raw text only while parsing.  Persist a redacted
    # copy so password/community/token material cannot enter the ordinary
    # inspection result table, including legacy/unbound-device paths.
    from services.platform_registry_service import redact_raw_output
    safe_raw_outputs = {
        command: redact_raw_output(str(output or ''))
        for command, output in raw_outputs.items()
    }
    raw_outputs_json = json.dumps(safe_raw_outputs, ensure_ascii=False)
    if len(raw_outputs_json.encode('utf-8')) > _RAW_OUTPUTS_MAX_BYTES:
        # 按命令输出长度降序，逐个截断直到总大小 < 10MB
        truncated_count = 0
        while len(json.dumps(raw_outputs, ensure_ascii=False).encode('utf-8')) > _RAW_OUTPUTS_MAX_BYTES:
            # 找到最长的命令输出
            longest_cmd = max(safe_raw_outputs.keys(), key=lambda k: len(str(safe_raw_outputs.get(k, ''))))
            current_len = len(str(safe_raw_outputs[longest_cmd]))
            # 截断到当前长度的一半，并保留 [TRUNCATED] 标记
            new_len = max(1024, current_len // 2)
            safe_raw_outputs[longest_cmd] = str(safe_raw_outputs[longest_cmd])[:new_len] + "\n... [TRUNCATED: 输出过大] ..."
            truncated_count += 1
            if truncated_count > 50:
                break  # safety guard
        # 追加 info finding
        findings.append(make_finding(
            'data_error',
            '原始输出超过 10MB，已截断',
            severity='info',
        ))
        raw_outputs_json = json.dumps(safe_raw_outputs, ensure_ascii=False)

    result['findings_json'] = json.dumps(findings, ensure_ascii=False)
    result['raw_outputs_json'] = raw_outputs_json

    # 7. 智能分析
    try:
        # 复用前面已预取的上次指标，避免再次查询数据库
        analysis = analyze_device_inspection(device, metrics, inspection_items, last_metrics_raw)
        result['analysis_json'] = json.dumps(analysis, ensure_ascii=False)
    except Exception as ae:
        logger.warning(f"Analysis failed for {hostname}: {ae}")
        result['analysis_json'] = '[]'

    # 7b. 关联分析 — R4.2/R4.3: 多指标关联风险检测
    correlated_risks = []
    try:
        rules_list = _get_correlation_rules_cached()
        if rules_list:
            correlated_risks = correlate_risk_patterns(metrics, rules_list, last_metrics_raw)
    except Exception as ce:
        # R4.7: 关联分析失败不影响其他结果
        logger.warning(f"Correlation analysis failed for {hostname}: {ce}")
        correlated_risks = []

    result['correlated_risks_json'] = json.dumps(correlated_risks, ensure_ascii=False)

    # 映射常用字段以保证 Dashboard 兼容
    for key_pair in (('cpu_util', 'cpu_usage'), ('mem_util', 'memory_usage'), ('memory', 'memory_usage')):
        mkey, rkey = key_pair
        for k, v in metrics.items():
            if k.endswith(mkey) and isinstance(v, (int, float)):
                result[rkey] = v
                break

    return result

def _inspect_single_device(device: dict[str, Any], alert_stats: dict[str, int], check_items: list[str] | None = None, use_admin_creds: bool = False) -> dict[str, Any]:
    device_id = str(device.get('id') or '')
    ip = device.get('ip_address') or ''
    hostname = device.get('hostname') or ip
    platform_name = (device.get('platform') or 'Linux').lower()

    # ── 先判定设备类型（决定按哪个 vendor 加载指标）──
    # 网络设备：走 NetmikoDriver CLI 采集 + TextFSM 解析
    # 服务器：走 Paramiko Shell 脚本采集
    # 注意：设备可能被错误标记 platform（例如服务器误填成 cisco_ios），
    # 因此只要 device_category 含 'server' 就按服务器处理，并用 'linux'
    # 作为指标 vendor 匹配，避免加载不到任何 Linux Shell 指标。
    category = str(device.get('device_category') or '').lower()
    is_server = platform_name in {p.lower() for p in _SERVER_PLATFORMS} or 'server' in category
    is_network_device = platform_name in _NETWORK_PLATFORMS and not is_server

    # 服务器统一用 'linux' 作为指标 vendor；网络设备使用其平台名。
    item_vendor = 'linux' if is_server else platform_name

    # ── 加载该平台适用的巡检指标（enabled=1，vendor 匹配或为 Generic/空）──
    # vendor 比较使用 LOWER() 以兼容库中以 'Linux'/'Cisco' 等首字母大写存储的写法。
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM inspection_items "
            "WHERE (LOWER(vendor) = LOWER(?) OR LOWER(vendor) = 'generic' OR vendor = '') "
            "AND COALESCE(enabled, 1) = 1",
            (item_vendor,)
        ).fetchall()
        matched_items = [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to load inspection items for {item_vendor}: {e}")
        matched_items = []
    finally:
        conn.close()

    # Filter matched_items if check_items is specified
    if check_items:
        norm_checks = {c.strip().lower() for c in check_items if c.strip()}
        matched_items = [
            it for it in matched_items
            if (it.get('check_key') or '').strip().lower() in norm_checks
            or (it.get('command') or '').strip().lower() in norm_checks
        ]

    if any(it.get('use_admin_creds', 0) == 1 for it in matched_items):
        use_admin_creds = True

    if is_network_device:
        # Preserve the shared connectivity probes as first-class metric sources.
        cli_items = [it for it in matched_items if (it.get('method') or '').upper() == 'CLI']
        snmp_items = [it for it in matched_items if (it.get('method') or '').upper() == 'SNMP']
        connection_items = [
            it for it in matched_items
            if (it.get('method') or '').upper() in {'ICMP', 'TCP'}
        ]
        all_items = cli_items + snmp_items + connection_items
        return _inspect_network_device(device, alert_stats, all_items, use_admin_creds, check_items)

    if is_server:
        # 只选 Shell 方式 of 指标（原有逻辑）
        shell_items = [it for it in matched_items if (it.get('method') or '') == 'Shell']
        return _inspect_server_device(device, alert_stats, shell_items)

    # 默认当服务器处理（兼容旧数据）
    shell_items = [it for it in matched_items if (it.get('method') or '') == 'Shell']
    return _inspect_server_device(device, alert_stats, shell_items)


def _inspect_server_device(device: dict[str, Any], alert_stats: dict[str, int], shell_items: list[dict]) -> dict[str, Any]:
    """服务器巡检（Shell 脚本方式），按指标绑定脚本分组执行并兼容旧配置。"""
    from services.platform_registry_service import redact_raw_output

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
    raw_outputs = {}

    def _parse_metric_from_integrated(output: str, key: str) -> tuple[bool, Any]:
        pattern = rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$"
        for line in output.split('\n'):
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                raw_value = match.group(1).strip()
                if re.fullmatch(r"(?:NA|N/A|NOT[_ ]COLLECTED|UNAVAILABLE)", raw_value, re.IGNORECASE):
                    return True, None
                if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", raw_value):
                    try:
                        return True, float(raw_value)
                    except (TypeError, ValueError, OverflowError):
                        return True, None
                return True, raw_value or None
        return False, None

    conn = get_db_connection()
    try:
        # Use the explicitly bound metric scripts when definitions provide
        # them.  The comprehensive script remains a compatibility fallback
        # for legacy/custom items without a script_id and for telemetry, but it
        # must not silently override the script shown for each built-in metric.
        use_single_script = False
        script_row = conn.execute("SELECT content FROM scripts WHERE id = ?", ("insp_linux_full",)).fetchone()
        bound_script_items = [
            item for item in shell_items
            if str(item.get('script_id') or '').strip()
        ]
        if script_row and script_row['content'] and shell_items and len(bound_script_items) != len(shell_items):
            use_single_script = True
            script_content = script_row['content']

        if use_single_script:
            raw_output = _execute_shell_script(ip, script_content, device)
            raw_outputs['insp_linux_full'] = raw_output

            if "ERROR:" in raw_output:
                result['ssh_ok'] = 0
                result['ssh_error'] = raw_output
                result['health_status'] = 'critical'
                result['health_score'] = 0
                findings.append(make_finding(
                    'connectivity_error',
                    f"SSH 连接或综合巡检脚本执行失败: {raw_output}",
                    raw_error=raw_output,
                    severity='critical',
                ))
                for item in shell_items:
                    metrics_results[item['check_key']] = {'value': None, 'error': raw_output}
                    metrics_results[f"{item['check_key']}_status"] = "ERROR"
            else:
                # Parse metrics from --- METRICS ---
                parsed_metrics = {}
                metrics_block_started = False
                for line in raw_output.splitlines():
                    line = line.strip()
                    if line == "--- METRICS ---":
                        metrics_block_started = True
                        continue
                    if metrics_block_started:
                        if line.startswith("==="):
                            metrics_block_started = False
                            continue
                        if ":" in line:
                            parts = line.split(":", 1)
                            m_key = parts[0].strip()
                            m_val_str = parts[1].strip()
                            try:
                                parsed_metrics[m_key] = float(m_val_str)
                            except ValueError:
                                parsed_metrics[m_key] = m_val_str

                # Map values and explicit per-metric collection/severity states.
                # A non-numeric sentinel must remain unknown, never silently pass
                # as SUCCESS or participate in numeric threshold comparisons.
                not_collected_states = {'UNCHECKED', 'NOT_COLLECTED', 'UNAVAILABLE'}
                explicit_metric_statuses = {
                    key[:-7]: str(value or '').strip().upper()
                    for key, value in parsed_metrics.items()
                    if key.endswith('_status')
                }
                for m_key, m_val in parsed_metrics.items():
                    if m_key.endswith('_status'):
                        metrics_results[m_key] = str(m_val)
                        continue
                    explicit_status = explicit_metric_statuses.get(m_key, '')
                    is_sentinel = isinstance(m_val, str) and m_val.strip().upper() in {
                        'NA', 'N/A', 'NULL', 'NONE',
                    }
                    if explicit_status in not_collected_states:
                        metrics_results[m_key] = {'value': None, 'error': '指标未采集'}
                        metrics_results[f"{m_key}_status"] = 'NOT_COLLECTED'
                    elif is_sentinel and explicit_status in {'ERROR', 'WARNING'}:
                        metrics_results[m_key] = {'value': None, 'error': '脚本已判定异常，但未提供数值'}
                        metrics_results[f"{m_key}_status"] = explicit_status
                    elif is_sentinel:
                        metrics_results[m_key] = {'value': None, 'error': '指标未采集'}
                        metrics_results[f"{m_key}_status"] = 'NOT_COLLECTED'
                    else:
                        metrics_results[m_key] = m_val
                        metrics_results[f"{m_key}_status"] = explicit_status or 'SUCCESS'

                metric_threshold_findings = []
                for item in shell_items:
                    ck = item['check_key']
                    explicit_status = explicit_metric_statuses.get(ck, '')
                    value = parsed_metrics.get(ck)
                    is_sentinel = isinstance(value, str) and value.strip().upper() in {
                        'NA', 'N/A', 'NULL', 'NONE',
                    }
                    if ck not in parsed_metrics:
                        if explicit_status in not_collected_states:
                            metrics_results[ck] = {'value': None, 'error': '指标未采集'}
                            metrics_results[f"{ck}_status"] = 'NOT_COLLECTED'
                        elif explicit_status in {'ERROR', 'WARNING'}:
                            metrics_results[ck] = {'value': None, 'error': '脚本已判定异常，但未提供数值'}
                            metrics_results[f"{ck}_status"] = explicit_status
                        else:
                            metrics_results[ck] = {'value': None, 'error': '未在综合巡检中采集到此指标'}
                            metrics_results[f"{ck}_status"] = 'NOT_COLLECTED'
                    elif explicit_status in not_collected_states:
                        metrics_results[ck] = {'value': None, 'error': '指标未采集'}
                        metrics_results[f"{ck}_status"] = 'NOT_COLLECTED'
                    elif is_sentinel and explicit_status in {'ERROR', 'WARNING'}:
                        metrics_results[ck] = {'value': None, 'error': '脚本已判定异常，但未提供数值'}
                        metrics_results[f"{ck}_status"] = explicit_status
                    elif is_sentinel:
                        metrics_results[ck] = {'value': None, 'error': '指标未采集'}
                        metrics_results[f"{ck}_status"] = 'NOT_COLLECTED'
                    elif (item.get('parse_type') or 'numeric').casefold() == 'status':
                        status_code, finding_severity = _classify_inspection_status(
                            value,
                            item.get('expected_value'),
                        )
                        if status_code == 'NOT_COLLECTED':
                            metrics_results[ck] = {'value': None, 'error': '指标未采集'}
                            metrics_results[f"{ck}_status"] = 'NOT_COLLECTED'
                        else:
                            metrics_results[ck] = value
                            current_status = explicit_status or 'SUCCESS'
                            severity_rank = {'SUCCESS': 0, 'NOT_APPLICABLE': 0, 'UNCHECKED': 0, 'NOT_COLLECTED': 0,
                                             'WARNING': 1, 'ERROR': 2, 'CRITICAL': 2}
                            proposed_status = (
                                'ERROR' if finding_severity == 'critical'
                                else 'WARNING' if finding_severity == 'warning'
                                else 'SUCCESS'
                            )
                            if severity_rank.get(proposed_status, 0) > severity_rank.get(current_status, 0):
                                metrics_results[f"{ck}_status"] = proposed_status
                                metric_threshold_findings.append((
                                    proposed_status,
                                    f"{item.get('name_zh') or ck} 状态不符合期望值 {item.get('expected_value')!r}（实际 {value!r}）",
                                ))
                    elif isinstance(value, (int, float)):
                        # Script checks carry richer platform-specific status. The configured
                        # item threshold still applies; keep whichever result is more severe.
                        current_status = explicit_status or 'SUCCESS'
                        severity_rank = {'SUCCESS': 0, 'NOT_APPLICABLE': 0, 'UNCHECKED': 0, 'NOT_COLLECTED': 0,
                                         'WARNING': 1, 'ERROR': 2, 'CRITICAL': 2}
                        threshold_status = ''
                        w = item.get('warning_threshold')
                        c = item.get('critical_threshold')
                        direction = item.get('threshold_direction') or 'above'
                        relation = _inspection_threshold_relation(direction)
                        if _inspection_threshold_is_crossed(value, c, direction):
                            threshold_status = 'ERROR'
                        elif _inspection_threshold_is_crossed(value, w, direction):
                            threshold_status = 'WARNING'
                        if threshold_status and severity_rank.get(threshold_status, 0) > severity_rank.get(current_status, 0):
                            metrics_results[f"{ck}_status"] = threshold_status
                            threshold_text = (
                                f"{ck}={value} 严重项{relation}阈值 {c}"
                                if threshold_status == 'ERROR'
                                else f"{ck}={value} 关注项{relation}阈值 {w}"
                            )
                            metric_threshold_findings.append((threshold_status, threshold_text))

                # Parse finding lines starting with [WARNING] or [ERROR]
                total_errors = 0
                total_warnings = 0
                overall_status = "SUCCESS"

                for line in raw_output.splitlines():
                    line = line.strip()
                    if "发现严重错误" in line and ":" in line:
                        try:
                            digits = re.findall(r'\d+', line.split(":", 1)[1])
                            if digits:
                                total_errors = int(digits[0])
                        except Exception:
                            pass
                    elif "发现警告信息" in line and ":" in line:
                        try:
                            digits = re.findall(r'\d+', line.split(":", 1)[1])
                            if digits:
                                total_warnings = int(digits[0])
                        except Exception:
                            pass
                    elif "综合健康评级" in line and ":" in line:
                        try:
                            overall_status = line.split(":", 1)[1].strip().replace("[", "").replace("]", "")
                        except Exception:
                            pass

                # Add findings for all issues, skipping section headers
                for line in raw_output.splitlines():
                    line = line.strip()
                    if line.startswith("[WARNING]"):
                        msg = line.replace("[WARNING]", "").strip()
                        if re.match(r'^\d+\.', msg):
                            continue
                        findings.append(make_finding(
                            'data_error',
                            msg,
                            severity='warning',
                        ))
                    elif line.startswith("[ERROR]"):
                        msg = line.replace("[ERROR]", "").strip()
                        if re.match(r'^\d+\.', msg):
                            continue
                        findings.append(make_finding(
                            'data_error',
                            msg,
                            severity='critical',
                        ))

                for threshold_status, threshold_text in metric_threshold_findings:
                    is_critical = threshold_status == 'ERROR'
                    findings.append(make_finding(
                        'data_error',
                        f"巡检项阈值判定: {threshold_text}",
                        severity='critical' if is_critical else 'warning',
                    ))
                    if is_critical:
                        total_errors += 1
                    else:
                        total_warnings += 1

                # Update health score and status
                if total_errors > 0 or overall_status == 'ERROR':
                    result['health_status'] = 'critical'
                elif total_warnings > 0 or overall_status == 'WARNING':
                    result['health_status'] = 'warning'
                else:
                    result['health_status'] = 'healthy'

                result['health_score'] = max(0, 100 - total_errors * 25 - total_warnings * 10)

                # Ensure "========== HEALTH CHECK ==========" is present for report_generator compatibility
                if "========== HEALTH CHECK ==========" not in raw_output:
                    cpu_util_val = parsed_metrics.get('cpu_util', 0.0)
                    load_val = parsed_metrics.get('cpu_load', 0.0)
                    mem_val = parsed_metrics.get('mem_avail', 0.0)
                    swap_val = parsed_metrics.get('swap_util', 0.0)
                    io_val = parsed_metrics.get('io_wait', 0.0)
                    disk_val = parsed_metrics.get('disk_util', 0.0)
                    inode_val = parsed_metrics.get('inode_util', 0.0)
                    tcp_estab_val = parsed_metrics.get('tcp_conns', 0)

                    def get_status_from_findings(keyword, default='OK'):
                        has_crit = any(keyword in f['message'] and f['severity'] == 'critical' for f in findings)
                        has_warn = any(keyword in f['message'] and f['severity'] == 'warning' for f in findings)
                        if has_crit: return 'CRITICAL'
                        if has_warn: return 'ERROR'
                        return default

                    cpu_status = get_status_from_findings('CPU', 'OK')
                    load_status = get_status_from_findings('负载', 'OK')
                    mem_status = get_status_from_findings('内存', 'OK')
                    disk_status = get_status_from_findings('挂载点', 'OK')
                    inode_status = get_status_from_findings('Inode', 'OK')
                    io_status = get_status_from_findings('I/O', 'OK')
                    tcp_status = get_status_from_findings('TCP', 'OK')

                    rep_overall = "OK"
                    if result['health_status'] == 'critical': rep_overall = "CRITICAL"
                    elif result['health_status'] == 'warning': rep_overall = "ERROR"

                    health_check_block = []
                    health_check_block.append("========== HEALTH CHECK ==========")
                    health_check_block.append(f"Host: {hostname}")
                    health_check_block.append(f"Time: {now}")
                    health_check_block.append(f"OVERALL: {rep_overall}")
                    health_check_block.append(f"SUMMARY: 发现严重错误 {total_errors} 个，警告信息 {total_warnings} 个")
                    health_check_block.append(f"CPU Usage(%) {cpu_util_val} {cpu_status}")
                    health_check_block.append(f"Load/Core {load_val} {load_status}")
                    health_check_block.append(f"Memory(%) {mem_val} {mem_status}")
                    health_check_block.append(f"Disk Usage(%) {disk_val} {disk_status}")
                    health_check_block.append(f"Inode Usage(%) {inode_val} {inode_status}")
                    health_check_block.append(f"IOWait(%) {io_val} {io_status}")
                    health_check_block.append(f"TCP ESTAB {tcp_estab_val} {tcp_status}")
                    health_check_block.append("==================================")

                    raw_outputs['insp_linux_full'] = raw_output + "\n\n" + "\n".join(health_check_block)

        else:
            # Group shell items by script_id to run each unique script only once
            items_by_script = {}
            for item in shell_items:
                script_id = item.get('script_id') or ''
                if script_id:
                    items_by_script.setdefault(script_id, []).append(item)

            # Run scripts and cache their raw outputs
            script_outputs = {}
            for script_id in items_by_script.keys():
                script_row = conn.execute("SELECT content FROM scripts WHERE id = ?", (script_id,)).fetchone()
                if not script_row:
                    continue
                raw_output = _execute_shell_script(ip, script_row['content'], device)
                script_outputs[script_id] = raw_output
                raw_outputs[f"script_{script_id}"] = raw_output

            # Process each shell item
            for item in shell_items:
                script_id = item.get('script_id') or ''
                cmd_key = item.get('check_key') or f"script_{script_id}"
                
                raw_output = script_outputs.get(script_id, '')
                if "ERROR:" in raw_output:
                    result['ssh_ok'] = 0
                    result['ssh_error'] = raw_output
                    result['health_status'] = 'critical'
                    result['health_score'] = 0
                    findings.append(make_finding(
                        'connectivity_error',
                        f"SSH 连接或脚本执行失败 ({item.get('name_zh')}): {raw_output}",
                        raw_error=raw_output,
                        severity='critical',
                    ))
                    metrics_results[item['check_key']] = {'value': None, 'error': raw_output}
                    metrics_results[f"{item['check_key']}_status"] = "ERROR"
                    continue

                # Parse metric value (try integrated format first, then fallback to legacy)
                parse_type = (item.get('parse_type') or 'numeric').casefold()
                integrated_key_found, integrated_value = _parse_metric_from_integrated(
                    raw_output,
                    item['check_key'],
                )
                if use_single_script:
                    if not integrated_key_found or integrated_value is None:
                        missing_reason = (
                            '综合脚本未输出该指标'
                            if not integrated_key_found
                            else '指标未采集'
                        )
                        metrics_results[item['check_key']] = {'value': None, 'error': missing_reason}
                        metrics_results[f"{item['check_key']}_status"] = "NOT_COLLECTED"
                        continue
                    val = integrated_value
                else:
                    if _is_no_data_metric_output(raw_output):
                        metrics_results[item['check_key']] = {'value': None, 'error': '指标未采集'}
                        metrics_results[f"{item['check_key']}_status"] = "NOT_COLLECTED"
                        continue
                    val = integrated_value if integrated_key_found else None

                if parse_type == 'status' and val is None and not integrated_key_found:
                    last_output_line = next(
                        (line.strip() for line in reversed(raw_output.splitlines()) if line.strip()),
                        '',
                    )
                    status_match = re.match(
                        rf"^{re.escape(item['check_key'])}\s*:\s*(.*?)\s*$",
                        last_output_line,
                        re.IGNORECASE,
                    )
                    status_text = status_match.group(1) if status_match else last_output_line
                    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", status_text):
                        val = float(status_text)
                    elif status_text:
                        val = status_text
                elif val is None and not use_single_script:
                    val = _extract_numeric_value(raw_output)

                if val is not None:
                    metrics_results[item['check_key']] = val
                    if parse_type == 'status':
                        metric_status, finding_severity = _classify_inspection_status(
                            val,
                            item.get('expected_value'),
                        )
                        metrics_results[f"{item['check_key']}_status"] = metric_status
                        if finding_severity:
                            findings.append(make_finding(
                                'data_error',
                                f"{item['name_zh']} 状态不符合期望值 {item.get('expected_value')!r}（实际 {val!r}）",
                                severity=finding_severity,
                            ))
                            if finding_severity == 'critical':
                                result['health_status'] = 'critical'
                            elif result['health_status'] != 'critical':
                                result['health_status'] = 'warning'
                    else:
                        w = item.get('warning_threshold')
                        c = item.get('critical_threshold')
                        direction = item.get('threshold_direction') or 'above'
                        relation = _inspection_threshold_relation(direction)

                        is_abnormal = False
                        if _inspection_threshold_is_crossed(val, c, direction):
                            findings.append(make_finding(
                                'data_error',
                                f"{item['name_zh']} 严重超标: {val} {relation}阈值 {c}",
                                severity='critical',
                            ))
                            result['health_status'] = 'critical'
                            is_abnormal = True
                        elif _inspection_threshold_is_crossed(val, w, direction):
                            findings.append(make_finding(
                                'data_error',
                                f"{item['name_zh']} 达到告警线: {val} {relation}阈值 {w}",
                                severity='warning',
                            ))
                            if result['health_status'] != 'critical':
                                result['health_status'] = 'warning'
                            is_abnormal = True

                        metrics_results[f"{item['check_key']}_status"] = "ERROR" if is_abnormal else "SUCCESS"
                else:
                    metrics_results[item['check_key']] = {'value': None, 'error': '采集失败或无法提取数值'}
                    metrics_results[f"{item['check_key']}_status"] = "ERROR"

    except Exception as e:
        findings.append(make_finding(
            'system_error',
            f"精细化巡检引擎异常: {str(e)}",
            raw_error=str(e),
            severity='critical',
        ))
    finally:
        conn.close()

    result['metrics_json'] = json.dumps(metrics_results, ensure_ascii=False)
    result['findings_json'] = json.dumps(findings, ensure_ascii=False)
    result['raw_outputs_json'] = json.dumps({
        command: redact_raw_output(str(output or ''))
        for command, output in raw_outputs.items()
    }, ensure_ascii=False)

    # 指标智能分析（与网络设备一致）：基于阈值 + 历史对比生成结论/建议。
    try:
        last_metrics_raw = _get_last_metrics_dict(device_id)
        analysis = analyze_device_inspection(device, metrics_results, shell_items, last_metrics_raw)
        result['analysis_json'] = json.dumps(analysis, ensure_ascii=False)
    except Exception as ae:
        logger.warning(f"[Inspection] Server analysis failed for {hostname}: {ae}")
        result['analysis_json'] = '[]'
    result['correlated_risks_json'] = '[]'

    # 映射常用字段以保证 Dashboard 兼容。
    # `metrics_results[ck]` may be either a numeric scalar (success path) or
    # a `{'value': None, 'error': '...'}` dict (collection failure path). The
    # SQLite/PG driver rejects dict values with
    #   `type 'dict' is not supported`, so we must coerce both shapes into
    # a plain int/float/None before binding to SQL parameters.
    def _scalar(value: Any) -> int | float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, dict):
            inner = value.get('value')
            if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                return inner
            return None
        # Strings / other unexpected types — try one numeric coercion.
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    result['cpu_usage'] = _scalar(metrics_results.get('cpu_util'))
    result['memory_usage'] = _scalar(metrics_results.get('mem_avail'))

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
    use_admin_creds: bool = False,
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
                    _inspect_single_device, dict(d), alert_stats_map.get(str(d.get('id') or ''), {}), check_items, use_admin_creds
                ): d
                for d in devices
            }
            # R10.1: 设备级超时保护 — 每个 future 最多等待 _SSH_COMMAND_TIMEOUT + 10 秒
            device_timeout = _SSH_COMMAND_TIMEOUT + 10
            for future in as_completed(futures):
                device = futures[future]
                try:
                    result = future.result(timeout=device_timeout)
                    result['run_id'] = run_id
                    results.append(result)
                except TimeoutError as te:
                    # R10.1: 设备采集超时
                    logger.error(f"Inspection timeout for {device.get('hostname')}: {te}")
                    future.cancel()
                    results.append({
                        'id': str(uuid.uuid4()),
                        'run_id': run_id,
                        'device_id': str(device.get('id') or ''),
                        'hostname': device.get('hostname') or '',
                        'ip_address': device.get('ip_address') or '',
                        'platform': device.get('platform') or '',
                        'health_status': 'critical',
                        'health_score': 0,
                        'findings_json': json.dumps([make_finding(
                            'system_error',
                            '设备采集超时，已跳过',
                            raw_error=str(te),
                            severity='warning',
                        )], ensure_ascii=False),
                        'checked_at': _beijing_now_iso(),
                        'ping_ok': 0, 'ssh_ok': 0, 'metrics_json': '{}',
                        'analysis_json': '[]', 'raw_outputs_json': '{}',
                    })
                except Exception as exc:
                    logger.error(f"Inspection failed for {device.get('hostname')}: {exc}")
                    results.append({
                        'id': str(uuid.uuid4()),
                        'run_id': run_id,
                        'device_id': str(device.get('id') or ''),
                        'hostname': device.get('hostname') or '',
                        'ip_address': device.get('ip_address') or '',
                        'platform': device.get('platform') or '',
                        'health_status': 'critical',
                        'findings_json': json.dumps([make_finding(
                            'system_error',
                            f'巡检异常: {exc}',
                            raw_error=str(exc),
                            severity='critical',
                        )], ensure_ascii=False),
                        'checked_at': _beijing_now_iso(),
                        'ping_ok': 0, 'ssh_ok': 0, 'metrics_json': '{}'
                    })

        # 4) 存储结果 — R10.2: 逐条写入，单台失败不影响其他设备
        insert_sql = '''INSERT INTO inspection_results
                (id, run_id, device_id, hostname, ip_address, platform, role, site,
                 ping_ok, ping_latency_ms, ssh_ok, ssh_error,
                 health_score, health_status,
                 cpu_usage, memory_usage, temperature, fan_status, psu_status,
                 interface_total, interface_up, interface_down, interface_flapping,
                 interface_high_util, interface_errors,
                 open_alerts, critical_alerts,
                 compliance_status, compliance_findings, findings_json, metrics_json,
                 raw_outputs_json, analysis_json, checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''

        def _scalar_metric(value: Any) -> int | float | None:
            """Coerce a metric value into something the DB driver accepts.

            `inspection_service` mixes "numeric on success" with "dict on
            failure" (e.g. {'value': None, 'error': '...'}). SQLite and
            psycopg2 both reject dict / list parameter binds with
                type 'dict' is not supported
            so we sanitize at the write boundary.
            """
            if value is None:
                return None
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, dict):
                inner = value.get('value')
                if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                    return inner
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        write_failed_count = 0

        def _status_metric_storage(value: Any) -> Any:
            # inspection_results keeps legacy TEXT columns; do not bind a
            # Python bool to PostgreSQL TEXT while preserving the API contract.
            if isinstance(value, bool):
                return 'true' if value else 'false'
            return value

        for r in results:
            try:
                conn.execute(insert_sql, (
                    r.get('id'), r.get('run_id'), r.get('device_id'), r.get('hostname'), r.get('ip_address'),
                    r.get('platform'), r.get('role', ''), r.get('site', ''),
                    r.get('ping_ok', 0), r.get('ping_latency_ms'), r.get('ssh_ok', 0), r.get('ssh_error', ''),
                    r.get('health_score', 100), r.get('health_status', 'unknown'),
                    _scalar_metric(r.get('cpu_usage')),
                    _scalar_metric(r.get('memory_usage')),
                    _scalar_metric(r.get('temperature')),
                    _status_metric_storage(r.get('fan_status', '')),
                    _status_metric_storage(r.get('psu_status', '')),
                    r.get('interface_total', 0), r.get('interface_up', 0), r.get('interface_down', 0),
                    r.get('interface_flapping', 0), r.get('interface_high_util', 0), r.get('interface_errors', 0),
                    r.get('open_alerts', 0), r.get('critical_alerts', 0),
                    r.get('compliance_status', 'unknown'), r.get('compliance_findings', 0),
                    r.get('findings_json', '[]'), r.get('metrics_json', '{}'),
                    r.get('raw_outputs_json', '{}'), r.get('analysis_json', '[]'), r.get('checked_at'),
                ))
            except Exception as write_err:
                # R10.2: 跳过该设备，记录日志，不回滚整次任务
                write_failed_count += 1
                logger.error(
                    f"[Inspection] DB write failed for device {r.get('hostname')} "
                    f"({r.get('device_id')}): {write_err}"
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

        # 汇总全网分析结论 — R10.5: 失败时设为 '{}'
        try:
            run_analysis_sum = summarize_run_analysis(results)
            analysis_sum_json = json.dumps(run_analysis_sum, ensure_ascii=False)
        except Exception as sum_err:
            logger.error(f"[Inspection] Failed to summarize analysis for run {run_id}: {sum_err}")
            analysis_sum_json = '{}'

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
        'id, hostname, ip_address, platform, vendor, model, status, compliance, role, site, '
        'cpu_usage, memory_usage, temp, fan_status, psu_status, '
        'username, password, normal_username, normal_password, '
        'admin_username, admin_password, management_port, enable_password, '
        'credential_source, vault_path, snmp_community, snmp_port, '
        'collection_policy_json'
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
        
        # Match by stable tag code or ID.
        device_ids = conn.execute(f'''
            SELECT DISTINCT dt.resource_id AS device_id
            FROM tag_assignments dt
            JOIN tag_definitions td ON td.id = dt.tag_id
            WHERE dt.resource_type='device' AND (td.code IN ({placeholders}) OR td.id IN ({placeholders}))
        ''', tuple(tags) * 2).fetchall()
        
        ids = [str(r['device_id']) for r in device_ids]
        if not ids:
            return []
        id_placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(f'SELECT {select} FROM devices WHERE id IN ({id_placeholders}) ORDER BY hostname', tuple(ids)).fetchall()
    else:
        rows = conn.execute(f'SELECT {select} FROM devices ORDER BY hostname').fetchall()
    
    res = []
    for r in rows:
        item = dict(r)
        item['interface_data'] = fetch_interface_data(conn, item['id'])
        res.append(item)
    return res


# ──────────────────────────────────────────────
# 查询 API
# ──────────────────────────────────────────────

def _enrich_run_name(conn, run_dict: dict[str, Any]) -> dict[str, Any]:
    schedule_id = run_dict.get('schedule_id')
    created_by = run_dict.get('created_by') or ''
    name = None

    try:
        if schedule_id:
            row = conn.execute('SELECT name FROM inspection_schedules WHERE id = ?', (schedule_id,)).fetchone()
            if row:
                name = row['name']
        elif created_by.startswith('scheduler:'):
            job_id = created_by.split(':', 1)[1]
            row = conn.execute('SELECT name FROM scheduled_jobs WHERE id = ?', (job_id,)).fetchone()
            if row:
                name = row['name']
    except Exception as e:
        logger.warning(f"Error enriching run name for run {run_dict.get('id')}: {e}")

    if name:
        run_dict['schedule_name'] = name
        run_dict['name'] = name
    return run_dict


def get_inspection_runs(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT COUNT(*) FROM inspection_runs').fetchone()[0]
        rows = conn.execute(
            'SELECT * FROM inspection_runs ORDER BY started_at DESC LIMIT ? OFFSET ?',
            (limit, offset),
        ).fetchall()
        
        items = []
        for r in rows:
            rd = dict(r)
            _enrich_run_name(conn, rd)
            items.append(rd)

        return {
            'total': total,
            'items': items,
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
        _enrich_run_name(conn, run_dict)
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

def list_inspection_items(
    *,
    q: str = '',
    category: str = '',
    method: str = '',
    vendor: str = '',
    page: int | None = None,
    page_size: int = 20,
) -> list[dict[str, Any]] | dict[str, Any]:
    conn = get_db_connection()
    try:
        def _filter_parts(
            *,
            include_category: bool,
            include_method: bool,
            include_vendor: bool = True,
        ) -> tuple[list[str], list[str]]:
            clauses: list[str] = []
            params: list[str] = []
            if q.strip():
                clauses.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(name_zh, '')) LIKE ? OR LOWER(COALESCE(check_key, '')) LIKE ? OR LOWER(COALESCE(command, '')) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ? OR LOWER(COALESCE(vendor, '')) LIKE ?)")
                fuzzy = f"%{q.strip().lower()}%"
                params.extend([fuzzy] * 6)
            if include_category and category and category.lower() != 'all':
                clauses.append("LOWER(COALESCE(category, '')) = ?")
                params.append(category.lower())
            if include_method and method and method.lower() != 'all':
                clauses.append("LOWER(COALESCE(method, '')) = ?")
                params.append(method.lower())
            if include_vendor and vendor and vendor.lower() != 'all':
                clauses.append("LOWER(COALESCE(vendor, '')) LIKE ?")
                params.append(f"%{vendor.lower()}%")
            return clauses, params

        clauses, params = _filter_parts(include_category=True, include_method=True)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        if page is None:
            rows = conn.execute(f'SELECT * FROM inspection_items{where} ORDER BY category ASC, name ASC', tuple(params)).fetchall()
            return [dict(r) for r in rows]
        count_row = conn.execute(f'SELECT COUNT(*) AS total FROM inspection_items{where}', tuple(params)).fetchone()
        total = int(count_row['total'] or 0) if count_row else 0

        # Facets must be computed from the filtered catalog, not from the
        # current page.  The UI shows category/method counts next to tabs, so
        # applying pagination to these aggregates makes a category appear as
        # zero until the user clicks it and loads that page.
        category_clauses, category_params = _filter_parts(include_category=False, include_method=True)
        category_where = f" WHERE {' AND '.join(category_clauses)}" if category_clauses else ''
        category_rows = conn.execute(
            f"SELECT COALESCE(category, '') AS facet_value, COUNT(*) AS total "
            f"FROM inspection_items{category_where} GROUP BY category",
            tuple(category_params),
        ).fetchall()
        category_counts = {
            str(row['facet_value'] or ''): int(row['total'] or 0)
            for row in category_rows
        }

        method_clauses, method_params = _filter_parts(include_category=True, include_method=False)
        method_where = f" WHERE {' AND '.join(method_clauses)}" if method_clauses else ''
        method_rows = conn.execute(
            f"SELECT COALESCE(method, '') AS facet_value, COUNT(*) AS total "
            f"FROM inspection_items{method_where} GROUP BY method",
            tuple(method_params),
        ).fetchall()
        method_counts = {
            str(row['facet_value'] or '').strip().upper(): int(row['total'] or 0)
            for row in method_rows
            if str(row['facet_value'] or '').strip()
        }

        # Vendor values are execution/filter keys (for example ``cisco_ios``),
        # so keep the exact stored spelling here.  The facet respects search,
        # category, and method filters, but ignores the currently selected
        # vendor so users can switch between vendors without losing options.
        vendor_clauses, vendor_params = _filter_parts(
            include_category=True,
            include_method=True,
            include_vendor=False,
        )
        vendor_where = f" WHERE {' AND '.join(vendor_clauses)}" if vendor_clauses else ''
        vendor_rows = conn.execute(
            f"SELECT COALESCE(vendor, '') AS facet_value, COUNT(*) AS total "
            f"FROM inspection_items{vendor_where} GROUP BY vendor",
            tuple(vendor_params),
        ).fetchall()
        vendor_counts = {
            str(row['facet_value'] or '').strip(): int(row['total'] or 0)
            for row in vendor_rows
            if str(row['facet_value'] or '').strip()
        }

        safe_page_size = min(max(int(page_size or 20), 1), 100)
        offset = (max(int(page or 1), 1) - 1) * safe_page_size
        rows = conn.execute(
            f'SELECT * FROM inspection_items{where} ORDER BY category ASC, name ASC LIMIT ? OFFSET ?',
            tuple(params + [safe_page_size, offset]),
        ).fetchall()
        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': max(int(page or 1), 1),
            'page_size': safe_page_size,
            'total_pages': max(1, (total + safe_page_size - 1) // safe_page_size),
            'facets': {
                'all': sum(category_counts.values()),
                'categories': category_counts,
                'methods': method_counts,
                'vendors': vendor_counts,
            },
        }
    finally:
        conn.close()

def create_inspection_item(item_data: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        item_id = str(uuid.uuid4())
        now = _beijing_now_iso()
        use_admin = 1 if item_data.get('use_admin_creds') else 0
        conn.execute(
            '''INSERT INTO inspection_items
                (id, name, name_zh, category, check_key, description, method, command,
                 script_id, warning_threshold, critical_threshold, parse_type, expected_value,
                 unit, threshold_direction, vendor, oid, use_admin_creds, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (item_id, item_data['name'], item_data['name_zh'], item_data['category'],
             item_data['check_key'], item_data.get('description', ''), 
             item_data.get('method', 'SNMP'), item_data.get('command', ''),
             item_data.get('script_id', ''), item_data.get('warning_threshold'),
             item_data.get('critical_threshold'), item_data.get('parse_type', 'numeric'),
             item_data.get('expected_value', ''),
             item_data.get('unit', ''),
             item_data.get('threshold_direction', 'above'),
             item_data.get('vendor', ''), item_data.get('oid', ''), use_admin, now, now)
        )
        conn.commit()
        item_data['id'] = item_id
        item_data['created_at'] = now
        item_data['updated_at'] = now
        item_data['use_admin_creds'] = bool(use_admin)
        item_data.setdefault('script_id', '')
        item_data.setdefault('warning_threshold', None)
        item_data.setdefault('critical_threshold', None)
        item_data.setdefault('parse_type', 'numeric')
        item_data.setdefault('expected_value', '')
        item_data.setdefault('unit', '')
        item_data.setdefault('threshold_direction', 'above')
        return item_data
    finally:
        conn.close()

def update_inspection_item(item_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        allowed = {
            'name', 'name_zh', 'category', 'check_key', 'description', 'method', 'command',
            'script_id', 'warning_threshold', 'critical_threshold', 'parse_type',
            'expected_value', 'unit', 'threshold_direction', 'vendor', 'oid', 'use_admin_creds',
        }
        sets = []
        params = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(int(bool(v)) if k == 'use_admin_creds' else v)
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
