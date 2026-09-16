# -*- coding: utf-8 -*-
import asyncio
import uuid
import json
import logging
import os
from datetime import datetime, timezone
from database import get_db_connection
from services.vault_service import resolve_device_credentials
from services.playbook_output_service import cleanup_expired_playbook_outputs, protect_output
from .manager import ws_manager
from .scenarios import (
    _render_phase_commands,
    _render_template,
    resolve_platform_phases,
    resolve_platform_value,
    select_controlled_steps,
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


def _redact_execution_value(value):
    """Redact sensitive material before Playbook output is persisted or pushed."""
    from services.platform_registry_service import redact_raw_output

    if isinstance(value, dict):
        return {key: _redact_execution_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_execution_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_execution_value(item) for item in value)
    if isinstance(value, str):
        return redact_raw_output(value)
    return value


def _phase_action_steps(phase_templates) -> list[dict]:
    """Extract declarative action steps without accepting raw command text."""
    if not isinstance(phase_templates, list):
        return []
    actions: list[dict] = []
    for step in phase_templates:
        if not isinstance(step, dict):
            continue
        action_code = str(step.get("action_code") or "").strip()
        if not action_code:
            continue
        # ``repeat`` is validated at the Playbook boundary. Keep this helper
        # defensive for legacy definitions loaded while the registry flag is
        # disabled: malformed values must not turn into an unbounded loop.
        repeat = step.get("repeat", 1)
        if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
            repeat = 1
        repeat = min(repeat, 10)
        action = {"action_code": action_code, "parameters": step.get("parameters") or {}}
        actions.extend(dict(action) for _ in range(repeat))
    return actions


def _phase_notification_steps(phase_templates) -> list[dict]:
    """Extract validated notification steps without accepting destinations."""
    if not isinstance(phase_templates, list):
        return []
    return [
        {
            "title": str(step.get("title", "")).strip(),
            "message": str(step.get("message", "")).strip(),
            "severity": str(step.get("severity", "info")).strip().lower(),
        }
        for step in phase_templates
        if isinstance(step, dict) and str(step.get("type") or "").strip() == "notification"
    ]


def _safe_notification_variables(variables: dict | None) -> dict:
    """Keep credentials and complex objects out of notification templates."""
    blocked_tokens = ("password", "passwd", "secret", "token", "private", "credential", "community", "api_key")
    safe: dict = {}
    for key, value in (variables or {}).items():
        lowered = str(key).lower()
        if any(token in lowered for token in blocked_tokens):
            continue
        if isinstance(value, (str, int, float, bool)) and len(str(value)) <= 256:
            safe[str(key)] = value
    return safe


def _attach_notification_result(base_result: dict | None, notification_result: dict | None) -> dict:
    result = dict(base_result or {"success": True, "commands": [], "output": ""})
    if notification_result:
        result["notifications"] = notification_result.get("notifications", [])
        result["notification_success"] = bool(notification_result.get("notification_success", True))
    return result


async def _execute_notification_steps(
    execution_id: str,
    device: dict,
    notification_steps: list[dict],
    *,
    variables: dict,
    dry_run: bool,
    actor: dict | None,
) -> dict:
    """Dispatch tenant-scoped notifications from configured channels only."""
    if not notification_steps:
        return {"notifications": [], "notification_success": True}

    tenant_id = str((actor or {}).get("tenant_id") or device.get("tenant_id") or "").strip()
    safe_variables = _safe_notification_variables(variables)
    items: list[dict] = []
    for step in notification_steps:
        title = _render_template(step.get("title", ""), safe_variables).strip()
        message = _render_template(step.get("message", ""), safe_variables).strip()
        severity = str(step.get("severity") or "info").strip().lower()
        item = {"title": title[:120], "severity": severity, "success": False}
        if not tenant_id:
            item["error_code"] = "NOTIFICATION_TENANT_REQUIRED"
        elif dry_run:
            item.update({"success": True, "status": "dry_run_skipped", "delivered": 0})
        else:
            try:
                from services.notification_service import dispatch_to_tenant_users

                dispatch_result = await asyncio.to_thread(
                    dispatch_to_tenant_users,
                    {
                        "title": title,
                        "object_name": device.get("hostname") or device.get("id") or "device",
                        "ip_address": device.get("ip_address") or "",
                        "status": "active",
                        "severity": severity,
                        "message": message,
                    },
                    tenant_id,
                )
                failed_channels = [
                    str(result.get("platform") or "unknown")
                    for result in dispatch_result
                    if not result.get("success")
                ]
                item.update({
                    "success": not failed_channels,
                    "status": "delivered" if dispatch_result else "no_configured_channels",
                    "delivered": sum(1 for result in dispatch_result if result.get("success")),
                })
                if failed_channels:
                    item["failed_channels"] = failed_channels
            except Exception:
                item["error_code"] = "NOTIFICATION_DISPATCH_FAILED"
        items.append(item)

        try:
            from services.audit_service import log_audit_event

            log_audit_event(
                event_type="PLAYBOOK_NOTIFICATION",
                category="automation",
                severity=severity if severity in {"critical", "major", "warning", "info", "low"} else "info",
                status="success" if item.get("success") else "failed",
                summary="Playbook notification step processed",
                actor_id=(actor or {}).get("id"),
                actor_username=(actor or {}).get("username"),
                actor_role=(actor or {}).get("role"),
                target_type="playbook_execution",
                target_id=execution_id,
                device_id=device.get("id"),
                execution_id=execution_id,
                details={
                    "tenant_id": tenant_id,
                    "title": title[:120],
                    "status": item.get("status"),
                    "error_code": item.get("error_code"),
                    "failed_channels": item.get("failed_channels", []),
                },
            )
        except Exception:
            logger.warning("[Playbook] Failed to audit notification step", exc_info=True)

    result = {"notifications": items, "notification_success": all(item.get("success") for item in items)}
    await ws_manager.emit(execution_id, {
        "type": "notifications",
        "device_id": device.get("id"),
        "notifications": items,
        "dry_run": dry_run,
    })
    return result


def _bind_legacy_phase_commands(device: dict, phases: dict) -> tuple[dict, list[str]]:
    """Convert exact legacy commands to registry actions for bound devices.

    This keeps existing read-only built-ins runnable when their command is an
    exact mapping in the published release, while refusing any command that
    cannot be proven to belong to that release.
    """
    if not device.get('platform_profile_id'):
        return phases, []
    from services.platform_registry_service import resolve_device_action_code

    bound_phases: dict = {}
    rejected: list[str] = []
    for phase, steps in (phases or {}).items():
        if not isinstance(steps, list):
            bound_phases[phase] = steps
            continue
        converted = []
        for step in steps:
            if isinstance(step, dict):
                if step.get('action_code') or str(step.get('type') or '').strip() in {'branch', 'notification', 'approval'}:
                    converted.append(step)
                    continue
            if isinstance(step, str):
                action_code = resolve_device_action_code(str(device.get('id') or ''), step)
                if action_code:
                    converted.append({'action_code': action_code, 'parameters': {}})
                    continue
            rejected.append(f'{phase}:{step}')
        bound_phases[phase] = converted
    return bound_phases, rejected


async def _execute_registry_actions(
    execution_id: str,
    device: dict,
    action_steps: list[dict],
    *,
    dry_run: bool,
    actor: dict | None,
) -> dict:
    """Preview or execute Playbook action steps through the platform boundary."""
    from services.platform_registry_service import execute_platform_action, preview_platform_action

    user = actor or {
        "id": "system-playbook",
        "username": "system-playbook",
        "role": "Administrator",
        "tenant_id": device.get("tenant_id") or "",
    }
    items = []
    all_ok = True
    for step in action_steps:
        action_code = step["action_code"]
        try:
            result = await asyncio.to_thread(
                preview_platform_action if dry_run else execute_platform_action,
                str(device["id"]),
                action_code,
                user=user,
                parameters=step.get("parameters") or {},
            )
            item = {
                "action_code": action_code,
                "success": bool(result.get("success")),
                "command": result.get("command"),
                "command_checksum": result.get("command_checksum"),
                "resolved_command_checksum": result.get("resolved_command_checksum"),
                "platform_release_id": result.get("platform_release_id"),
                "release_checksum": result.get("release_checksum"),
                "records": result.get("records") or [],
                "error_code": result.get("error_code"),
                "error": result.get("error"),
            }
        except Exception as exc:
            item = {"action_code": action_code, "success": False, "error_code": getattr(exc, "code", "ACTION_FAILED"), "error": str(exc)}
        all_ok = all_ok and item["success"]
        items.append(item)
    await ws_manager.emit(execution_id, {
        "type": "platform_actions",
        "device_id": device.get("id"),
        "actions": items,
        "dry_run": dry_run,
    })
    return {
        "success": all_ok,
        "actions": items,
        "commands": [item["command"] for item in items if item.get("command")],
        "output": json.dumps(items, ensure_ascii=False),
    }


def _merge_phase_results(command_result: dict | None, action_result: dict | None) -> dict:
    if command_result is None:
        return action_result or {"success": True, "commands": [], "output": ""}
    if action_result is None:
        return command_result
    return {
        "success": bool(command_result.get("success", False) and action_result.get("success", False)),
        "commands": (command_result.get("commands") or []) + (action_result.get("commands") or []),
        "actions": action_result.get("actions") or [],
        "output": "\n\n".join(item for item in (command_result.get("output"), action_result.get("output")) if item),
    }


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
        phases_encrypted, phases_json, raw_output_expires_at, _encrypted = protect_output(
            device_result.get('phases', {})
        )
        cleanup_expired_playbook_outputs(conn)
        conn.execute(
            '''INSERT INTO execution_device_results
               (id, execution_id, device_id, hostname, ip_address, status,
                error_message, phases_json, phases_encrypted, raw_output_expires_at,
                started_at, completed_at, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                 execution_id=excluded.execution_id, device_id=excluded.device_id,
                 hostname=excluded.hostname, ip_address=excluded.ip_address,
                 status=excluded.status, error_message=excluded.error_message,
                 phases_json=excluded.phases_json, phases_encrypted=excluded.phases_encrypted,
                 raw_output_expires_at=excluded.raw_output_expires_at,
                 started_at=excluded.started_at,
                 completed_at=excluded.completed_at, duration_ms=excluded.duration_ms''',
            (
                str(uuid.uuid4()), execution_id, device_id,
                device.get('hostname') or device_id,
                device.get('ip_address') or device.get('ip') or '',
                device_result.get('status', 'success'),
                _redact_execution_value(device_result.get('error', '')),
                phases_json,
                phases_encrypted,
                raw_output_expires_at,
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
    actor: dict | None = None,
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
        dd['username'] = creds.get('normal_username') or creds.get('username') or ''
        dd['password'] = creds.get('normal_password') or creds.get('password') or ''
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
            device_phases, rejected_legacy_steps = _bind_legacy_phase_commands(device, device_phases)
            if rejected_legacy_steps:
                overall_ok = False
                device_result["status"] = "error"
                device_result["error_code"] = "RAW_COMMAND_NOT_BOUND_TO_PLATFORM_RELEASE"
                device_result["error"] = "Bound devices may execute only published platform action_code steps"
                device_result["rejected_steps"] = rejected_legacy_steps[:32]
                await ws_manager.emit(execution_id, {
                    "type": "device_error",
                    "device_id": device_id,
                    "hostname": hostname,
                    "error": device_result["error"],
                    "error_code": device_result["error_code"],
                })
                await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                results[device_id] = device_result
                return
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
                pre_steps = select_controlled_steps(
                    device_phases.get('pre_check', []), variables=variables, device=device,
                )
                pre_cmds = _render_phase_commands(pre_steps, variables)
                pre_actions = _phase_action_steps(pre_steps)
                pre_notifications = _phase_notification_steps(pre_steps)
                if pre_cmds or pre_actions or pre_notifications:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "pre_check", "commands": pre_cmds,
                        "actions": [step["action_code"] for step in pre_actions],
                        "notifications": [
                            {"title": step["title"], "severity": step["severity"]}
                            for step in pre_notifications
                        ],
                    })
                    pre_command_output = await _exec_commands(service, device, pre_cmds, is_config=False) if pre_cmds else None
                    pre_action_output = await _execute_registry_actions(
                        execution_id, device, pre_actions, dry_run=dry_run, actor=actor,
                    ) if pre_actions else None
                    pre_output = _merge_phase_results(pre_command_output, pre_action_output)
                    pre_notification_output = await _execute_notification_steps(
                        execution_id, device, pre_notifications,
                        variables=variables, dry_run=dry_run, actor=actor,
                    ) if pre_notifications else None
                    pre_output = _attach_notification_result(pre_output, pre_notification_output)
                    device_result["phases"]["pre_check"] = pre_output
                    if not pre_output.get("success", True):
                        overall_ok = False   # pre_check errors → partial_failure, but execution continues
                    if not pre_output.get("notification_success", True):
                        overall_ok = False
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
                    if snap_cmd and not device.get('platform_profile_id'):
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
                exec_steps = select_controlled_steps(
                    device_phases.get('execute', []), variables=variables, device=device,
                )
                exec_cmds = _render_phase_commands(exec_steps, variables)
                exec_actions = _phase_action_steps(exec_steps)
                exec_notifications = _phase_notification_steps(exec_steps)
                if exec_cmds or exec_actions or exec_notifications:
                    if dry_run:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                            "actions": [step["action_code"] for step in exec_actions],
                            "notifications": [
                                {"title": step["title"], "severity": step["severity"]}
                                for step in exec_notifications
                            ],
                            "dry_run": True,
                        })
                        dry_run_commands = {
                            "commands": exec_cmds,
                            "output": "[DRY-RUN] Commands not sent to device",
                            "success": True,
                        }
                        dry_run_actions = await _execute_registry_actions(
                            execution_id, device, exec_actions, dry_run=True, actor=actor,
                        ) if exec_actions else None
                        exec_output = _merge_phase_results(dry_run_commands, dry_run_actions)
                        exec_notification_output = await _execute_notification_steps(
                            execution_id, device, exec_notifications,
                            variables=variables, dry_run=True, actor=actor,
                        ) if exec_notifications else None
                        device_result["phases"]["execute"] = _attach_notification_result(exec_output, exec_notification_output)
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": device_result["phases"]["execute"],
                            "dry_run": True,
                        })
                    else:
                        await ws_manager.emit(execution_id, {
                            "type": "phase_start", "device_id": device_id,
                            "phase": "execute", "commands": exec_cmds,
                            "actions": [step["action_code"] for step in exec_actions],
                            "notifications": [
                                {"title": step["title"], "severity": step["severity"]}
                                for step in exec_notifications
                            ],
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
                        command_output = await _exec_commands(service, device, exec_cmds, is_config=_needs_config) if exec_cmds else None
                        action_output = await _execute_registry_actions(
                            execution_id, device, exec_actions, dry_run=False, actor=actor,
                        ) if exec_actions else None
                        exec_output = _merge_phase_results(command_output, action_output)
                        exec_notification_output = await _execute_notification_steps(
                            execution_id, device, exec_notifications,
                            variables=variables, dry_run=False, actor=actor,
                        ) if exec_notifications else None
                        exec_output = _attach_notification_result(exec_output, exec_notification_output)
                        device_result["phases"]["execute"] = exec_output
                        if not exec_output.get("notification_success", True):
                            overall_ok = False
                        await ws_manager.emit(execution_id, {
                            "type": "phase_done", "device_id": device_id,
                            "phase": "execute", "output": exec_output,
                        })

                        # P0: Execute 失败 → 自动回滚
                        if not exec_output.get("success", True):
                            overall_ok = False
                            device_result["status"] = "failed"
                            await _do_rollback(execution_id, service, device, device_phases, variables, actor)
                            device_result["phases"]["rollback"] = {"triggered": True, "reason": "execute_failed"}
                            await _save_device_result_to_db(execution_id, device_id, device, device_result, started_at_iso)
                            results[device_id] = device_result
                            return

                # ──── PHASE 3: Post-Check ────
                post_steps = select_controlled_steps(
                    device_phases.get('post_check', []), variables=variables, device=device,
                )
                post_cmds = _render_phase_commands(post_steps, variables)
                post_actions = _phase_action_steps(post_steps)
                post_notifications = _phase_notification_steps(post_steps)
                if (post_cmds or post_actions or post_notifications) and not dry_run:
                    await ws_manager.emit(execution_id, {
                        "type": "phase_start", "device_id": device_id,
                        "phase": "post_check", "commands": post_cmds,
                        "actions": [step["action_code"] for step in post_actions],
                        "notifications": [
                            {"title": step["title"], "severity": step["severity"]}
                            for step in post_notifications
                        ],
                    })
                    post_command_output = await _exec_commands(service, device, post_cmds, is_config=False) if post_cmds else None
                    post_action_output = await _execute_registry_actions(
                        execution_id, device, post_actions, dry_run=False, actor=actor,
                    ) if post_actions else None
                    post_output = _merge_phase_results(post_command_output, post_action_output)
                    post_notification_output = await _execute_notification_steps(
                        execution_id, device, post_notifications,
                        variables=variables, dry_run=False, actor=actor,
                    ) if post_notifications else None
                    post_output = _attach_notification_result(post_output, post_notification_output)
                    device_result["phases"]["post_check"] = post_output
                    if not post_output.get("notification_success", True):
                        overall_ok = False
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
                        await _do_rollback(execution_id, service, device, device_phases, variables, actor)
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
    results_encrypted, results_json, raw_output_expires_at, _encrypted = protect_output(results)
    cleanup_expired_playbook_outputs(conn2)
    conn2.execute(
        """UPDATE playbook_executions
           SET status=?, results_json=?, results_encrypted=?, raw_output_expires_at=?, updated_at=?,
               total_devices=?, success_count=?, failed_count=?, partial_count=?
           WHERE id=?""",
        (final_status, results_json, results_encrypted, raw_output_expires_at, datetime.now().isoformat(),
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
                    await _do_rollback(execution_id, svc, dev, dev_phases, variables, actor)

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
            if is_config and all_ok:
                from core.cmd_cache import clear_cmd_cache
                clear_cmd_cache(device.get('ip_address') or device.get('hostname') or '')
            return {"success": all_ok, "output": "\n\n".join(output_lines), "commands": commands}
        except Exception as e:
            return {"success": False, "output": str(e), "commands": commands, "error": str(e)}

    return await loop.run_in_executor(None, _run)


async def _do_rollback(execution_id: str, service, device: dict, phases: dict, variables: dict, actor: dict | None = None):
    """Execute rollback phase and notify via WebSocket."""
    rollback_steps = select_controlled_steps(
        phases.get('rollback', []), variables=variables, device=device,
    )
    rollback_cmds = _render_phase_commands(rollback_steps, variables)
    rollback_actions = _phase_action_steps(rollback_steps)
    rollback_notifications = _phase_notification_steps(rollback_steps)
    hostname = device.get('hostname', device.get('id', ''))
    if not rollback_cmds and not rollback_actions and not rollback_notifications:
        await ws_manager.emit(execution_id, {
            "type": "rollback", "device_id": device['id'],
            "hostname": hostname, "status": "no_rollback_defined",
        })
        return

    await ws_manager.emit(execution_id, {
        "type": "rollback_start", "device_id": device['id'],
        "hostname": hostname, "commands": rollback_cmds,
        "actions": [step["action_code"] for step in rollback_actions],
        "notifications": [
            {"title": step["title"], "severity": step["severity"]}
            for step in rollback_notifications
        ],
    })
    command_result = await _exec_commands(service, device, rollback_cmds, is_config=True) if rollback_cmds else None
    action_result = await _execute_registry_actions(
        execution_id, device, rollback_actions, dry_run=False, actor=actor,
    ) if rollback_actions else None
    result = _merge_phase_results(command_result, action_result)
    notification_result = await _execute_notification_steps(
        execution_id, device, rollback_notifications,
        variables=variables, dry_run=False, actor=actor,
    ) if rollback_notifications else None
    result = _attach_notification_result(result, notification_result)
    await ws_manager.emit(execution_id, {
        "type": "rollback_done", "device_id": device['id'],
        "hostname": hostname, "output": result,
    })
