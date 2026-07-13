import uuid
import json
import asyncio
import logging
import time
import re
from datetime import datetime
from database import get_db_connection
from services.automation_service import AutomationService
from services.notification_service import dispatch_to_all_users
from core.crypto import decrypt_credential
from services.vault_service import resolve_device_credentials
# Import inspection service to handle specialized inspection jobs
from services.inspection_service import run_inspection

logger = logging.getLogger(__name__)

async def run_scheduled_automation_job(job_id: str):
    """
    核心执行逻辑：
    1. 获取作业定义
    2. 解析目标设备
    3. 获取脚本内容
    4. 批量执行
    5. 记录执行历史 (SURFACE IN EXECUTION HISTORY TAB)
    6. 更新状态 & 发送告警
    """
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row or not row['enabled']:
            return
        job = dict(row)

        # 1. 确定设备范围
        device_ids = []
        if job['device_scope'] == 'all':
            rows = conn.execute("SELECT id FROM devices").fetchall()
            device_ids = [r['id'] for r in rows]
        elif job['device_scope'] == 'tags':
            tag_id = job['device_filter']
            rows = conn.execute("SELECT device_id FROM device_tags WHERE tag_id = ?", (tag_id,)).fetchall()
            device_ids = [r['device_id'] for r in rows]
        elif job['device_scope'] == 'ip':
            # Support targeting by IP address directly
            target_ips = [i.strip() for i in (job['device_filter'] or '').split(',') if i.strip()]
            if target_ips:
                placeholders = ','.join(['?'] * len(target_ips))
                rows = conn.execute(f"SELECT id FROM devices WHERE ip_address IN ({placeholders})", target_ips).fetchall()
                device_ids = [r['id'] for r in rows]
        else: # ids
            device_ids = [i.strip() for i in (job['device_filter'] or '').split(',') if i.strip()]

        if not device_ids:
            logger.warning(f"Job {job_id} has no target devices.")
            return

        # ── SPECIAL HANDLING FOR INSPECTION JOBS ──
        # If the job is marked as an inspection, we divert it to the specialized
        # inspection engine. This ensures we get smart analysis, health scoring,
        # and Excel report support, which the generic command runner lacks.
        if job['action_type'] == 'inspection':
            logger.info(f"Diverting scheduled job {job_id} ({job['name']}) to inspection engine.")
            
            # Parse check items from commands field (comma-separated or newline-separated) or script.
            #
            # IMPORTANT: a shell *collector* script (e.g. the built-in 'insp_linux_full'
            # comprehensive inspection) must NOT be split line-by-line into check_items —
            # doing so produces hundreds of bogus "items" that filter out every real
            # inspection metric, leaving the run with empty metrics. We only derive
            # check_items from a plain comma/newline list in the `commands` field.
            # When a script_id is set we leave check_items=None so the inspection engine
            # runs its full metric set / comprehensive script for the device platform.
            custom_check_items = None
            if not job.get('script_id') and job['commands']:
                custom_check_items = [c.strip() for c in re.split(r'[,\n]', job['commands']) if c.strip()]
            
            # NOTE: schedule_id must be None here.
            # scheduled_jobs.id ≠ inspection_schedules.id — passing the job_id
            # would violate the FK constraint on inspection_runs.schedule_id.
            # We embed the job_id in created_by for traceability instead.
            loop = asyncio.get_event_loop()
            inspection_result = await loop.run_in_executor(
                None,
                lambda: run_inspection(
                    scope_type='devices',
                    scope_filter=','.join(device_ids),
                    trigger_type='scheduled',
                    schedule_id=None,
                    created_by=f'scheduler:{job_id}',
                    check_items=custom_check_items,
                    use_admin_creds=bool(job.get('use_admin_creds', 0))
                )
            )
            
            run_status = 'success' if inspection_result.get('success') else 'failed'
            conn.execute(
                "UPDATE scheduled_jobs SET last_run_at = ?, last_run_status = ?, run_count = run_count + 1 WHERE id = ?",
                (datetime.now().isoformat(), run_status, job_id)
            )
            conn.commit()
            return


        # 2. 获取命令或脚本内容
        commands_str = job['commands'] or ""
        script_name = "Scheduled Job"
        is_shell_script = False
        if job['script_id']:
            script = conn.execute("SELECT name, content, script_type FROM scripts WHERE id = ?", (job['script_id'],)).fetchone()
            if script:
                commands_str = script['content']
                script_name = script['name']
                # sqlite3.Row 不支持 .get(),需要直接索引;同时兼容旧记录中 script_type 为 NULL 的情况
                if script['script_type'] == 'shell':
                    is_shell_script = True
        
        if not is_shell_script and commands_str.strip().startswith('#!'):
            is_shell_script = True

        # NOTE: We do NOT pre-wrap shell scripts here.
        # The execution path branches per device based on asset_type:
        #   - Linux/server  → LinuxDriver (Paramiko exec_command, native script support)
        #   - Network device → NetmikoDriver (Netmiko send_command, needs base64 wrapping)
        # Wrapping is done per-device inside the loop below.
        if not is_shell_script:
            commands = [c.strip() for c in commands_str.split('\n') if c.strip()]
        else:
            commands = []  # shell scripts are executed via per-device path below
        
        # 3. 初始化执行历史记录 (Surface in Execution History)
        execution_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()
        
        conn.execute(
            '''INSERT INTO playbook_executions 
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (execution_id, f"scheduled:{job_id}", job['name'], 'mixed', 
             json.dumps(device_ids), '{}', 'running', 0,
             # Use 'scheduler' as author so the frontend can reliably identify
             # these records as scheduled-job executions (not manual runs).
             'scheduler',
             5, now_iso, now_iso)
        )
        conn.commit()

        # 4. 执行（并行，最多 10 并发）
        total_failed = 0
        total_success = 0
        failure_details = []
        results_lock = asyncio.Lock()

        service = AutomationService(driver_type='netmiko') # 默认 netmiko

        # 预加载所有设备信息，避免在并发任务中重复查询
        device_rows = conn.execute(
            f"SELECT * FROM devices WHERE id IN ({','.join('?' * len(device_ids))})",
            device_ids
        ).fetchall()
        device_map = {row['id']: dict(row) for row in device_rows}

        async def _execute_single_device(dev_id: str):
            nonlocal total_failed, total_success

            device = device_map.get(dev_id)
            if not device:
                async with results_lock:
                    total_failed += 1
                    failure_details.append(f"设备 {dev_id} 不存在")
                return

            d = dict(device)
            creds = resolve_device_credentials(d)
            if job.get('use_admin_creds', 0) == 1:
                d['username'] = creds.get('admin_username') or creds.get('username') or ''
                d['password'] = creds.get('admin_password') or creds.get('password') or ''
                d['enable_password'] = creds.get('enable_password') or ''
                logger.info(f"[Scheduler] Using admin/privileged credentials (User: '{d.get('username', 'unknown')}') for device {d.get('hostname', d.get('ip_address'))} (use_admin_creds=1)")
            else:
                d['username'] = creds.get('normal_username') or creds.get('username') or creds.get('admin_username') or ''
                d['password'] = creds.get('normal_password') or creds.get('password') or creds.get('admin_password') or ''
                d['enable_password'] = creds.get('enable_password') or ''
                logger.info(f"[Scheduler] Using normal credentials (User: '{d.get('username', 'unknown')}') for device {d.get('hostname', d.get('ip_address'))}")

            # 记录设备开始执行（使用独立连接，避免并发冲突）
            dev_started_at = datetime.now().isoformat()
            dev_result_id = str(uuid.uuid4())
            dev_conn = get_db_connection()
            try:
                dev_conn.execute(
                    '''INSERT INTO execution_device_results 
                       (id, execution_id, device_id, hostname, ip_address, status, started_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (dev_result_id, execution_id, dev_id, d['hostname'], d['ip_address'], 'running', dev_started_at)
                )
                dev_conn.commit()
            finally:
                dev_conn.close()

            try:
                loop = asyncio.get_event_loop()

                # ── Per-device execution path ────────────────────────────────
                platform = str(d.get('platform') or '').lower()
                category = str(d.get('device_category') or '').lower()
                is_server = any(t in platform for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or 'server' in category

                if is_shell_script and is_server:
                    # Linux/server: use LinuxDriver via SCRIPT mode.
                    d['asset_type'] = 'server'
                    exec_results_raw = await loop.run_in_executor(
                        None,
                        lambda: service.orchestrator.execute_single(d, 'script', commands_str)
                    )
                    logger.info(f"[Scheduler] Linux execution raw result for {d.get('hostname')}: success={exec_results_raw.get('success')}, err={exec_results_raw.get('stderr') or exec_results_raw.get('error')}")
                    exec_results = [{
                        'success': exec_results_raw.get('success', False),
                        'output': exec_results_raw.get('stdout', '') or exec_results_raw.get('output', ''),
                        'error': exec_results_raw.get('stderr', '') or exec_results_raw.get('error', ''),
                    }]

                elif is_shell_script and not is_server:
                    # Network device: must use base64 wrapping + sentinel markers
                    import base64 as _b64
                    tmp_file = f"/tmp/netops_{uuid.uuid4().hex}.sh"
                    res_file = f"{tmp_file}.log"
                    encoded_script = _b64.b64encode(commands_str.encode()).decode()
                    _sentinel_begin = "---NETOPS_BEGIN---"
                    _sentinel_end   = "---NETOPS_END---"
                    wrapped = (
                        f"echo '{encoded_script}' | base64 -d > {tmp_file}; "
                        f"printf '\\n{_sentinel_begin}\\n'; "
                        f"/bin/bash {tmp_file} > {res_file} 2>&1; "
                        f"sleep 1; cat {res_file}; "
                        f"printf '\\n{_sentinel_end}\\n'; "
                        f"rm -f {tmp_file} {res_file}"
                    )
                    exec_results = await loop.run_in_executor(
                        None,
                        lambda: service.execute_commands(d, [wrapped], is_config=False)
                    )

                else:
                    # Plain CLI commands (both Linux and network devices)
                    cmds_snapshot = list(commands)  # capture for lambda closure
                    exec_results = await loop.run_in_executor(
                        None,
                        lambda: service.execute_commands(d, cmds_snapshot, is_config=bool(job['is_config']))
                    )
                    log_summary = [(r.get('success'), r.get('stderr') or r.get('error') or '') for r in exec_results]
                    logger.info(f"[Scheduler] CLI execution raw result for {d.get('hostname')}: {log_summary}")

                # ── Normalise output ─────────────────────────────────────────
                def _get_output(r: dict) -> str:
                    out_val = r.get('output') or r.get('stdout') or ''
                    err_val = r.get('error') or r.get('stderr') or ''
                    if not out_val and err_val:
                        return f"ERROR: {err_val}"
                    return out_val

                success = all(r.get('success', False) for r in exec_results)

                processed_commands = []
                business_anomaly = False
                anomaly_msg = ""
                _sentinel_begin = "---NETOPS_BEGIN---"
                _sentinel_end   = "---NETOPS_END---"

                cmd_iter = iter(cmds_snapshot) if not is_shell_script else None
                for r in exec_results:
                    out = str(_get_output(r))
                    if is_shell_script and not is_server:
                        if _sentinel_begin in out and _sentinel_end in out:
                            out = out.split(_sentinel_begin)[-1].split(_sentinel_end)[0].strip()
                        elif _sentinel_begin in out:
                            out = out.split(_sentinel_begin)[-1].strip() + "\n[Warning: Execution might be incomplete]"

                    cmd_label = next(cmd_iter, None) if cmd_iter else None
                    if cmd_label:
                        if job.get('is_config'):
                            cmd_str = " | ".join(cmds_snapshot)
                            processed_commands.append(f"# {cmd_str}\n{out}")
                        else:
                            processed_commands.append(f"# {cmd_label}\n{out}")
                    else:
                        processed_commands.append(out)

                    lines = out.split('\n')
                    found_crit = False
                    for line in lines:
                        if "CRITICAL" in line or "ERROR" in line:
                            business_anomaly = True
                            found_crit = True
                            clean_line = " ".join(line.split())
                            anomaly_msg = f"检测到严重异常: {clean_line}"
                            break

                    if not found_crit:
                        for line in lines:
                            if "WARNING" in line:
                                clean_line = " ".join(line.split())
                                anomaly_msg = f"检测到警告: {clean_line}"
                                break

                if success and not business_anomaly:
                    phase_status = "success"
                    async with results_lock:
                        total_success += 1
                else:
                    phase_status = "failed"
                    async with results_lock:
                        total_failed += 1
                        if success and business_anomaly:
                            failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 业务异常: {anomaly_msg}")
                        elif not success:
                            failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 执行失败")

                combined_output = '\n'.join(processed_commands).strip()
                display_commands = [script_name] if is_shell_script else (commands or [])
                phase_data = {
                    "execute": {
                        "status": phase_status,
                        "commands": display_commands,
                        "output": combined_output
                    }
                }

                dev_completed_at = datetime.now().isoformat()
                upd_conn = get_db_connection()
                try:
                    upd_conn.execute(
                        '''UPDATE execution_device_results 
                           SET status = ?, error_message = ?, phases_json = ?, completed_at = ?
                           WHERE id = ?''',
                        (phase_status,
                         anomaly_msg if business_anomaly else ("" if success else "Command failure"),
                         json.dumps(phase_data), dev_completed_at, dev_result_id)
                    )
                    upd_conn.commit()
                finally:
                    upd_conn.close()

            except Exception as e:
                async with results_lock:
                    total_failed += 1
                    failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 异常: {str(e)}")

                dev_completed_at = datetime.now().isoformat()
                err_conn = get_db_connection()
                try:
                    err_conn.execute(
                        '''UPDATE execution_device_results 
                           SET status = ?, error_message = ?, completed_at = ?
                           WHERE id = ?''',
                        ("failed", str(e), dev_completed_at, dev_result_id)
                    )
                    err_conn.commit()
                finally:
                    err_conn.close()

        # 并发执行，最多 10 个设备同时运行
        _CONCURRENCY = 10
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async def _throttled(dev_id: str):
            async with semaphore:
                await _execute_single_device(dev_id)

        await asyncio.gather(*[_throttled(did) for did in device_ids])

        # 5. 更新总执行记录状态
        final_playbook_status = "success" if total_failed == 0 else ("failed" if total_success == 0 else "partial")
        conn.execute(
            '''UPDATE playbook_executions 
               SET status = ?, total_devices = ?, success_count = ?, failed_count = ?, updated_at = ?
               WHERE id = ?''',
            (final_playbook_status, len(device_ids), total_success, total_failed, datetime.now().isoformat(), execution_id)
        )

        # 6. 更新作业定义中的最后运行状态
        conn.execute(
            "UPDATE scheduled_jobs SET last_run_at = ?, last_run_status = ?, run_count = run_count + 1 WHERE id = ?",
            (datetime.now().isoformat(), final_playbook_status, job_id)
        )
        conn.commit()

        # 7. 如果失败，触发告警
        if total_failed > 0:
            await notify_job_failure(job, failure_details)

    except Exception as e:
        logger.exception(f"Scheduled job {job_id} failed with exception")
    finally:
        conn.close()

async def notify_job_failure(job, details):
    # 获取活跃用户的通知偏好并分发
    from services.notification_service import dispatch_to_all_users
    
    # 1. 优化告警标题：突出任务名称
    alert_title = f"🔴 NetOps 异常告警: {job['name']}"
    
    # 2. 固定判定级别为 Major (主要告警)，避免过度干扰
    severity = "major"
        
    # 3. 构建结构化正文
    msg_body = (
        f"任务名称: {job['name']}\n"
        f"执行方式: 定时任务\n"
        f"异常设备数: {len(details)}\n"
        f"----------------------------\n"
        f"详细异常详情:\n" + "\n".join(details[:10])
    )
    
    alert = {
        "title": alert_title,
        "object_name": job['name'],
        "ip_address": "N/A",
        "status": "active",
        "severity": severity,
        "message": msg_body,
        "first_occurrence": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "last_occurrence": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    # 调用通知服务 (同步调用，调用方通常已经在子线程或独立进程中)
    dispatch_to_all_users(alert)

def sync_scheduler_jobs(scheduler):
    """
    将数据库中的所有启用任务同步到 APScheduler。
    """
    from apscheduler.triggers.cron import CronTrigger
    
    # 清理旧的动态任务 (以 'dyn_' 开头)
    for s_job in scheduler.get_jobs():
        if s_job.id.startswith('dyn_'):
            scheduler.remove_job(s_job.id)

    conn = get_db_connection()
    try:
        jobs = conn.execute("SELECT * FROM scheduled_jobs WHERE enabled = 1").fetchall()
        for job in jobs:
            job_id = job['id']
            # APScheduler 运行协程需要特殊的包装
            if job['job_type'] == 'cron' and job['cron_expr']:
                try:
                    scheduler.add_job(
                        run_scheduled_automation_job_sync_wrapper,
                        CronTrigger.from_crontab(job['cron_expr']),
                        id=f"dyn_{job_id}",
                        args=[job_id],
                        replace_existing=True,
                        # 允许至多 2 个实例并发，并合并被错过的触发，避免单次巡检
                        # 偶尔超时导致后续触发被 "maximum instances reached" 跳过。
                        max_instances=2,
                        coalesce=True,
                        misfire_grace_time=300,
                    )
                    logger.info(f"Scheduled cron job: {job['name']} ({job['cron_expr']})")
                except Exception as e:
                    logger.error(f"Failed to schedule job {job['name']}: {e}")
            elif job['job_type'] == 'once' and job['scheduled_at']:
                try:
                    run_dt = datetime.fromisoformat(job['scheduled_at'])
                    if run_dt > datetime.now():
                        scheduler.add_job(
                            run_scheduled_automation_job_sync_wrapper,
                            'date',
                            run_date=run_dt,
                            id=f"dyn_{job_id}",
                            args=[job_id],
                            replace_existing=True
                        )
                        logger.info(f"Scheduled one-time job: {job['name']} at {job['scheduled_at']}")
                except Exception as e:
                    logger.error(f"Failed to schedule one-time job {job['name']}: {e}")
    finally:
        conn.close()

def run_scheduled_automation_job_sync_wrapper(job_id: str):
    """同步包装器，用于 APScheduler 调用协程"""
    from core.scheduler_lock import acquire_scheduler_lock
    if not acquire_scheduler_lock(f"dyn_{job_id}", expire_seconds=300):
        logger.debug(f"Dynamic job {job_id} lock is already held. Skipping.")
        return
    import asyncio
    try:
        # 获取当前运行的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_scheduled_automation_job(job_id))
        loop.close()
    except Exception as e:
        logger.error(f"Error in scheduled job wrapper for {job_id}: {e}")

# ──────────────────────────────────────────────────────────────────────
# System Platform-managed periodic jobs (Interface, Topology & Endpoints)
# ──────────────────────────────────────────────────────────────────────

def _beijing_now_iso() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def parse_cisco_interfaces(output: str) -> list[dict]:
    try:
        from ntc_templates.parse import parse_output
        res = parse_output(platform='cisco_ios', command='show interfaces', data=output)
        if isinstance(res, list):
            return res
    except Exception as e:
        logger.debug("NTC templates show interfaces parse failed: %s", e)
    return []

def parse_cisco_interfaces_status(output: str) -> list[dict]:
    try:
        from ntc_templates.parse import parse_output
        res = parse_output(platform='cisco_ios', command='show interfaces status', data=output)
        if isinstance(res, list):
            return res
    except Exception as e:
        logger.debug("NTC templates show interfaces status parse failed: %s", e)
    return []

def parse_huawei_interfaces(output: str) -> list[dict]:
    try:
        from ntc_templates.parse import parse_output
        res = parse_output(platform='huawei_vrp', command='display interface', data=output)
        if isinstance(res, list):
            return res
    except Exception as e:
        logger.debug("NTC templates display interface parse failed: %s", e)
    return []

def parse_cisco_interfaces_regex(output: str) -> list[dict]:
    interfaces = []
    blocks = re.split(r'\n(?=[a-zA-Z0-9\/\.\-\:]+\s+is\s+)', output)
    for block in blocks:
        if not block.strip():
            continue
        first_line = block.splitlines()[0]
        match = re.match(r'^([a-zA-Z0-9\/\.\-\:]+)\s+is\s+([^,]+),\s+line\s+protocol\s+is\s+(\S+)', first_line, re.IGNORECASE)
        if not match:
            continue
        name, admin_state, oper_state = match.groups()
        admin_status = 'up' if 'up' in admin_state.lower() else 'down'
        oper_status = 'up' if 'up' in oper_state.lower() else 'down'
        
        desc_match = re.search(r'Description:\s*(.+)$', block, re.MULTILINE | re.IGNORECASE)
        desc = desc_match.group(1).strip() if desc_match else ''
        
        mac_match = re.search(r'address\s+is\s+([0-9a-fA-F\.\-]{14})', block, re.IGNORECASE)
        mac = mac_match.group(1).replace('.', '').replace('-', '').lower() if mac_match else ''
        
        mtu_match = re.search(r'MTU\s+(\d+)\s+bytes', block, re.IGNORECASE)
        mtu = int(mtu_match.group(1)) if mtu_match else 1500
        
        bw_match = re.search(r'BW\s+(\d+)\s+Kbit', block, re.IGNORECASE)
        speed = float(bw_match.group(1)) * 1000.0 if bw_match else 0.0
        
        duplex = 'auto'
        if 'full-duplex' in block.lower():
            duplex = 'full'
        elif 'half-duplex' in block.lower():
            duplex = 'half'
            
        interfaces.append({
            'interface': name,
            'link_status': admin_status,
            'protocol_status': oper_status,
            'description': desc,
            'address': mac,
            'mtu': mtu,
            'bandwidth': speed,
            'duplex': duplex
        })
    return interfaces

def parse_cisco_interfaces_status_regex(output: str) -> list[dict]:
    entries = []
    for line in output.splitlines():
        line = line.strip()
        if not line or any(k in line.lower() for k in ('port', 'name', 'status', 'vlan', 'duplex', 'speed', 'type', '---')):
            continue
        parts = line.split()
        if len(parts) >= 4:
            port = parts[0]
            vlan = None
            for p in parts[1:]:
                p_lower = p.lower()
                if p_lower in ('trunk', 'routed') or (p.isdigit() and 0 < int(p) < 4096):
                    vlan = p
                    break
            if vlan:
                entries.append({
                    'port': port,
                    'vlan': vlan
                })
    return entries

def parse_huawei_interfaces_regex(output: str) -> list[dict]:
    interfaces = []
    blocks = re.split(r'\n(?=[a-zA-Z0-9\/\.\-\:]+\s+current\s+state\s*:)', output)
    for block in blocks:
        if not block.strip():
            continue
        first_line = block.splitlines()[0]
        match = re.match(r'^([a-zA-Z0-9\/\.\-\:]+)\s+current\s+state\s*:\s*(\S+)', first_line, re.IGNORECASE)
        if not match:
            continue
        name, state = match.groups()
        admin_status = 'up' if 'up' in state.lower() else 'down'
        
        proto_match = re.search(r'Line\s+protocol\s+current\s+state\s*:\s*(\S+)', block, re.IGNORECASE)
        oper_status = 'up' if proto_match and 'up' in proto_match.group(1).lower() else 'down'
        
        desc_match = re.search(r'Description:\s*(.+)$', block, re.MULTILINE | re.IGNORECASE)
        desc = desc_match.group(1).strip() if desc_match else ''
        
        mac_match = re.search(r'Hardware\s+address\s+is\s+([0-9a-fA-F\.\-]{14})', block, re.IGNORECASE)
        mac = mac_match.group(1).replace('.', '').replace('-', '').lower() if mac_match else ''
        
        mtu_match = re.search(r'The\s+Maximum\s+Frame\s+Length\s+is\s+(\d+)|MTU\s+(\d+)', block, re.IGNORECASE)
        mtu = 1500
        if mtu_match:
            mtu = int(mtu_match.group(1) or mtu_match.group(2))
            
        speed = 0.0
        speed_match = re.search(r'Speed\s*:\s*(\d+)\s*(Mb/s|Gb/s|Mbps|Gbps)', block, re.IGNORECASE)
        if speed_match:
            val = float(speed_match.group(1))
            unit = speed_match.group(2).lower()
            if 'g' in unit:
                speed = val * 1e9
            else:
                speed = val * 1e6
                
        duplex = 'auto'
        if 'full' in block.lower():
            duplex = 'full'
        elif 'half' in block.lower():
            duplex = 'half'
            
        interfaces.append({
            'interface': name,
            'link_status': admin_status,
            'protocol_status': oper_status,
            'description': desc,
            'address': mac,
            'mtu': mtu,
            'bandwidth': speed,
            'duplex': duplex
        })
    return interfaces

def parse_arp_table_regex(output: str) -> list[dict]:
    entries = []
    ip_mac_re = re.compile(
        r'\b(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b'
        r'\s+(?:-\s+)?'
        r'\b(?P<mac>[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}|[0-9a-fA-F]{12})\b',
        re.IGNORECASE
    )
    for line in output.splitlines():
        m = ip_mac_re.search(line)
        if m:
            ip = m.group('ip')
            mac = m.group('mac').replace('.', '').replace('-', '').lower()
            if ip in ('0.0.0.0', '255.255.255.255') or ip.startswith('169.254.'):
                continue
            parts = line.split()
            intf = ''
            vlan = None
            for p in parts:
                p_lower = p.lower()
                if any(k in p_lower for k in ('ethernet', 'ge', 'xge', 'vl', 'vlanif', 'gi', 'fa', 'eth', 'lo')):
                    intf = p
                elif p.isdigit() and 0 < int(p) < 4096:
                    vlan = int(p)
            entries.append({
                'ip': ip,
                'mac': mac,
                'interface': intf,
                'vlan': vlan
            })
    return entries

def parse_mac_table_regex(output: str) -> list[dict]:
    entries = []
    mac_re = re.compile(
        r'\b(?P<mac>[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}-[0-9a-fA-F]{2}|[0-9a-fA-F]{12})\b',
        re.IGNORECASE
    )
    for line in output.splitlines():
        m = mac_re.search(line)
        if m:
            mac = m.group('mac').replace('.', '').replace('-', '').lower()
            parts = line.split()
            intf = ''
            vlan = None
            entry_type = 'dynamic'
            
            for p in parts:
                if 'static' in p.lower():
                    entry_type = 'static'
                elif 'dynamic' in p.lower():
                    entry_type = 'dynamic'
                    
            for p in parts:
                p_lower = p.lower()
                if any(k in p_lower for k in ('ethernet', 'ge', 'xge', 'gi', 'fa', 'eth', 'po', 'port-channel', 'trunk')):
                    intf = p
                elif p.isdigit() and 0 < int(p) < 4096:
                    vlan = int(p)
                    
            if intf:
                entries.append({
                    'mac': mac,
                    'interface': intf,
                    'vlan': vlan or 1,
                    'type': entry_type
                })
    return entries

def sync_topology_and_interfaces_job():
    """System periodic task: Collect interfaces and topology LLDP/CDP neighbors."""
    logger.info("[Scheduler Job] Starting sync_topology_and_interfaces_job...")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM devices WHERE status = 'online'").fetchall()
        devices = [dict(row) for row in rows]
    finally:
        conn.close()

    if not devices:
        logger.info("[Scheduler Job] No online devices found for interface and topology sync.")
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.topology_service import normalize_interface_name, PLATFORM_MAP
    from netmiko import ConnectHandler
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs
    
    def collect_device_interfaces(device: dict) -> list[dict]:
        ip = device.get('ip_address')
        port = int(device.get('management_port') or device.get('port') or 22)
        from drivers.ssh_compat import is_ssh_port_open
        if not is_ssh_port_open(ip, port):
            logger.warning("Failed to collect interfaces for device %s: SSH port %s is closed/unreachable", device.get('hostname'), port)
            return []

        dev_id = device['id']
        from core.platform_utils import normalize_device_platform
        platform = normalize_device_platform(device.get('vendor'), device.get('platform'))
        creds = resolve_device_credentials(device)
        username = creds.get('normal_username') or creds.get('username') or ''
        password = creds.get('normal_password') or creds.get('password') or ''
        enable_pw = creds.get('enable_password') or ''
        
        netmiko_device = {
            'device_type': PLATFORM_MAP.get(platform, 'cisco_ios'),
            'host': ip,
            'username': username,
            'password': password,
            'port': int(device.get('management_port') or device.get('port') or 22),
            'fast_cli': True,
        }
        netmiko_device.update(build_netmiko_compatibility_kwargs())
        if enable_pw:
            netmiko_device['secret'] = enable_pw

        commands = []
        if 'cisco' in platform:
            commands = ['show interfaces', 'show interfaces status']
        elif 'huawei' in platform or 'h3c' in platform:
            commands = ['display interface']
        else:
            commands = ['show interfaces']

        try:
            with ConnectHandler(**netmiko_device) as client:
                if enable_pw:
                    try:
                        client.enable()
                    except Exception:
                        pass
                
                outputs = {}
                for cmd in commands:
                    output = client.send_command(cmd, use_textfsm=False)
                    outputs[cmd] = output
                
                parsed_interfaces = []
                if 'cisco' in platform:
                    show_int_output = outputs.get('show interfaces', '')
                    parsed_show_int = parse_cisco_interfaces(show_int_output)
                    if not parsed_show_int:
                        parsed_show_int = parse_cisco_interfaces_regex(show_int_output)
                        
                    show_status_output = outputs.get('show interfaces status', '')
                    parsed_show_status = parse_cisco_interfaces_status(show_status_output)
                    if not parsed_show_status:
                        parsed_show_status = parse_cisco_interfaces_status_regex(show_status_output)
                        
                    status_by_name = {normalize_interface_name(x.get('port')).lower(): x for x in parsed_show_status}
                    for item in parsed_show_int:
                        iname = item.get('interface')
                        norm_iname = normalize_interface_name(iname).lower()
                        status_item = status_by_name.get(norm_iname, {})
                        
                        vlan_val = status_item.get('vlan')
                        mode = 'access'
                        access_vlan = None
                        if vlan_val:
                            if 'trunk' in str(vlan_val).lower():
                                mode = 'trunk'
                            elif str(vlan_val).isdigit():
                                mode = 'access'
                                access_vlan = int(vlan_val)
                                
                        parsed_interfaces.append({
                            'device_id': dev_id,
                            'name': iname,
                            'description': item.get('description', ''),
                            'admin_status': item.get('link_status', 'down'),
                            'oper_status': item.get('protocol_status', 'down'),
                            'mac_address': item.get('address', ''),
                            'mtu': item.get('mtu', 1500),
                            'speed': item.get('bandwidth', 0.0),
                            'bandwidth': item.get('bandwidth', 0.0),
                            'duplex': item.get('duplex', 'auto'),
                            'switchport_mode': mode,
                            'access_vlan': access_vlan,
                        })
                elif 'huawei' in platform or 'h3c' in platform:
                    disp_int_output = outputs.get('display interface', '')
                    parsed_disp_int = parse_huawei_interfaces(disp_int_output)
                    if not parsed_disp_int:
                        parsed_disp_int = parse_huawei_interfaces_regex(disp_int_output)
                        
                    for item in parsed_disp_int:
                        parsed_interfaces.append({
                            'device_id': dev_id,
                            'name': item.get('interface'),
                            'description': item.get('description', ''),
                            'admin_status': item.get('link_status', 'down'),
                            'oper_status': item.get('protocol_status', 'down'),
                            'mac_address': item.get('address', ''),
                            'mtu': item.get('mtu', 1500),
                            'speed': item.get('bandwidth', 0.0),
                            'bandwidth': item.get('bandwidth', 0.0),
                            'duplex': item.get('duplex', 'auto'),
                            'switchport_mode': 'access',
                            'access_vlan': None,
                        })
                else:
                    show_int_output = outputs.get(commands[0], '')
                    parsed_show_int = parse_cisco_interfaces_regex(show_int_output)
                    for item in parsed_show_int:
                        parsed_interfaces.append({
                            'device_id': dev_id,
                            'name': item.get('interface'),
                            'description': item.get('description', ''),
                            'admin_status': item.get('link_status', 'down'),
                            'oper_status': item.get('protocol_status', 'down'),
                            'mac_address': item.get('address', ''),
                            'mtu': item.get('mtu', 1500),
                            'speed': item.get('bandwidth', 0.0),
                            'bandwidth': item.get('bandwidth', 0.0),
                            'duplex': item.get('duplex', 'auto'),
                            'switchport_mode': 'access',
                            'access_vlan': None,
                        })
                return parsed_interfaces
        except Exception as e:
            logger.error("Failed to collect interfaces for device %s: %s", device.get('hostname'), e)
            return []

    # Collect interfaces in parallel
    all_interfaces = []
    workers = min(5, len(devices))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(collect_device_interfaces, dev) for dev in devices]
        for f in as_completed(futures):
            all_interfaces.extend(f.result())

    # Write to database sequentially
    if all_interfaces:
        db_conn = get_db_connection()
        try:
            for iface in all_interfaces:
                db_conn.execute('''
                    INSERT INTO interfaces (
                        id, device_id, interface_name, description, admin_status, oper_status,
                        mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, access_vlan
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'physical', ?, ?)
                    ON CONFLICT(device_id, interface_name) DO UPDATE SET
                        description = excluded.description,
                        admin_status = excluded.admin_status,
                        oper_status = excluded.oper_status,
                        mac_address = excluded.mac_address,
                        speed = excluded.speed,
                        bandwidth = excluded.bandwidth,
                        duplex = excluded.duplex,
                        switchport_mode = excluded.switchport_mode,
                        access_vlan = excluded.access_vlan
                ''', (
                    f"intf-{uuid.uuid4().hex[:12]}", iface['device_id'], iface['name'], iface['description'],
                    iface['admin_status'], iface['oper_status'], iface['mac_address'],
                    iface['speed'], iface['bandwidth'], iface['duplex'],
                    iface['switchport_mode'], iface['access_vlan']
                ))
            db_conn.commit()
            logger.info("Successfully updated %d interfaces in DB.", len(all_interfaces))
        except Exception as db_err:
            logger.error("Failed to write interfaces to DB: %s", db_err)
        finally:
            db_conn.close()

    # Collect topology neighbors
    from services.topology_service import discover_lldp_neighbors
    async def run_discovery():
        tasks = [discover_lldp_neighbors(dev['id']) for dev in devices]
        await asyncio.gather(*tasks, return_exceptions=True)
        
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run_discovery())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_discovery())
        loop.close()
    
    logger.info("[Scheduler Job] sync_topology_and_interfaces_job completed.")

def poll_endpoints_job():
    """System periodic task: Collect ARP and MAC tables, then run localization."""
    logger.info("[Scheduler Job] Starting poll_endpoints_job...")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM devices WHERE status = 'online'").fetchall()
        devices = [dict(row) for row in rows]
    finally:
        conn.close()
        
    if not devices:
        logger.info("[Scheduler Job] No online devices found for endpoint polling.")
        return

    l3_roles = {'router', 'gateway', 'core', 'dist', 'aggregation', 'l3switch'}
    l3_devices = [d for d in devices if (d.get('role') or '').lower().strip() in l3_roles]
    
    mac_excluded_roles = {'router', 'firewall', 'gateway', 'server', 'linux', 'windows'}
    l2_devices = [d for d in devices if (d.get('role') or '').lower().strip() not in mac_excluded_roles]

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.topology_service import PLATFORM_MAP
    from netmiko import ConnectHandler
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs
    
    def collect_device_arp(device: dict) -> list[dict]:
        ip = device.get('ip_address')
        port = int(device.get('management_port') or device.get('port') or 22)
        from drivers.ssh_compat import is_ssh_port_open
        if not is_ssh_port_open(ip, port):
            logger.warning("Failed to collect ARP for device %s: SSH port %s is closed/unreachable", device.get('hostname'), port)
            return []

        dev_id = device['id']
        from core.platform_utils import normalize_device_platform
        platform = normalize_device_platform(device.get('vendor'), device.get('platform'))
        creds = resolve_device_credentials(device)
        username = creds.get('normal_username') or creds.get('username') or ''
        password = creds.get('normal_password') or creds.get('password') or ''
        enable_pw = creds.get('enable_password') or ''
        
        netmiko_device = {
            'device_type': PLATFORM_MAP.get(platform, 'cisco_ios'),
            'host': ip,
            'username': username,
            'password': password,
            'port': int(device.get('management_port') or device.get('port') or 22),
            'fast_cli': True,
        }
        netmiko_device.update(build_netmiko_compatibility_kwargs())
        if enable_pw:
            netmiko_device['secret'] = enable_pw
            
        cmd = 'display arp all' if 'huawei' in platform or 'h3c' in platform else 'show ip arp'
        try:
            with ConnectHandler(**netmiko_device) as client:
                if enable_pw:
                    try:
                        client.enable()
                    except Exception:
                        pass
                output = client.send_command(cmd, use_textfsm=False)
                parsed_arp = parse_arp_table_regex(output)
                for item in parsed_arp:
                    item['device_id'] = dev_id
                return parsed_arp
        except Exception as e:
            logger.error("Failed to collect ARP for device %s: %s", device.get('hostname'), e)
            return []

    def collect_device_mac(device: dict) -> list[dict]:
        ip = device.get('ip_address')
        port = int(device.get('management_port') or device.get('port') or 22)
        from drivers.ssh_compat import is_ssh_port_open
        if not is_ssh_port_open(ip, port):
            logger.warning("Failed to collect MAC for device %s: SSH port %s is closed/unreachable", device.get('hostname'), port)
            return []

        dev_id = device['id']
        from core.platform_utils import normalize_device_platform
        platform = normalize_device_platform(device.get('vendor'), device.get('platform'))
        creds = resolve_device_credentials(device)
        username = creds.get('normal_username') or creds.get('username') or ''
        password = creds.get('normal_password') or creds.get('password') or ''
        enable_pw = creds.get('enable_password') or ''
        
        netmiko_device = {
            'device_type': PLATFORM_MAP.get(platform, 'cisco_ios'),
            'host': ip,
            'username': username,
            'password': password,
            'port': int(device.get('management_port') or device.get('port') or 22),
            'fast_cli': True,
        }
        netmiko_device.update(build_netmiko_compatibility_kwargs())
        if enable_pw:
            netmiko_device['secret'] = enable_pw
            
        cmd = 'display mac-address' if 'huawei' in platform or 'h3c' in platform else 'show mac address-table'
        try:
            with ConnectHandler(**netmiko_device) as client:
                if enable_pw:
                    try:
                        client.enable()
                    except Exception:
                        pass
                output = client.send_command(cmd, use_textfsm=False)
                parsed_mac = parse_mac_table_regex(output)
                for item in parsed_mac:
                    item['device_id'] = dev_id
                return parsed_mac
        except Exception as e:
            logger.error("Failed to collect MAC for device %s: %s", device.get('hostname'), e)
            return []

    all_arp = []
    if l3_devices:
        workers = min(5, len(l3_devices))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(collect_device_arp, dev) for dev in l3_devices]
            for f in as_completed(futures):
                all_arp.extend(f.result())

    all_mac = []
    if l2_devices:
        workers = min(5, len(l2_devices))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(collect_device_mac, dev) for dev in l2_devices]
            for f in as_completed(futures):
                all_mac.extend(f.result())

    # Write to DB sequentially
    db_conn = get_db_connection()
    try:
        last_update = _beijing_now_iso()
        if all_arp:
            for item in all_arp:
                uid = f"{item['device_id']}_{item['ip']}_{item['mac']}"
                db_conn.execute('''
                    INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        interface_name = excluded.interface_name,
                        vlan_id = excluded.vlan_id,
                        last_updated = excluded.last_updated
                ''', (uid, item['device_id'], item['ip'], item['mac'], item['interface'], item['vlan'], last_update))
                
        if all_mac:
            for item in all_mac:
                uid = f"{item['device_id']}_{item['mac']}_{item['interface']}_{item['vlan']}"
                db_conn.execute('''
                    INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        entry_type = excluded.entry_type,
                        last_updated = excluded.last_updated
                ''', (uid, item['device_id'], item['mac'], item['interface'], item['vlan'], item['type'], last_update))
        db_conn.commit()
        logger.info("Successfully updated raw ARP/MAC cache in DB.")
    except Exception as db_err:
        logger.error("Failed to write ARP/MAC to DB: %s", db_err)
    finally:
        db_conn.close()

    # Call track_and_locate_endpoints()
    from services.endpoint_tracker_service import track_and_locate_endpoints
    try:
        track_and_locate_endpoints()
    except Exception as e:
        logger.error("Failed to execute track_and_locate_endpoints: %s", e)
        
    logger.info("[Scheduler Job] poll_endpoints_job completed.")


def sync_routing_neighbors_job():
    """System periodic task: Collect dynamic OSPF and BGP neighbor states."""
    logger.info("[Scheduler Job] Starting sync_routing_neighbors_job...")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM devices WHERE status = 'online'").fetchall()
        devices = [dict(row) for row in rows]
    finally:
        conn.close()

    if not devices:
        logger.info("[Scheduler Job] No online devices found for routing neighbors sync.")
        return

    _L3_ROLES = {'router', 'gateway', 'core', 'dist', 'aggregation', 'l3switch'}
    l3_devices = [d for d in devices if (d.get('role') or '').lower().strip() in _L3_ROLES]

    if not l3_devices:
        logger.info("[Scheduler Job] No eligible L3 routing devices found.")
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.operational_data_service import collect_operational_data

    workers = min(5, len(l3_devices))
    all_neighbors = []

    def collect_neighbors(dev: dict) -> list[dict]:
        ip = dev.get('ip_address')
        port = int(dev.get('management_port') or dev.get('port') or 22)
        from drivers.ssh_compat import is_ssh_port_open
        if not is_ssh_port_open(ip, port):
            logger.warning("Failed to collect routing neighbors for device %s: SSH port %s is closed/unreachable", dev.get('hostname'), port)
            return []

        dev_id = dev['id']
        res = []
        try:
            payload = collect_operational_data(dev, categories=['bgp', 'ospf'])
            for cat_res in payload.get('categories', []):
                key = cat_res.get('key')
                records = cat_res.get('records', [])
                if key == 'bgp':
                    for r in records:
                        neigh_ip = r.get('bgp_neigh') or r.get('bgp_neighbor') or r.get('neighbor') or r.get('peer_address') or r.get('peer') or r.get('neighbor_ip') or r.get('peer_ip') or ''
                        if not neigh_ip:
                            continue
                        
                        remote_as = None
                        for k in ['neigh_as', 'as', 'peer_as', 'remote_as', 'neighbor_as']:
                            if k in r and r[k] is not None:
                                try:
                                    remote_as = int(r[k])
                                    break
                                except Exception:
                                    pass
                        
                        local_as = 0
                        for k in ['local_as', 'local_as_num', 'local_as_number', 'my_as']:
                            if k in r and r[k] is not None:
                                try:
                                    local_as = int(r[k])
                                    break
                                except Exception:
                                    pass
                        
                        state_raw = r.get('state_pfxrcd') or r.get('state') or r.get('pfx_rcd') or r.get('status') or ''
                        state = 'Established'
                        if state_raw:
                            if str(state_raw).isdigit():
                                state = 'Established'
                            elif str(state_raw).lower() in ('established', 'established/established'):
                                state = 'Established'
                            else:
                                state = str(state_raw)
                        
                        uptime = r.get('up_down') or r.get('uptime') or r.get('elapsed_time') or r.get('time') or ''
                        
                        res.append({
                            'device_id': dev_id,
                            'protocol': 'bgp',
                            'neighbor_id': neigh_ip,
                            'neighbor_ip': neigh_ip,
                            'state': state,
                            'uptime': str(uptime),
                            'local_as': local_as,
                            'remote_as': remote_as or 0,
                            'area_id': '',
                            'local_interface': ''
                        })
                elif key == 'ospf':
                    for r in records:
                        neigh_id = r.get('neighbor_id') or r.get('router_id') or ''
                        neigh_ip = r.get('address') or r.get('neighbor_address') or r.get('neighbor_ip') or r.get('ip_address') or ''
                        if not neigh_id and not neigh_ip:
                            continue
                        
                        state = r.get('state') or ''
                        local_intf = r.get('interface') or r.get('interface_name') or r.get('local_interface') or ''
                        area_id = r.get('area_id') or '0.0.0.0'
                        
                        res.append({
                            'device_id': dev_id,
                            'protocol': 'ospf',
                            'neighbor_id': neigh_id or neigh_ip,
                            'neighbor_ip': neigh_ip or neigh_id,
                            'state': state,
                            'uptime': '',
                            'remote_as': 0,
                            'area_id': area_id,
                            'local_interface': local_intf
                        })
        except Exception as e:
            logger.debug(f"[Scheduler Job] Failed to collect routing neighbors from {dev.get('hostname') or dev.get('ip_address')}: {e}")
        return res

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(collect_neighbors, dev): dev for dev in l3_devices}
        for future in as_completed(future_map):
            try:
                res = future.result()
                all_neighbors.extend(res)
            except Exception as e:
                logger.debug(f"[Scheduler Job] ThreadPool error during neighbor collection: {e}")

    db_conn = get_db_connection()
    try:
        db_conn.execute("DELETE FROM routing_neighbors")
        last_update = _beijing_now_iso()
        for item in all_neighbors:
            uid = f"{item['device_id']}_{item['protocol']}_{item['neighbor_ip']}_{item['local_interface']}"
            db_conn.execute('''
                INSERT INTO routing_neighbors (
                    id, device_id, protocol, neighbor_id, neighbor_ip, local_interface, state, uptime, local_as, remote_as, area_id, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                uid,
                item['device_id'],
                item['protocol'],
                item['neighbor_id'],
                item['neighbor_ip'],
                item['local_interface'],
                item['state'],
                item['uptime'],
                item.get('local_as', 0),
                item['remote_as'],
                item['area_id'],
                last_update
            ))
        db_conn.commit()
        logger.info(f"Successfully synced {len(all_neighbors)} routing neighbors to DB.")
    except Exception as db_err:
        logger.error("Failed to write routing neighbors to DB: %s", db_err)
    finally:
        db_conn.close()

    logger.info("[Scheduler Job] sync_routing_neighbors_job completed.")


def sync_bgp_routes_job():
    """System periodic task: Collect BGP routing tables from L3 devices.

    Collects both the global/default BGP table AND per-VRF BGP tables.
    VRF names are sourced from the CMDB ``vrfs`` table.
    """
    logger.info("[Scheduler Job] Starting sync_bgp_routes_job...")
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM devices WHERE status = 'online'").fetchall()
        devices = [dict(row) for row in rows]

        # Load VRF names from CMDB
        vrf_rows = conn.execute("SELECT vrf_name FROM vrfs ORDER BY vrf_name").fetchall()
        cmdb_vrfs = [dict(r)['vrf_name'] for r in vrf_rows if dict(r).get('vrf_name')]
    finally:
        conn.close()

    if not devices:
        logger.info("[Scheduler Job] No online devices found for BGP routes sync.")
        return

    _L3_ROLES = {'router', 'gateway', 'core', 'dist', 'aggregation', 'l3switch'}
    l3_devices = [d for d in devices if (d.get('role') or '').lower().strip() in _L3_ROLES]

    if not l3_devices:
        logger.info("[Scheduler Job] No eligible L3 routing devices found.")
        return

    logger.info(f"[Scheduler Job] BGP sync: {len(l3_devices)} devices, "
                f"VRFs from CMDB: {cmdb_vrfs or ['(none)']}")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.operational_data_service import (
        collect_operational_data,
        _build_connection_params,
        _parse_bgp_routes_raw,
        PLATFORM_DEVICE_TYPE_MAP,
    )
    from netmiko import ConnectHandler
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs

    workers = min(5, len(l3_devices))
    all_routes = []

    # ── Platform → VRF BGP command mapping ─────────────────
    VRF_BGP_CMD = {
        'cisco_ios': 'show ip bgp vrf {vrf}',
        'cisco_nxos': 'show bgp vrf {vrf} ipv4 unicast',
        'arista_eos': 'show ip bgp vrf {vrf}',
        'huawei_vrp': 'display bgp vpnv4 vpn-instance {vrf} routing-table',
        'h3c_comware': 'display bgp vpnv4 vpn-instance {vrf} routing-table',
        'ruijie_rgos': 'show ip bgp vrf {vrf}',
    }

    def _normalize_records(records: list[dict], device_id: str, vrf_name: str, local_as: int = 0) -> list[dict]:
        """Normalize a set of parsed BGP records into our DB schema."""
        res = []
        for r in records:
            prefix = r.get('prefix') or r.get('network')
            next_hop = r.get('next_hop')
            if not prefix or not next_hop:
                continue

            raw_lp = r.get('loc_pref') or r.get('local_pref') or 0
            try:
                loc_pref = int(raw_lp) if raw_lp != '' else 0
            except (ValueError, TypeError):
                loc_pref = 0

            raw_metric = r.get('metric', 0)
            try:
                metric = int(raw_metric) if raw_metric != '' else 0
            except (ValueError, TypeError):
                metric = 0

            raw_weight = r.get('weight', 0)
            try:
                weight = int(raw_weight) if raw_weight != '' else 0
            except (ValueError, TypeError):
                weight = 0

            as_path = r.get('as_path', '')
            origin = r.get('origin', '')
            if origin and origin not in as_path:
                as_path = f"{as_path} {origin}".strip() if as_path else origin

            is_best = r.get('is_best', 0)
            if not is_best and r.get('path_selection') == '>':
                is_best = 1

            res.append({
                'device_id': device_id,
                'vrf_name': vrf_name,
                'prefix': prefix,
                'next_hop': next_hop,
                'metric': metric,
                'loc_pref': loc_pref,
                'weight': weight,
                'as_path': as_path,
                'local_as': local_as,
                'is_best': is_best,
                'is_active': r.get('is_active', is_best),
            })
        return res

    def collect_bgp_routes(dev: dict) -> list[dict]:
        dev_id = dev['id']
        from core.platform_utils import normalize_device_platform
        platform = normalize_device_platform(dev.get('vendor'), dev.get('platform'))
        res = []
        local_as = 0

        # ── 1. Collect default/global BGP table and BGP summary via standard flow ──
        try:
            payload = collect_operational_data(dev, categories=['bgp', 'bgp_routes'])
            bgp_records = []
            bgp_routes_records = []
            for cat_res in payload.get('categories', []):
                if cat_res.get('key') == 'bgp':
                    bgp_records = cat_res.get('records', [])
                elif cat_res.get('key') == 'bgp_routes':
                    bgp_routes_records = cat_res.get('records', [])

            if bgp_records:
                local_as = bgp_records[0].get('local_as', 0)

            res.extend(_normalize_records(
                bgp_routes_records, dev_id, 'default', local_as
            ))
        except Exception as e:
            logger.debug(f"[Scheduler Job] Default BGP collection failed for "
                         f"{dev.get('hostname')}: {e}")

        # ── 2. Collect per-VRF BGP tables ──────────────────────────
        if cmdb_vrfs:
            vrf_cmd_template = VRF_BGP_CMD.get(platform, VRF_BGP_CMD['cisco_ios'])
            try:
                conn_params = _build_connection_params(dev)
                with ConnectHandler(**conn_params) as client:
                    if conn_params.get('secret'):
                        try:
                            client.enable()
                        except Exception:
                            pass

                    for vrf_name in cmdb_vrfs:
                        try:
                            cmd = vrf_cmd_template.format(vrf=vrf_name)
                            output = client.send_command(
                                cmd,
                                cmd_verify=False,
                                strip_prompt=True,
                                strip_command=True,
                                read_timeout=30,
                            )
                            if not output or not output.strip():
                                continue
                            # Skip error responses
                            lowered = output.strip().lower()
                            if any(err in lowered for err in (
                                '% invalid', 'not exist', 'not found',
                                'no matching', 'address family not',
                             )):
                                continue

                            records = _parse_bgp_routes_raw(output, platform)
                            res.extend(_normalize_records(records, dev_id, vrf_name, local_as))
                            if records:
                                logger.debug(
                                    f"[Scheduler Job] {dev.get('hostname')}: "
                                    f"VRF {vrf_name} → {len(records)} BGP routes"
                                )
                        except Exception as vrf_err:
                            logger.debug(
                                f"[Scheduler Job] VRF {vrf_name} BGP failed on "
                                f"{dev.get('hostname')}: {vrf_err}"
                            )
            except Exception as conn_err:
                logger.debug(
                    f"[Scheduler Job] VRF SSH connection failed for "
                    f"{dev.get('hostname')}: {conn_err}"
                )

        return res

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(collect_bgp_routes, dev): dev for dev in l3_devices}
        for future in as_completed(future_map):
            try:
                res = future.result()
                all_routes.extend(res)
            except Exception as e:
                logger.debug(f"[Scheduler Job] ThreadPool error during BGP routes collection: {e}")

    db_conn = get_db_connection()
    try:
        db_conn.execute("DELETE FROM bgp_route_table")
        last_update = _beijing_now_iso()
        for item in all_routes:
            uid = f"{item['device_id']}_{item['vrf_name']}_{item['prefix']}_{item['next_hop']}_{item['as_path']}"
            db_conn.execute('''
                INSERT INTO bgp_route_table (
                    id, device_id, vrf_name, prefix, next_hop, metric, loc_pref, weight, as_path, local_as, is_best, is_active, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                uid,
                item['device_id'],
                item['vrf_name'],
                item['prefix'],
                item['next_hop'],
                item['metric'],
                item['loc_pref'],
                item['weight'],
                item['as_path'],
                item['local_as'],
                item['is_best'],
                item['is_active'],
                last_update
            ))
        db_conn.commit()

        # Count by VRF for informative logging
        vrf_counts = {}
        for item in all_routes:
            vrf_counts[item['vrf_name']] = vrf_counts.get(item['vrf_name'], 0) + 1
        vrf_summary = ', '.join(f"{k}={v}" for k, v in sorted(vrf_counts.items()))
        logger.info(f"Successfully synced {len(all_routes)} BGP routes to DB. "
                    f"VRF breakdown: {vrf_summary or 'none'}")
    except Exception as db_err:
        logger.error("Failed to write BGP routes to DB: %s", db_err)
    finally:
        db_conn.close()

    logger.info("[Scheduler Job] sync_bgp_routes_job completed.")


