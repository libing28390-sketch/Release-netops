"""Celery execution boundary for alert notification outbox deliveries."""

from __future__ import annotations

import logging
import uuid

from celery.exceptions import Reject

from celery_app import TASK_NAME, app


logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name=TASK_NAME,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    acks_on_failure_or_timeout=False,
)
def deliver_alert_notification(
    _task,
    delivery_id: str,
    dispatch_generation: int,
) -> None:
    """Process one generation-fenced delivery using a per-execution owner."""
    if (
        not isinstance(delivery_id, str)
        or not delivery_id.strip()
        or not isinstance(dispatch_generation, int)
        or isinstance(dispatch_generation, bool)
        or dispatch_generation < 1
    ):
        raise Reject("alert_delivery_invalid_arguments", requeue=False)

    try:
        from services.monitoring_notification_outbox_service import (
            process_alert_delivery_by_generation,
        )

        process_alert_delivery_by_generation(
            delivery_id=delivery_id,
            dispatch_generation=dispatch_generation,
            worker_id=str(uuid.uuid4()),
        )
    except Exception as exc:
        # Celery rejects failed late-acked messages without broker requeue.
        # Recovery stays in PostgreSQL: the relay republishes an unclaimed
        # pending row with bounded backoff, or reclaims an expired DB lease.
        logger.error(
            "Alert delivery task failed in the outbox processor "
            "(delivery_id=%s, generation=%s, error_type=%s)",
            delivery_id,
            dispatch_generation,
            type(exc).__name__,
        )
        raise
