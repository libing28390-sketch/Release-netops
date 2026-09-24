"""Automatic synchronization of monitoring collector targets from CMDB.

Provides automatic compile and publish for monitoring collectors whenever CMDB
devices or physical assets change, on system startup, and via scheduled sweeps,
eliminating the need for manual operator intervention.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from database import get_db_connection

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_debounce_timer: threading.Timer | None = None
_timer_lock = threading.Lock()


def sync_all_monitoring_collectors(user: Any = None) -> dict[str, Any]:
    """Compile and publish latest targets for all enabled collectors.
    
    Extracts live devices and server assets from CMDB, generates updated
    vmagent/snmp_targets, and immediately publishes them to the runtime.
    """
    if not _sync_lock.acquire(blocking=False):
        logger.info("[CollectorAutoSync] Sync already in progress, skipping concurrent run")
        return {"status": "SKIPPED", "reason": "in_progress"}

    try:
        from api.monitoring_v1 import compile_collector, publish_collector

        conn = get_db_connection()
        try:
            collector_rows = conn.execute(
                "SELECT id FROM monitoring_collectors WHERE enabled = 1"
            ).fetchall()
            collector_ids = [
                str(item["id"] if hasattr(item, "keys") else item[0])
                for item in collector_rows
            ]
        finally:
            conn.close()

        if not collector_ids:
            logger.info("[CollectorAutoSync] No enabled collectors found")
            return {"status": "NO_COLLECTORS", "results": []}

        actor = user or {"id": "system-auto-sync", "role": "Administrator", "username": "system"}
        results = []
        for cid in collector_ids:
            try:
                compiled = compile_collector(cid, _user=actor)
                if compiled.get("status") == "UNCHANGED" and compiled.get("already_applied"):
                    published = compiled
                else:
                    published = publish_collector(cid, _user=actor)
                results.append({
                    "collector_id": cid,
                    "config_version": published.get("config_version"),
                    "status": published.get("status") or "APPLIED",
                    "assignment_count": compiled.get("assignment_count", 0),
                })
                logger.info(
                    f"[CollectorAutoSync] Successfully synced collector {cid} "
                    f"v{published.get('config_version')} ({compiled.get('assignment_count', 0)} assignments)"
                )
            except Exception as exc:
                logger.warning(f"[CollectorAutoSync] Failed to sync collector {cid}: {exc}", exc_info=True)
                results.append({
                    "collector_id": cid,
                    "status": "FAILED",
                    "error": str(exc),
                })
        return {"status": "SUCCESS", "results": results}
    finally:
        _sync_lock.release()


def _debounced_worker() -> None:
    try:
        result = sync_all_monitoring_collectors()
        if result.get("status") == "SKIPPED" and result.get("reason") == "in_progress":
            # Preserve status-triggered updates when a different collector
            # compile/publish is still running as the debounce timer fires.
            trigger_async_monitoring_sync(delay_seconds=5.0)
    except Exception as exc:
        logger.error(f"[CollectorAutoSync] Debounced worker error: {exc}", exc_info=True)


def trigger_async_monitoring_sync(delay_seconds: float = 2.0) -> None:
    """Schedule a debounced asynchronous monitoring targets sync.
    
    Consecutive calls within delay_seconds are merged into a single run.
    Safe to call from HTTP request threads.
    """
    import os
    import sys
    if os.environ.get("ENVIRONMENT") == "test" or "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        return

    global _debounce_timer
    with _timer_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(delay_seconds, _debounced_worker)
        _debounce_timer.daemon = True
        _debounce_timer.start()
        logger.debug(f"[CollectorAutoSync] Scheduled debounced sync in {delay_seconds}s")
