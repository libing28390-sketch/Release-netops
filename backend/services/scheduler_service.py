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

        if is_shell_script:
            import uuid
            tmp_file = f"/tmp/netops_{uuid.uuid4().hex}.sh"
            import base64
            encoded_script = base64.b64encode(commands_str.encode()).decode()
            sentinel_begin = "---NETOPS_BEGIN---"
            sentinel_end = "---NETOPS_END---"
            res_file = f"{tmp_file}.log"
            
            # 决战方案：
            # 1. Base64 编码传输：彻底消除脚本内容中 #, >, $ 等字符对 Netmiko 提示符识别的干扰
            # 2. 管道解码：直接通过 base64 -d 还原文件，极其稳健
            # 3. 结果重定向：依然使用文件落地，确保 cat 时能一气呵成
            wrapped_command = (
                f"echo '{encoded_script}' | base64 -d > {tmp_file}; "
                f"printf '\\n{sentinel_begin}\\n'; "
                f"/bin/bash {tmp_file} > {res_file} 2>&1; "
                f"sleep 1; "
                f"cat {res_file}; "
                f"printf '\\n{sentinel_end}\\n'; "
                f"rm -f {tmp_file} {res_file}"
            )
            commands = [wrapped_command]
        else:
            commands = [c.strip() for c in commands_str.split('\n') if c.strip()]
        
        # 3. 初始化执行历史记录 (Surface in Execution History)
        execution_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()
        
        conn.execute(
            '''INSERT INTO playbook_executions 
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (execution_id, f"scheduled:{job_id}", job['name'], 'mixed', 
             json.dumps(device_ids), '{}', 'running', 0, job['created_by'] or 'system', 5, now_iso, now_iso)
        )
        conn.commit()

        # 4. 执行
        total_failed = 0
        total_success = 0
        failure_details = []

        service = AutomationService(driver_type='netmiko') # 默认 netmiko

        for dev_id in device_ids:
            device = conn.execute("SELECT * FROM devices WHERE id = ?", (dev_id,)).fetchone()
            if not device: continue
            
            d = dict(device)
            d['password'] = decrypt_credential(d.get('password')) or ''
            
            # 记录设备开始执行
            dev_started_at = datetime.now().isoformat()
            dev_result_id = str(uuid.uuid4())
            conn.execute(
                '''INSERT INTO execution_device_results 
                   (id, execution_id, device_id, hostname, ip_address, status, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (dev_result_id, execution_id, dev_id, d['hostname'], d['ip_address'], 'running', dev_started_at)
            )
            conn.commit()

            try:
                loop = asyncio.get_event_loop()
                exec_results = await loop.run_in_executor(None, lambda: service.execute_commands(d, commands, is_config=bool(job['is_config'])))
                
                # 判断是否全部成功
                success = all(r.success for r in exec_results)
                
                # 铁腕清洗：使用双锚点隔离法，绝对过滤回显和杂质
                processed_commands = []
                business_anomaly = False
                anomaly_msg = ""
                
                begin_mark = "---NETOPS_BEGIN---"
                end_mark = "---NETOPS_END---"
                
                for r in exec_results:
                    out = r.output
                    if is_shell_script:
                        if begin_mark in out and end_mark in out:
                            # 精准提取两个锚点之间的内容
                            out = out.split(begin_mark)[-1].split(end_mark)[0].strip()
                        elif begin_mark in out:
                            # 如果只有起始锚点，说明执行到一半截断了
                            out = out.split(begin_mark)[-1].strip() + "\n[Warning: Execution might be incomplete]"
                    
                    processed_commands.append(out)
                    
                    # 业务逻辑异常检测：精准提取异常内容
                    lines = out.split('\n')
                    found_crit = False
                    for line in lines:
                        if "CRITICAL" in line or "ERROR" in line:
                            business_anomaly = True
                            found_crit = True
                            # 提取具体的异常行，去除多余空格
                            clean_line = " ".join(line.split())
                            anomaly_msg = f"检测到严重异常: {clean_line}"
                            break # 优先记录第一个严重异常
                    
                    if not found_crit:
                        for line in lines:
                            if "WARNING" in line:
                                # WARNING 仅记录描述，不作为 business_anomaly 判定依据
                                clean_line = " ".join(line.split())
                                anomaly_msg = f"检测到警告: {clean_line}"
                                break

                # 统计逻辑：业务异常优先
                # 如果脚本执行成功但业务逻辑异常，统一记为失败
                if success and not business_anomaly:
                    total_success += 1
                    phase_status = "success"
                else:
                    total_failed += 1
                    phase_status = "failed"
                    if success and business_anomaly:
                        failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 业务异常: {anomaly_msg}")
                    elif not success:
                        failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 执行失败")
                
                # 格式化输出为 phases_json 兼容格式
                phase_data = {
                    "execute": {
                        "status": phase_status,
                        "commands": processed_commands
                    }
                }
                
                # 更新设备结果
                dev_completed_at = datetime.now().isoformat()
                conn.execute(
                    '''UPDATE execution_device_results 
                       SET status = ?, error_message = ?, phases_json = ?, completed_at = ?
                       WHERE id = ?''',
                    (phase_status, 
                     anomaly_msg if business_anomaly else ("" if success else "Command failure"), 
                     json.dumps(phase_data), dev_completed_at, dev_result_id)
                )
                conn.commit()

            except Exception as e:
                total_failed += 1
                failure_details.append(f"设备 {d['hostname'] or d['ip_address']} 异常: {str(e)}")
                
                # 更新设备异常结果
                dev_completed_at = datetime.now().isoformat()
                conn.execute(
                    '''UPDATE execution_device_results 
                       SET status = ?, error_message = ?, completed_at = ?
                       WHERE id = ?''',
                    ("failed", str(e), dev_completed_at, dev_result_id)
                )
                conn.commit()

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
