"""PG outbox consumer for Redis result-cache invalidation."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from services.ip_locator_cache_service import get_locator_cache
from services.ip_locator_task_service import (
    claim_locator_invalidation,
    complete_locator_invalidation,
)

logger = logging.getLogger(__name__)


def _invalidation_prefixes(cache: Any, event: dict[str, Any]) -> list[str]:
    scope_hash = str(event.get("scope_hash") or "").strip()
    if not scope_hash:
        raise ValueError("invalidation scope is missing")
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    kind = str(payload.get("observation_kind") or "").strip().lower()
    target_ip = str(payload.get("target_ip") or "").strip()
    if kind in {"route", "arp", "path"} and target_ip:
        exact = cache.build_key("result", scope_hash, target_ip)
        result_prefix = f"{exact}:"
    else:
        # MAC, neighbor, interface and topology changes can affect multiple IP
        # results within the same authorization scope; keep invalidation scoped.
        result_prefix = f"{cache.build_key('result', scope_hash)}:"

    # Fact projections carry observation-generation and pipeline-version
    # fences, and every read validates those fences against PostgreSQL. Keep
    # them in Redis and let the read path reject stale generations: deleting a
    # whole fact prefix here can race with the writer's post-commit SET and
    # erase the just-published current generation. The result cache is removed
    # eagerly; stale fact keys are harmless and are overwritten on re-read.
    return [result_prefix]


def process_pending_locator_invalidations(*, limit: int = 50) -> int:
    """Consume a bounded batch, retrying when Redis cannot be reached."""
    worker_id = f"locator-invalidation:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    processed = 0
    for _ in range(max(1, min(500, int(limit)))):
        event = claim_locator_invalidation(worker_id=worker_id)
        if not event:
            break
        event_id = str(event.get("id") or "")
        token = str(event.get("lease_token") or "")
        success = False
        error_kind = ""
        retry_at = None
        try:
            cache = get_locator_cache()
            configured = (
                str(getattr(cache, "backend", ""))
                == "redis"
                and bool(str(getattr(cache.settings, "REDIS_URL", "") or "").strip())
                and bool(str(getattr(cache, "namespace", "") or "").strip())
            )
            if configured:
                for prefix in _invalidation_prefixes(cache, event):
                    deleted = cache.delete_prefix(prefix, batch_size=100)
                    if deleted is None:
                        raise ConnectionError("redis_invalidation_unavailable")
            success = True
        except Exception as exc:
            error_kind = type(exc).__name__
            attempts = max(1, int(event.get("attempts") or 1))
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 2 ** min(attempts, 8)))
            logger.warning(
                "[IPLocatorV2] result invalidation deferred (%s)",
                error_kind,
            )
        if complete_locator_invalidation(
            event_id,
            worker_id=worker_id,
            lease_token=token,
            success=success,
            error_message=error_kind,
            retry_at=retry_at,
        ):
            processed += 1
    return processed


__all__ = ["process_pending_locator_invalidations"]
