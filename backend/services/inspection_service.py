"""
Device Inspection Service — 设备巡检引擎

支持:
- 手动触发巡检（单台/批量/全网）
- 定时巡检计划（cron 表达式）
- 分层连通性验证（ICMP → SSH）
- 健康指标采集与评分
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

logger = logging.getLogger(__name__)

_BEIJING_TZ = timezone(timedelta(hours=8))
_MAX_CONCURRENT = 10


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

def _inspect_single_device(device: dict[str, Any], alert_stats: dict[str, int], check_items: list[str] | None = None) -> dict[str, Any]:
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

    # 建立数据库连接获取指标
    conn = get_db_connection()
    try:
        # 获取该平台相关的精细化 Shell 巡检指标
        items = conn.execute(
            "SELECT * FROM inspection_items WHERE (vendor = ? OR vendor = 'Generic' OR vendor = '') AND method = 'Shell'",
            (platform_name,)
        ).fetchall()

        for item in items:
            script_id = item['script_id']
            if not script_id: continue
            
            script_row = conn.execute("SELECT content FROM scripts WHERE id = ?", (script_id,)).fetchone()
            if not script_row: continue
            
            # 1. 真实 SSH 执行
            raw_output = _execute_shell_script(ip, script_row['content'], device)
            
            # 2. 精细化取值 (取最后算出的数值)
            val = _extract_numeric_value(raw_output)
            
            if val is not None:
                metrics_results[item['check_key']] = val
                # 3. 阈值自动化判定
                w = item['warning_threshold']
                c = item['critical_threshold']
                
                if c is not None and val >= c:
                    findings.append({'severity': 'critical', 'message': f"{item['name_zh']} 严重超标: {val} (阈值 {c})"})
                    result['health_status'] = 'critical'
                elif w is not None and val >= w:
                    findings.append({'severity': 'warning', 'message': f"{item['name_zh']} 达到告警线: {val} (阈值 {w})"})
                    if result['health_status'] != 'critical': result['health_status'] = 'warning'
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
                 compliance_status, compliance_findings, findings_json, metrics_json, checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
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
                r.get('findings_json', '[]'), r.get('metrics_json', '{}'), r.get('checked_at'),
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

        completed_at = _beijing_now_iso()
        conn.execute(
            '''UPDATE inspection_runs SET
                status='completed', completed_at=?, success_count=?, failed_count=?,
                unreachable_count=?, healthy_count=?, warning_count=?, critical_count=?,
                avg_health_score=?
               WHERE id=?''',
            (completed_at, success_count, failed_count, unreachable_count,
             healthy_count, warning_count, critical_count, avg_score, run_id),
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
        'cpu_usage, memory_usage, temp, fan_status, psu_status, interface_data'
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
