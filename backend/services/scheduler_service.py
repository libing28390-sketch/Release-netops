import uuid
import json
import asyncio
import logging
import time
from datetime import datetime
from database import get_db_connection
from services.automation_service import AutomationService
from services.notification_service import dispatch_to_all_users
from core.crypto import decrypt_credential

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
        job = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job or not job['enabled']:
            return

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

        # 2. 获取命令或脚本内容
        commands_str = job['commands'] or ""
        script_name = "Scheduled Job"
        is_shell_script = False
        if job['script_id']:
            script = conn.execute("SELECT name, content, script_type FROM scripts WHERE id = ?", (job['script_id'],)).fetchone()
            if script:
                commands_str = script['content']
                script_name = script['name']
                if script.get('script_type') == 'shell':
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
            # Use normal (least-privilege) credentials for scheduled command execution.
            # Admin credentials are only needed for config changes; read-only health
            # checks and monitoring scripts should run as the normal user.
            normal_user = d.get('normal_username', '').strip()
            normal_pass = d.get('normal_password', '').strip()
            if normal_user and normal_pass:
                d['username'] = normal_user
                d['password'] = decrypt_credential(normal_pass) or ''
                logger.info(f"[Scheduler] Using normal credentials for device {d.get('hostname', d.get('ip_address'))}")
            else:
                # Fallback: no normal creds configured, use whatever is available
                fallback_user = d.get('username', '').strip()
                fallback_pass = decrypt_credential(d.get('password') or '') or ''
                if not fallback_user or not fallback_pass:
                    # Last resort: admin creds
                    fallback_user = d.get('admin_username', '').strip() or fallback_user
                    fallback_pass = decrypt_credential(d.get('admin_password') or '') or fallback_pass
                d['username'] = fallback_user
                d['password'] = fallback_pass
                logger.info(f"[Scheduler] No normal credentials, falling back to '{fallback_user}' for device {d.get('hostname', d.get('ip_address'))}")

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
                is_server = any(t in platform for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server'))

                if is_shell_script and is_server:
                    # Linux/server: use LinuxDriver via SCRIPT mode.
                    d['asset_type'] = 'server'
                    exec_results_raw = await loop.run_in_executor(
                        None,
                        lambda: service.orchestrator.execute_single(d, 'script', commands_str)
                    )
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

                # ── Normalise output ─────────────────────────────────────────
                def _get_output(r: dict) -> str:
                    return r.get('output') or r.get('stdout') or ''

                success = all(r.get('success', False) for r in exec_results)

                processed_commands = []
                business_anomaly = False
                anomaly_msg = ""
                _sentinel_begin = "---NETOPS_BEGIN---"
                _sentinel_end   = "---NETOPS_END---"

                for r in exec_results:
                    out = str(_get_output(r))
                    if is_shell_script and not is_server:
                        if _sentinel_begin in out and _sentinel_end in out:
                            out = out.split(_sentinel_begin)[-1].split(_sentinel_end)[0].strip()
                        elif _sentinel_begin in out:
                            out = out.split(_sentinel_begin)[-1].strip() + "\n[Warning: Execution might be incomplete]"

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
                        replace_existing=True
                    )
                    logger.info(f"Scheduled cron job: {job['name']} ({job['cron_expr']})")
                except Exception as e:
                    logger.error(f"Failed to schedule job {job['name']}: {e}")
            elif job['job_type'] == 'once' and job['scheduled_at']:
                # 单次任务处理逻辑 (可选实现)
                pass
    finally:
        conn.close()

def run_scheduled_automation_job_sync_wrapper(job_id: str):
    """同步包装器，用于 APScheduler 调用协程"""
    import asyncio
    try:
        # 获取当前运行的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_scheduled_automation_job(job_id))
        loop.close()
    except Exception as e:
        logger.error(f"Error in scheduled job wrapper for {job_id}: {e}")
