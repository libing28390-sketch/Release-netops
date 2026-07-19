# -*- coding: utf-8 -*-
import asyncio
import uuid
import json
import logging
from datetime import datetime, timezone
from database import get_db_connection
from services.vault_service import resolve_device_credentials
from .manager import ws_manager
from .scenarios import (
    _render_phase_commands,
    resolve_platform_phases,
    resolve_platform_value,
)
from .builtin_scenarios import PLATFORM_SAVE_COMMANDS, PLATFORM_SHOW_RUNNING

logger = logging.getLogger("api.playbooks.engine")

# P2: 设备粒度互斥锁 (device_id → asyncio.Lock)
_device_locks: dict[str, asyncio.Lock] = {}

def _get_device_lock(device_id: str) -> asyncio.Lock:
    if device_id not in _device_locks:
        _device_locks[device_id] = asyncio.Lock()
    return _device_locks[device_id]

# P3: 待确认 commit 的回滚任务 (execution_id → asyncio.Task)
_pending_rollbacks: dict[str, asyncio.Task] = {}


def _save_snapshot(hostname: str, config_text: str) -> None:
    """将变更前的 running-config 保存到 backup/snapshots/ 目录。"""
    import os
    snap_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'backup', 'snapshots')
    os.makedirs(snap_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(snap_dir, f"{hostname}_{ts}_pre_change.txt")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(config_text)
        logger.info(f"Pre-change snapshot saved: {filename}")
    except Exception as e:
        logger.warning(f"Failed to save snapshot for {hostname}: {e}")


async def _save_device_result_to_db(
    execution_id: str,
    device_id: str,
    device: dict,
    device_result: dict,
    started_at_iso: str,
) -> None:
    """Persist one device's execution result into execution_device_results."""
    completed_at_iso = datetime.now().isoformat()
    try:
        started_dt = datetime.fromisoformat(started_at_iso)
        completed_dt = datetime.fromisoformat(completed_at_iso)
        duration_ms = int((completed_dt - started_dt).total_seconds() * 1000)
    except Exception:
        duration_ms = 0
    try:
        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO execution_device_results
               (id, execution_id, device_id, hostname, ip_address, status,
                error_message, phases_json, started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 execution_id=excluded.execution_id, device_id=excluded.device_id,
                 hostname=excluded.hostname, ip_address=excluded.ip_address,
                 status=excluded.status, error_message=excluded.error_message,
                 phases_json=excluded.phases_json, started_at=excluded.started_at,
                 completed_at=excluded.completed_at, duration_ms=excluded.duration_ms''',
            (
                str(uuid.uuid4()), execution_id, device_id,
                device.get('hostname') or device_id,
                device.get('ip_address') or device.get('ip') or '',
                device_result.get('status', 'success'),
                device_result.get('error', ''),
                json.dumps(device_result.get('phases', {})),
                started_at_iso, completed_at_iso, duration_ms,
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[DB] Failed to save device result for {device_id}: {e}")



async def _run_playbook(
    execution_id: str,
    device_ids: list,
    phases: dict,
    variables: dict,
    dry_run: bool,
    concurrency: int,
    platform: str = 'cisco_ios',
    commit_confirmed_ttl: int = 0,
):
    """
    Execute the playbook across all selected devices with concurrency control.
    Emits events through WebSocket in real time.
    """
    from services.automation_service import AutomationService

    conn = get_db_connection()
    conn.execute("UPDATE playbook_executions SET status='running', updated_at=? WHERE id=?",
                 (datetime.now().isoformat(), execution_id))
    conn.commit()

    # Load device info
    device_rows = conn.execute(
        f"SELECT * FROM devices WHERE id IN ({','.join('?' * len(device_ids))})",
        device_ids
    ).fetchall()
    devices = {}
    for d in device_rows:
        dd = dict(d)
        creds = resolve_device_credentials(dd)
        dd['username'] = creds.get('normal_username') or ''
        dd['password'] = creds.get('normal_password') or ''
        dd['enable_password'] = creds.get('enable_password') or ''
        devices[d['id']] = dd
    conn.close()

    total = len(device_ids)
    results = {}      # device_id → {pre_check, execute, post_check, rollback, status}
    overall_ok = True

    await ws_manager.emit(execution_id, {
        "type": "start",
        "execution_id": execution_id,
        "total_devices": total,
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
    })

    semaphore = asyncio.Semaphore(concurrency)

    async def _process_device(device_id: str, idx: int):
        nonlocal overall_ok
        started_at_iso = datetime.now().isoformat()
        device = devices.get(device_id)
        if not device:
            await ws_manager.emit(execution_id, {
                "type": "device_error",
                "device_id": device_id,
                "error": "Device not found in DB",
            })
            err_result = {"status": "error", "error": "not found", "phases": {}}
            await _save_device_result_to_db(execution_id, device_id, {}, err_result, started_at_iso)
            results[device_id] = err_result
            return

        hostname = device.get('hostname', device_id)
        driver_type = 'mock' if device.get('ip_address') in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
        service = AutomationService(driver_type=driver_type)

        device_result = {"status": "success", "phases": {}}

        try:
            # The request-level platform is only a UI/approval hint. The
            # executable command source is the platform stored on this asset.
            # This is what prevents a Huawei/H3C device from receiving the
            # Cisco phase that happened to be selected in the browser.
            device_phases, resolved_platform = resolve_platform_phases(
                phases,
                device.get('platform'),
                device.get('vendor'),
            )
            device_result["platform"] = resolved_platform
        except KeyError as exc:
            overall_ok = False
            device_result["status"] = "error"
            device_result["error"] = str(exc)
            await ws_manager.emit(execution_id, {
                "type": "device_error",
                "device_id": device_id,
                "hostname": hostname,
                "error": str(exc),
            })
            await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
            results[device_id] = device_result
            return

        async with semaphore:
            async with _get_device_lock(device_id):   # P2: 设备粒度互斥锁
                await ws_manager.emit(execution_id, {
                    "type": "device_start",
                    "device_id": device_id,
                    "hostname": hostname,
                    "index": idx,
                    "total": total,
                })

                # ──── PHASE 1: Pre-Check ────
                pre_cmds = _render_phase_commands(device_phases.get('pre_check', []), variables)
                if pre_cmds:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "pre_check", "commands": pre_cmds,
                    })
                    pre_output = await _exec_commands(service, device, pre_cmds, is_config=False)
                    device_result["phases"]["pre_check"] = pre_output
                    if not pre_output.get("success", True):
                        overall_ok = False   # pre_check errors → partial_failure, but execution continues
                    await ws_manager.emit(execution_id, {
                        "type": "phase_done", "device_id": device_id,
                        "phase": "pre_check", "output": pre_output,
                    })

                # ──── P1: 变更前快照 ────
                if not dry_run:
                    snap_cmd = resolve_platform_value(
                        PLATFORM_SHOW_RUNNING,
                        device.get('platform'),
                        device.get('vendor'),
                    )
                    if snap_cmd:
                        snap_output = await _exec_commands(service, device, [snap_cmd], is_config=False)
                        if snap_output.get('success'):
                            _save_snapshot(hostname, snap_output.get('output', ''))
                            device_result["snapshot"] = "saved"
                        await ws_manager.emit(execution_id, {
                            "type": "snapshot", "device_id": device_id,
                            "hostname": hostname,
                            "status": "saved" if snap_output.get('success') else "failed",
                        })

                # ──── PHASE 2: Execute ────
                exec_cmds = _render_phase_commands(device_phases.get('execute', []), variables)
                if exec_cmds:
                    if dry_run:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                            "dry_run": True,
                        })
                        device_result["phases"]["execute"] = {
                            "commands": exec_cmds,
                            "output": "[DRY-RUN] Commands not sent to device",
                            "success": True,
                        }
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": device_result["phases"]["execute"],
                            "dry_run": True,
                        })
                    else:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                        })
                        # Determine if commands need config mode.
                        # Show/display/ping commands are exec-mode only; config commands
                        # (interface, vlan, router, etc.) need config mode.
                        _show_prefixes = (
                            'show ', 'display ', 'ping ', 'traceroute ', 'tracert ',
                            'dir ', 'more ', 'terminal ', 'debug ', 'undebug ',
                        )
                        _needs_config = not all(
                            any(cmd.lower().strip().startswith(p) for p in _show_prefixes)
                            for cmd in exec_cmds
                            if cmd.strip()
                        )
                        exec_output = await _exec_commands(service, device, exec_cmds, is_config=_needs_config)
                        device_result["phases"]["execute"] = exec_output
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": exec_output,
                        })

                        # P0: Execute 失败 → 自动回滚
                        if not exec_output.get("success", True):
                            overall_ok = False
                            device_result["status"] = "failed"
                            await _do_rollback(execution_id, service, device, device_phases, variables)
                            device_result["phases"]["rollback"] = {"triggered": True, "reason": "execute_failed"}
                            await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                            results[device_id] = device_result
                            return

                # ──── PHASE 3: Post-Check ────
                post_cmds = _render_phase_commands(device_phases.get('post_check', []), variables)
                if post_cmds and not dry_run:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "post_check", "commands": post_cmds,
                    })
                    post_output = await _exec_commands(service, device, post_cmds, is_config=False)
                    device_result["phases"]["post_check"] = post_output
                    await ws_manager.emit(execution_id, {
                        "type": "phase_done", "device_id": device_id,
                        "phase": "post_check", "output": post_output,
                    })

                    # P0: Post-Check 执行失败 → 自动回滚（连接中断/命令报错）
                    if not post_output.get("success", True):
                        overall_ok = False
                        device_result["status"] = "post_check_failed"
                        await ws_manager.emit(execution_id, {
                            "type": "post_check_failed", "device_id": device_id,
                            "hostname": hostname,
                            "message": "Post-check failed, triggering automatic rollback",
                        })
                        await _do_rollback(execution_id, service, device, device_phases, variables)
                        device_result["phases"]["rollback"] = {"triggered": True, "reason": "post_check_failed"}
                        await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                        results[device_id] = device_result
                        return

                # ──── P0: Save Phase（写入持久化存储）────
                if not dry_run and exec_cmds:
                    save_cmd = resolve_platform_value(
                        PLATFORM_SAVE_COMMANDS,
                        device.get('platform'),
                        device.get('vendor'),
                    )
                    if save_cmd:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "save", "commands": [save_cmd],
                        })
                        save_output = await _exec_commands(service, device, [save_cmd], is_config=False)
                        device_result["phases"]["save"] = save_output
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "save", "output": save_output,
                        })

                await ws_manager.emit(execution_id, {
                    "type": "device_done", "device_id": device_id,
                    "hostname": hostname, "status": device_result["status"],
                })
                await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                results[device_id] = device_result

    # Run with concurrency control
    tasks = [_process_device(did, i) for i, did in enumerate(device_ids)]
    await asyncio.gather(*tasks)

    final_status = 'success' if overall_ok else 'partial_failure'
    if dry_run:
        final_status = 'dry_run_complete'

    # Persist results
    success_c = sum(1 for r in results.values() if r.get('status') == 'success')
    failed_c  = sum(1 for r in results.values() if r.get('status') in ('failed', 'error'))
    partial_c = sum(1 for r in results.values() if 'partial' in r.get('status', '') or 'check_failed' in r.get('status', ''))
    conn2 = get_db_connection()
    conn2.execute(
        """UPDATE playbook_executions
           SET status=?, results_json=?, updated_at=?,
               total_devices=?, success_count=?, failed_count=?, partial_count=?
           WHERE id=?""",
        (final_status, json.dumps(results), datetime.now().isoformat(),
         total, success_c, failed_c, partial_c, execution_id)
    )
    conn2.commit()
    conn2.close()

    # ──── P3: Commit Confirmed 安全网 ────
    # 若请求方指定了 commit_confirmed_ttl > 0，且本次执行全部成功，
    # 启动一个倒计时任务：超时后自动对所有设备执行回滚。
    # 调用 POST /api/playbooks/executions/{id}/confirm-commit 可取消定时器。
    if commit_confirmed_ttl > 0 and overall_ok and not dry_run:
        async def _auto_rollback():
            await asyncio.sleep(commit_confirmed_ttl)
            if execution_id not in _pending_rollbacks:
                return  # 已被 confirm-commit 取消
            del _pending_rollbacks[execution_id]
            await ws_manager.emit(execution_id, {
                "type": "commit_confirmed_timeout",
                "message": f"Commit not confirmed within {commit_confirmed_ttl}s, auto-rollback triggered",
                "execution_id": execution_id,
            })
            for did in device_ids:
                dev = devices.get(did)
                if dev:
                    svc_type = 'mock' if dev.get('ip_address') in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
                    svc = AutomationService(driver_type=svc_type)
                    try:
                        dev_phases, _ = resolve_platform_phases(
                            phases, dev.get('platform'), dev.get('vendor')
                        )
                    except KeyError as exc:
                        logger.warning("[Rollback] No platform phases for %s: %s", did, exc)
                        continue
                    await _do_rollback(execution_id, svc, dev, dev_phases, variables)

        task = asyncio.create_task(_auto_rollback())
        _pending_rollbacks[execution_id] = task
        await ws_manager.emit(execution_id, {
            "type": "commit_confirm_pending",
            "execution_id": execution_id,
            "ttl": commit_confirmed_ttl,
            "message": f"Changes deployed. Auto-rollback in {commit_confirmed_ttl}s unless confirmed.",
        })

    await ws_manager.emit(execution_id, {
        "type": "complete",
        "execution_id": execution_id,
        "status": final_status,
        "summary": {
            "total": total,
            "success": sum(1 for r in results.values() if r.get("status") == "success"),
            "failed": sum(1 for r in results.values() if r.get("status") != "success"),
        },
        "timestamp": datetime.now().isoformat(),
    })



async def _exec_commands(service, device: dict, commands: list, is_config: bool) -> dict:
    """Execute commands on a single device in a thread pool."""
    loop = asyncio.get_event_loop()

    def _run():
        try:
            results = service.execute_commands(device, commands, is_config=is_config)
            output_lines = []
            all_ok = True
            cmd_iter = iter(commands)
            for r in results:
                cmd_label = next(cmd_iter, None)
                if r.get('success', False):
                    out = r.get('output') or r.get('stdout') or ''
                    if cmd_label:
                        if is_config:
                            cmd_str = " | ".join(commands)
                            output_lines.append(f"# {cmd_str}\n{out}")
                        else:
                            output_lines.append(f"# {cmd_label}\n{out}")
                    else:
                        output_lines.append(out)
                else:
                    err = r.get('error') or r.get('stderr') or ''
                    if cmd_label:
                        if is_config:
                            cmd_str = " | ".join(commands)
                            output_lines.append(f"# {cmd_str}\nERROR: {err}")
                        else:
                            output_lines.append(f"# {cmd_label}\nERROR: {err}")
                    else:
                        output_lines.append(f"ERROR: {err}")
                    all_ok = False
            return {"success": all_ok, "output": "\n\n".join(output_lines), "commands": commands}
        except Exception as e:
            return {"success": False, "output": str(e), "commands": commands, "error": str(e)}

    return await loop.run_in_executor(None, _run)


async def _do_rollback(execution_id: str, service, device: dict, phases: dict, variables: dict):
    """Execute rollback phase and notify via WebSocket."""
    rollback_cmds = _render_phase_commands(phases.get('rollback', []), variables)
    hostname = device.get('hostname', device.get('id', ''))
    if not rollback_cmds:
        await ws_manager.emit(execution_id, {
            "type": "rollback", "device_id": device['id'],
            "hostname": hostname, "status": "no_rollback_defined",
        })
        return

    await ws_manager.emit(execution_id, {
        "type": "rollback_start", "device_id": device['id'],
        "hostname": hostname, "commands": rollback_cmds,
    })
    result = await _exec_commands(service, device, rollback_cmds, is_config=True)
    await ws_manager.emit(execution_id, {
        "type": "rollback_done", "device_id": device['id'],
        "hostname": hostname, "output": result,
    })
