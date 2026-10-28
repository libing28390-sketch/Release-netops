"""Shared PostgreSQL query tasks for read-only IP locator CLI operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import hashlib
import inspect
import logging
import os
import socket
import threading
import time
import uuid
from typing import Any, Callable, Mapping

from core.config import settings
from services.ip_locator_session_pool import get_ip_locator_session_pool

logger = logging.getLogger(__name__)

_CLI_TASK_LEASE_SECONDS = 90
_CLI_TASK_HEARTBEAT_SECONDS = 10
_CLI_TASK_COMPLETED_SHARE_SECONDS = 2
_CLI_TASK_MAX_RESULT_BYTES = 2_000_000


class LocatorCLIQueryError(TimeoutError):
    """A shared, read-only locator query failed or missed its deadline."""


class LocatorCLIQueryCancelled(LocatorCLIQueryError):
    """The parent trace was cancelled while awaiting a shared CLI query."""


@dataclass(frozen=True)
class LocatorCLIResult:
    value: Any
    status: dict[str, Any]
    collected_at: str
    task_id: str
    source: str = "ssh_cli"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _worker_id() -> str:
    return f"ip-locator-query:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _json_value(value: Any) -> Any:
    """Convert a supported CLI result to bounded JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _fallback_operation_version(
    kind: str,
    operation: str,
    device: Mapping[str, Any],
    target: Mapping[str, Any],
    callback: Callable[[], Any],
) -> str:
    """Derive a non-empty task fence when a legacy caller omits one."""
    try:
        implementation = inspect.getsource(callback)
    except (OSError, TypeError):
        code = getattr(callback, "__code__", None)
        implementation = repr((getattr(callback, "__module__", ""), getattr(callback, "__qualname__", ""), getattr(code, "co_code", b"").hex(), getattr(code, "co_consts", ())))
    material = {
        "kind": kind,
        "operation": str(operation or "").lower(),
        "platform": str(device.get("platform") or target.get("platform") or "").lower(),
        "profile_id": str(device.get("platform_profile_id") or target.get("platform_profile_id") or target.get("profile_id") or ""),
        "target_mode": str(target.get("snapshot") or "targeted"),
        "command_digest": hashlib.sha256(str(target.get("command") or "").encode("utf-8")).hexdigest(),
        "implementation": implementation,
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"locator-{kind}:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _check_cancel(context: Mapping[str, Any]) -> None:
    check = context.get("cancel_check")
    if callable(check) and check():
        raise LocatorCLIQueryCancelled("locator run is no longer active")


def _lease_heartbeat(
    task_id: str,
    worker_id: str,
    lease_token: str,
    stop: threading.Event,
    lost: threading.Event,
) -> None:
    from services.ip_locator_task_service import renew_locator_task

    while not stop.wait(_CLI_TASK_HEARTBEAT_SECONDS):
        try:
            if not renew_locator_task(
                task_id,
                worker_id=worker_id,
                lease_token=lease_token,
                lease_seconds=_CLI_TASK_LEASE_SECONDS,
            ):
                lost.set()
                return
        except Exception as exc:
            logger.warning("[IPLocator] query-task heartbeat failed (%s)", type(exc).__name__)
            lost.set()
            return


def run_locator_cli_query(
    device: dict[str, Any],
    operation: str,
    callback: Callable[[], Any],
    *,
    task_context: Mapping[str, Any],
    wait_seconds: int,
) -> LocatorCLIResult:
    """Enqueue/share one scoped query, then claim and execute it under leases.

    Claims are targeted to the query created by this trace. Concurrent traces
    that enqueue the same operation share its active PostgreSQL lease and read
    the same collected timestamp/result; no database transaction spans SSH.
    """
    from services.ip_locator_task_service import (
        LocatorTaskError,
        claim_locator_task,
        complete_locator_task,
        enqueue_locator_task,
        get_locator_task,
    )

    selected_device_id = str(device.get("id") or "").strip()
    if not selected_device_id:
        raise LocatorCLIQueryError("managed device identity is required for locator CLI")
    wait_budget = max(1, int(wait_seconds))
    deadline = time.monotonic() + wait_budget
    force_refresh = bool(task_context.get("force_refresh"))
    run_id = str(task_context.get("durable_run_id") or "").strip()
    run_owner_id = str(task_context.get("run_owner_id") or "").strip()
    query_target = dict(task_context.get("target") or {})
    query_target.setdefault("platform", str(device.get("platform") or ""))
    query_target.setdefault("platform_profile_id", str(device.get("platform_profile_id") or ""))
    raw_vlan = task_context.get("vlan_id")
    try:
        selected_vlan = int(raw_vlan) if raw_vlan not in (None, "") else None
        if selected_vlan is not None and not 0 <= selected_vlan <= 4_294_967_295:
            selected_vlan = None
    except (TypeError, ValueError):
        selected_vlan = None
    enqueue_kwargs = {
        "run_id": run_id or None,
        "owner_id": run_owner_id or None,
        "relation_role": f"cli:{str(operation or '').lower()}",
        "required": False,
        "operation": operation,
        "mode": "force_refresh" if force_refresh else "normal",
        "deployment_id": str(
            task_context.get("deployment_id")
            or getattr(settings, "IP_LOCATOR_REDIS_NAMESPACE", "nexora:production:locator:v1")
        ),
        "tenant_id": str(task_context.get("tenant_id") or "tenant-default"),
        "scope_hash": str(task_context.get("scope_hash") or ""),
        "network_domain_id": str(task_context.get("network_domain_id") or ""),
        "site_id": str(task_context.get("site_id") or ""),
        "vrf_name": str(task_context.get("vrf_name") or "default"),
        "start_device_id": str(task_context.get("start_device_id") or ""),
        "device_id": selected_device_id,
        "target_ip": str(task_context.get("target_ip") or ""),
        "target_mac": str(task_context.get("target_mac") or ""),
        "bridge_domain": str(task_context.get("bridge_domain") or ""),
        "vlan_id": selected_vlan,
        "target": query_target,
        "authorization_scope_hash": str(task_context.get("authorization_scope_hash") or ""),
        "action_version": str(task_context.get("action_version") or "").strip()
        or _fallback_operation_version("action", operation, device, query_target, callback),
        "parser_version": str(task_context.get("parser_version") or "").strip()
        or _fallback_operation_version("parser", operation, device, query_target, callback),
        "deadline_seconds": wait_budget,
        "payload": {
            "platform": str(device.get("platform") or ""),
            "command": str(query_target.get("command") or ""),
            "target": query_target,
        },
        # A completed raw output is shared only briefly. Afterwards a cache
        # miss must issue a new CLI command instead of relabeling old output.
        "requeue_completed_after_seconds": _CLI_TASK_COMPLETED_SHARE_SECONDS,
    }
    try:
        task = enqueue_locator_task(**enqueue_kwargs)
    except Exception as exc:
        logger.warning("[IPLocator] query-task enqueue failed (%s)", type(exc).__name__)
        raise LocatorCLIQueryError("unable to queue locator CLI query") from exc
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise LocatorCLIQueryError("locator query task has no identifier")

    worker_id = _worker_id()

    def execute_claimed(claimed: Mapping[str, Any]) -> LocatorCLIResult:
        task_lease_token = str(claimed.get("lease_token") or "")
        if not task_lease_token:
            raise LocatorTaskError("claimed locator task is missing its ownership token")
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        heartbeat_thread = threading.Thread(
            target=_lease_heartbeat,
            args=(task_id, worker_id, task_lease_token, heartbeat_stop, lease_lost),
            name="ip-locator-query-lease",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            _check_cancel(task_context)
            remaining = max(1, int(deadline - time.monotonic()))
            output = get_ip_locator_session_pool().run(
                device,
                callback,
                task_id=task_id,
                run_id=run_id,
                wait_seconds=remaining,
            )
            _check_cancel(task_context)
            if lease_lost.is_set():
                raise LocatorCLIQueryError("locator CLI query lease was lost")
            collected_at = _utc_now_iso()
            status = getattr(output, "status", {}) or {}
            safe_status = dict(status) if isinstance(status, Mapping) else {}
            payload = {
                "value": _json_value(output),
                "status": _json_value(safe_status),
                "collected_at": collected_at,
                "source": "ssh_cli",
            }
            encoded_size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if encoded_size > _CLI_TASK_MAX_RESULT_BYTES:
                raise LocatorCLIQueryError("locator CLI output exceeds the bounded task result size")
            completed = complete_locator_task(
                task_id,
                worker_id=worker_id,
                lease_token=task_lease_token,
                success=True,
                result=payload,
            )
            if completed is None or str(completed.get("status") or "") != "succeeded":
                raise LocatorCLIQueryError("locator CLI task was cancelled or fenced before completion")
            return LocatorCLIResult(
                value=payload["value"],
                status=safe_status,
                collected_at=collected_at,
                task_id=task_id,
                source="ssh_cli",
            )
        except Exception as exc:
            try:
                complete_locator_task(
                    task_id,
                    worker_id=worker_id,
                    lease_token=task_lease_token,
                    success=False,
                    error_code=f"{type(exc).__name__}"[:80],
                    error_message="只读设备查询失败",
                )
            except Exception as persist_error:
                logger.warning("[IPLocator] query-task failure persist failed (%s)", type(persist_error).__name__)
            raise
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)

    while time.monotonic() < deadline:
        _check_cancel(task_context)
        try:
            current = get_locator_task(task_id)
        except Exception as exc:
            logger.warning("[IPLocator] shared query result read failed (%s)", type(exc).__name__)
            raise LocatorCLIQueryError("unable to read shared locator CLI result") from exc
        if current is None:
            raise LocatorCLIQueryError("shared locator CLI task disappeared")
        status = str(current.get("status") or "")
        if status == "succeeded":
            try:
                result_payload = current.get("result")
                if isinstance(result_payload, dict) and "value" in result_payload:
                    return LocatorCLIResult(
                        value=result_payload.get("value"),
                        status=(
                            result_payload.get("status")
                            if isinstance(result_payload.get("status"), dict) else {}
                        ),
                        collected_at=str(
                            result_payload.get("collected_at")
                            or current.get("completed_at")
                            or _utc_now_iso()
                        ),
                        task_id=task_id,
                        source=str(result_payload.get("source") or "shared_cli_task"),
                    )
                raise LocatorCLIQueryError("shared CLI result has expired; retry the locator query")
            except LocatorCLIQueryError:
                # A janitor may have scrubbed the short-lived raw output at
                # the deadline edge. Requeue the same scoped key once the
                # original row is no longer reusable.
                task = enqueue_locator_task(
                    **{
                        **enqueue_kwargs,
                        "force_requeue": True,
                        "requeue_completed_after_seconds": None,
                    }
                )
                task_id = str(task.get("id") or task_id)
                continue
        if status in {"failed", "cancelled", "expired"}:
            raise LocatorCLIQueryError("shared locator CLI task did not complete successfully")

        lease_until = current.get("lease_until")
        should_claim = status == "pending"
        lease_seconds_remaining: float | None = None
        if status == "running" and lease_until:
            try:
                lease_due = datetime.fromisoformat(str(lease_until).replace("Z", "+00:00"))
                if lease_due.tzinfo is None:
                    lease_due = lease_due.replace(tzinfo=timezone.utc)
                lease_seconds_remaining = lease_due.timestamp() - time.time()
                should_claim = lease_seconds_remaining <= 0
            except (TypeError, ValueError):
                should_claim = True
        if should_claim:
            try:
                claimed = claim_locator_task(
                    worker_id=worker_id,
                    task_id=task_id,
                    lease_seconds=_CLI_TASK_LEASE_SECONDS,
                )
            except Exception as exc:
                logger.warning("[IPLocator] query-task claim failed (%s)", type(exc).__name__)
                raise LocatorCLIQueryError("unable to claim locator CLI query") from exc
            if claimed is not None:
                return execute_claimed(claimed)
            time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))
        else:
            retry_delay = 0.5
            if status == "running" and lease_seconds_remaining is not None:
                retry_delay = min(1.0, max(0.2, lease_seconds_remaining))
            time.sleep(min(retry_delay, max(0.01, deadline - time.monotonic())))

    raise LocatorCLIQueryError("timed out waiting for shared locator CLI task")


__all__ = [
    "LocatorCLIQueryCancelled",
    "LocatorCLIQueryError",
    "LocatorCLIResult",
    "run_locator_cli_query",
]
