"""Celery application for PostgreSQL-backed alert notification deliveries.

This module is intentionally independent of ``main`` so workers do not start
the FastAPI application or its lifespan when importing the task app.
"""

from __future__ import annotations

import os
from functools import cached_property

from celery import Celery
from celery.apps.worker import Worker as CeleryWorker
from kombu import Queue


BROKER_ENV_VAR = "ALERT_NOTIFICATION_BROKER_URL"
TASK_NAME = "monitoring.alerts.deliver"
ALERT_NOTIFY_CRITICAL_QUEUE = "alert_notify_critical"
ALERT_NOTIFY_NORMAL_QUEUE = "alert_notify_normal"


def _configured_broker_url() -> str | None:
    value = os.environ.get(BROKER_ENV_VAR, "").strip()
    return value or None


_broker_url = _configured_broker_url()


def _require_configured_broker() -> None:
    if not _broker_url:
        raise RuntimeError(
            f"{BROKER_ENV_VAR} must be configured before starting an alert notification worker"
        )


class _AlertNotificationWorker(CeleryWorker):
    """Enforce the broker contract before Celery starts worker bootsteps."""

    def __init__(self, app=None, hostname=None, **kwargs) -> None:
        worker_app = app or getattr(type(self), "app", None)
        _require_configured_broker()
        super().__init__(app=worker_app, hostname=hostname, **kwargs)


class _AlertNotificationCelery(Celery):
    @cached_property
    def Worker(self):
        return self.subclass_with_self(_AlertNotificationWorker)


# Passing None keeps import and task inspection safe in API-only environments.
# A worker is separately guarded below so Celery's implicit localhost AMQP
# fallback can never be mistaken for a configured production broker.
app = _AlertNotificationCelery(
    "netops_alert_notifications",
    broker=_broker_url,
    include=["tasks.alert_notification_tasks"],
)

app.conf.update(
    broker_url=_broker_url,
    accept_content=("json",),
    task_serializer="json",
    result_serializer="json",
    event_serializer="json",
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_default_queue=ALERT_NOTIFY_NORMAL_QUEUE,
    task_default_exchange_type="direct",
    task_default_routing_key=ALERT_NOTIFY_NORMAL_QUEUE,
    task_queues=(
        Queue(ALERT_NOTIFY_CRITICAL_QUEUE),
        Queue(ALERT_NOTIFY_NORMAL_QUEUE),
    ),
    task_routes={TASK_NAME: {"queue": ALERT_NOTIFY_NORMAL_QUEUE}},
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": 120,
        "global_keyprefix": "nexora_alert_",
    },
    worker_enable_remote_control=False,
    worker_send_task_events=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Failed late-acked task messages are rejected without broker requeue.
    # The PostgreSQL relay republishes unclaimed outbox rows with bounded
    # backoff; expired claimed rows are recovered through their DB lease.
    task_acks_on_failure_or_timeout=False,
)
