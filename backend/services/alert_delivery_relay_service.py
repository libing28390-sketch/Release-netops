"""Publish PostgreSQL outbox generations to the isolated Celery broker."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from celery_app import ALERT_NOTIFY_CRITICAL_QUEUE, ALERT_NOTIFY_NORMAL_QUEUE, TASK_NAME, app
from database import get_db_connection


logger = logging.getLogger(__name__)
_PUBLISH_LEASE_SECONDS = 30
_PUBLISHED_RETRY_INTERVALS_SECONDS = (60, 120, 240, 480, 960, 1800)
_PUBLISHED_RETRY_MAX_SECONDS = 3600
_MAX_CLAIM_LIMIT = 100


def _claim_ready_deliveries(*, limit: int, relay_id: str) -> list[dict[str, Any]]:
    normal_quota = max(1, limit // 4) if limit >= 2 else 0
    critical_quota = limit - normal_quota
    connection = get_db_connection()
    try:
        rows = connection.execute(
            """
            WITH normal_candidates AS (
                SELECT delivery.id, 'normal'::text AS priority
                  FROM alert_delivery_outbox AS delivery
                 WHERE delivery.status = 'pending'
                   AND delivery.available_at <= clock_timestamp()
                   AND delivery.publish_available_at <= clock_timestamp()
                   AND (delivery.publish_lease_until IS NULL OR delivery.publish_lease_until <= clock_timestamp())
                   AND (
                       delivery.published_generation < delivery.dispatch_generation
                       OR delivery.published_at IS NULL
                       OR (delivery.published_at <= clock_timestamp() - (
                               CASE
                                   WHEN delivery.publish_redrive_count <= 0 THEN ?
                                   WHEN delivery.publish_redrive_count = 1 THEN ?
                                   WHEN delivery.publish_redrive_count = 2 THEN ?
                                   WHEN delivery.publish_redrive_count = 3 THEN ?
                                   WHEN delivery.publish_redrive_count = 4 THEN ?
                                   WHEN delivery.publish_redrive_count = 5 THEN ?
                                   ELSE ?
                               END * INTERVAL '1 second'
                           ) AND delivery.attempts = 0)
                   )
                   AND NOT (
                       delivery.priority = 'critical'
                       OR lower(COALESCE(delivery.payload->>'severity', ''))
                          IN ('critical', 'major', 'high', 'p1', 'emergency')
                   )
                 ORDER BY delivery.publish_available_at, delivery.created_at, delivery.id
                 LIMIT ?
                 FOR UPDATE OF delivery SKIP LOCKED
            ), critical_candidates AS (
                SELECT delivery.id, 'critical'::text AS priority
                  FROM alert_delivery_outbox AS delivery
                 WHERE delivery.status = 'pending'
                   AND delivery.available_at <= clock_timestamp()
                   AND delivery.publish_available_at <= clock_timestamp()
                   AND (delivery.publish_lease_until IS NULL OR delivery.publish_lease_until <= clock_timestamp())
                   AND (
                       delivery.published_generation < delivery.dispatch_generation
                       OR delivery.published_at IS NULL
                       OR (delivery.published_at <= clock_timestamp() - (
                               CASE
                                   WHEN delivery.publish_redrive_count <= 0 THEN ?
                                   WHEN delivery.publish_redrive_count = 1 THEN ?
                                   WHEN delivery.publish_redrive_count = 2 THEN ?
                                   WHEN delivery.publish_redrive_count = 3 THEN ?
                                   WHEN delivery.publish_redrive_count = 4 THEN ?
                                   WHEN delivery.publish_redrive_count = 5 THEN ?
                                   ELSE ?
                               END * INTERVAL '1 second'
                           ) AND delivery.attempts = 0)
                   )
                   AND (
                       delivery.priority = 'critical'
                       OR lower(COALESCE(delivery.payload->>'severity', ''))
                          IN ('critical', 'major', 'high', 'p1', 'emergency')
                   )
                 ORDER BY delivery.publish_available_at, delivery.created_at, delivery.id
                 LIMIT ?
                 FOR UPDATE OF delivery SKIP LOCKED
            ), quota_candidates AS MATERIALIZED (
                SELECT id, priority FROM normal_candidates
                UNION ALL
                SELECT id, priority FROM critical_candidates
            ), overflow_candidates AS (
                SELECT delivery.id,
                       CASE
                           WHEN delivery.priority = 'critical' OR lower(COALESCE(delivery.payload->>'severity', ''))
                                IN ('critical', 'major', 'high', 'p1', 'emergency')
                           THEN 'critical' ELSE 'normal'
                       END AS priority
                  FROM alert_delivery_outbox AS delivery
                 WHERE delivery.status = 'pending'
                   AND delivery.available_at <= clock_timestamp()
                   AND delivery.publish_available_at <= clock_timestamp()
                   AND (delivery.publish_lease_until IS NULL OR delivery.publish_lease_until <= clock_timestamp())
                   AND (
                       delivery.published_generation < delivery.dispatch_generation
                       OR delivery.published_at IS NULL
                       OR (delivery.published_at <= clock_timestamp() - (
                               CASE
                                   WHEN delivery.publish_redrive_count <= 0 THEN ?
                                   WHEN delivery.publish_redrive_count = 1 THEN ?
                                   WHEN delivery.publish_redrive_count = 2 THEN ?
                                   WHEN delivery.publish_redrive_count = 3 THEN ?
                                   WHEN delivery.publish_redrive_count = 4 THEN ?
                                   WHEN delivery.publish_redrive_count = 5 THEN ?
                                   ELSE ?
                               END * INTERVAL '1 second'
                           ) AND delivery.attempts = 0)
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM quota_candidates AS quota WHERE quota.id = delivery.id
                   )
                 ORDER BY
                       CASE
                           WHEN delivery.priority = 'critical' OR lower(COALESCE(delivery.payload->>'severity', ''))
                                IN ('critical', 'major', 'high', 'p1', 'emergency')
                           THEN 0 ELSE 1
                       END,
                       delivery.publish_available_at, delivery.created_at, delivery.id
                 LIMIT GREATEST(0, ? - (SELECT COUNT(*) FROM quota_candidates))
                 FOR UPDATE OF delivery SKIP LOCKED
            ), candidates AS (
                SELECT id, priority FROM quota_candidates
                UNION ALL
                SELECT id, priority FROM overflow_candidates
            )
            UPDATE alert_delivery_outbox AS delivery
               SET publish_lease_owner = ?,
                   publish_lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                   publish_attempts = publish_attempts + 1,
                   updated_at = clock_timestamp()
              FROM candidates
             WHERE delivery.id = candidates.id
            RETURNING delivery.id, delivery.dispatch_generation,
                      candidates.priority AS priority,
                      (delivery.published_generation >= delivery.dispatch_generation) AS redrive
            """,
            (
                *_PUBLISHED_RETRY_INTERVALS_SECONDS,
                _PUBLISHED_RETRY_MAX_SECONDS,
                normal_quota,
                *_PUBLISHED_RETRY_INTERVALS_SECONDS,
                _PUBLISHED_RETRY_MAX_SECONDS,
                critical_quota,
                *_PUBLISHED_RETRY_INTERVALS_SECONDS,
                _PUBLISHED_RETRY_MAX_SECONDS,
                limit,
                relay_id,
                _PUBLISH_LEASE_SECONDS,
            ),
        ).fetchall()
        connection.commit()
        return [dict(row) for row in rows]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _mark_published(*, delivery_id: str, generation: int, relay_id: str, redrive: bool = False) -> bool:
    connection = get_db_connection()
    try:
        result = connection.execute(
            """
            UPDATE alert_delivery_outbox
               SET published_generation = GREATEST(published_generation, ?),
                   published_at = clock_timestamp(),
                   publish_redrive_count = publish_redrive_count + ?,
                   publish_lease_owner = '', publish_lease_until = NULL,
                   publish_last_error = '', updated_at = clock_timestamp()
             WHERE id = ? AND status = 'pending'
               AND dispatch_generation = ? AND publish_lease_owner = ?
            """,
            (generation, int(bool(redrive)), delivery_id, generation, relay_id),
        )
        connection.commit()
        return int(result.rowcount or 0) == 1
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _release_publish_failure(*, delivery_id: str, generation: int, relay_id: str, error_code: str) -> None:
    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT publish_attempts FROM alert_delivery_outbox WHERE id = ? AND publish_lease_owner = ? AND dispatch_generation = ? FOR UPDATE",
            (delivery_id, relay_id, generation),
        ).fetchone()
        if row:
            attempts = max(1, int(row['publish_attempts'] or 1))
            backoff_seconds = min(60, 2 ** min(attempts, 6))
            connection.execute(
                """
                UPDATE alert_delivery_outbox
                   SET publish_lease_owner = '', publish_lease_until = NULL,
                       publish_available_at = clock_timestamp() + (? * INTERVAL '1 second'),
                       publish_last_error = ?, updated_at = clock_timestamp()
                 WHERE id = ? AND publish_lease_owner = ? AND dispatch_generation = ?
                """,
                (backoff_seconds, error_code[:120], delivery_id, relay_id, generation),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def publish_ready_alert_deliveries(*, limit: int = 50) -> dict[str, int]:
    """Publish due rows, leaving all delivery retries and truth in PostgreSQL."""
    try:
        claim_limit = max(0, min(_MAX_CLAIM_LIMIT, int(limit)))
    except (TypeError, ValueError) as exc:
        raise ValueError('limit must be an integer') from exc
    counts = {'claimed': 0, 'published': 0, 'failed': 0}
    if claim_limit == 0:
        return counts

    relay_id = str(uuid.uuid4())
    deliveries = _claim_ready_deliveries(limit=claim_limit, relay_id=relay_id)
    counts['claimed'] = len(deliveries)
    for delivery in deliveries:
        delivery_id = str(delivery['id'])
        generation = int(delivery['dispatch_generation'])
        priority = str(delivery.get('priority') or 'normal')
        queue = ALERT_NOTIFY_CRITICAL_QUEUE if priority == 'critical' else ALERT_NOTIFY_NORMAL_QUEUE
        try:
            stable_task_id = hashlib.sha256(f'{delivery_id}:{generation}'.encode()).hexdigest()
            app.send_task(
                TASK_NAME,
                args=[delivery_id, generation],
                task_id=stable_task_id,
                queue=queue,
                serializer='json',
                retry=False,
                ignore_result=True,
            )
        except Exception as exc:
            error_code = f'broker_publish_{type(exc).__name__}'
            try:
                _release_publish_failure(
                    delivery_id=delivery_id,
                    generation=generation,
                    relay_id=relay_id,
                    error_code=error_code,
                )
            except Exception:
                logger.exception('Could not release alert publish lease (delivery_id=%s)', delivery_id)
            counts['failed'] += 1
            logger.warning('Alert broker publish failed (delivery_id=%s, error_type=%s)', delivery_id, type(exc).__name__)
            continue
        try:
            if _mark_published(
                delivery_id=delivery_id,
                generation=generation,
                relay_id=relay_id,
                redrive=bool(delivery.get('redrive')),
            ):
                counts['published'] += 1
        except Exception:
            # A broker message may already be visible. Let the lease expire and
            # republish the same generation; worker fencing absorbs duplicates.
            logger.exception('Could not mark alert delivery published (delivery_id=%s)', delivery_id)
    return counts


def relay_alert_deliveries_once(*, limit: int = 50) -> dict[str, int]:
    from services.monitoring_notification_outbox_service import recover_expired_alert_delivery_leases

    recovered = recover_expired_alert_delivery_leases(limit=limit)
    published = publish_ready_alert_deliveries(limit=limit)
    return {**published, 'recovered': recovered.get('recovered', 0), 'terminal_failures': recovered.get('failed', 0)}


__all__ = ['publish_ready_alert_deliveries', 'relay_alert_deliveries_once']
