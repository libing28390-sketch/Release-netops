"""Durable workers for PostgreSQL-backed V2 locator runs."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import settings
from services.ip_locator_task_service import (
    claim_locator_run,
    claim_locator_runs,
    renew_locator_run_lease,
    save_locator_run_result,
)
from services.ip_locator_trace_service import add_legacy_compatibility, trace_ip

logger = logging.getLogger(__name__)


def _worker_id() -> str:
    return f"ip-locator:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _run_claimed(run: dict[str, Any]) -> dict[str, Any] | None:
    run_id = str(run.get("id") or "")
    worker = str(run.get("claim_lease_owner") or "")
    token = str(run.get("claim_lease_token") or "")
    if not run_id or not worker or not token:
        return None
    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()

    def heartbeat() -> None:
        while not heartbeat_stop.wait(10):
            try:
                renewed = renew_locator_run_lease(
                    run_id,
                    worker_id=worker,
                    lease_token=token,
                    lease_seconds=30,
                )
            except Exception as exc:
                logger.warning("[IPLocatorV2] run lease heartbeat failed (%s)", type(exc).__name__)
                lease_lost.set()
                return
            if not renewed:
                lease_lost.set()
                return

    heartbeat_thread = threading.Thread(target=heartbeat, name="ip-locator-run-lease", daemon=True)
    heartbeat_thread.start()
    try:
        now = _utc_now()
        try:
            deadline = datetime.fromisoformat(str(run.get("deadline_at") or "").replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            remaining = max(1, int((deadline.astimezone(timezone.utc) - now).total_seconds()))
        except (TypeError, ValueError):
            remaining = max(1, int(getattr(settings, "IP_LOCATOR_TASK_DEADLINE_SECONDS", 180)))
        result = trace_ip(
            str(run.get("target_ip") or ""),
            durable_run_id=run_id,
            run_owner_id=str(run.get("owner_id") or ""),
            cancel_check=lease_lost.is_set,
            tenant_id=str(run.get("tenant_id") or "tenant-default"),
            start_device_id=str(run.get("start_device_id") or ""),
            site_id=str(run.get("site_id") or ""),
            network_domain_id=str(run.get("network_domain_id") or ""),
            vrf=str(run.get("vrf_name") or "default"),
            force_refresh=bool(run.get("force_refresh")),
            authorized_device_ids=list((run.get("stats") or {}).get("authorized_device_ids") or []),
            deadline_seconds=remaining,
        )
        if lease_lost.is_set():
            logger.warning("[IPLocatorV2] run %s lost its lease; result will not be committed", run_id)
            return None
        result = add_legacy_compatibility(result)
        status = str(result.get("status") or "failed")
        if status not in {"completed", "partial", "failed", "needs_context"}:
            status = "failed"
        generated_at = _utc_now()
        fresh_until = generated_at + timedelta(
            seconds=int(getattr(settings, "IP_LOCATOR_RESULT_FRESH_SECONDS", 120))
        )
        evidence_at = result.get("evidence_collected_at")
        if evidence_at:
            try:
                parsed = datetime.fromisoformat(str(evidence_at).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                evidence_deadline = parsed.astimezone(timezone.utc) + timedelta(
                    seconds=int(getattr(settings, "IP_LOCATOR_RESULT_FRESH_SECONDS", 120))
                )
                fresh_until = max(generated_at, min(fresh_until, evidence_deadline))
            except (TypeError, ValueError):
                pass
        return save_locator_run_result(
            run_id,
            result=result,
            status=status,
            owner_id=None,
            stats={
                "conclusion": result.get("conclusion"),
                "queried_devices": result.get("queried_devices") or {},
                "coverage_gaps": result.get("coverage_gaps") or [],
            },
            error_code=(result.get("errors") or [""])[0] if status == "failed" else "",
            error_message="IP 定位执行失败" if status == "failed" else "",
            generated_at=generated_at,
            fresh_until=fresh_until,
            retain_until=generated_at + timedelta(days=30),
            lease_owner=worker,
            lease_token=token,
        )
    except Exception as exc:
        logger.error("[IPLocatorV2] run %s failed: %s", run_id, type(exc).__name__)
        try:
            return save_locator_run_result(
                run_id,
                result={},
                status="failed",
                owner_id=None,
                error_code="TRACE_FAILED",
                error_message="IP 定位执行失败",
                lease_owner=worker,
                lease_token=token,
            )
        except Exception as persist_error:
            logger.error(
                "[IPLocatorV2] failed to persist run failure (%s)",
                type(persist_error).__name__,
            )
            return None
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)


def run_locator_run_by_id(run_id: str) -> None:
    """Wake a queued run immediately; PostgreSQL still arbitrates ownership."""
    worker = _worker_id()
    claimed = claim_locator_run(
        run_id,
        worker_id=worker,
        max_active_runs=max(1, int(getattr(settings, "IP_LOCATOR_CLI_GLOBAL_CONCURRENCY", 5))),
        lease_seconds=30,
    )
    if claimed:
        _run_claimed(claimed)


async def process_pending_locator_runs() -> int:
    """Claim a bounded batch so runs stranded by a restart are recovered."""
    capacity = max(1, int(getattr(settings, "IP_LOCATOR_CLI_GLOBAL_CONCURRENCY", 5)))
    worker = _worker_id()
    claimed = await asyncio.to_thread(
        claim_locator_runs,
        worker_id=worker,
        limit=capacity,
        max_active_runs=capacity,
        lease_seconds=30,
    )
    if not claimed:
        return 0
    await asyncio.gather(*(asyncio.to_thread(_run_claimed, run) for run in claimed))
    return len(claimed)


__all__ = ["process_pending_locator_runs", "run_locator_run_by_id"]
