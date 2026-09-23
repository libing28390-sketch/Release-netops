"""Durable, PostgreSQL-backed delivery queue for monitoring notifications."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from database import get_db_connection

logger = logging.getLogger(__name__)

_ALLOWED_CHANNELS = frozenset({
    "workspace", "feishu", "dingtalk", "wechat", "email", "global_webhook",
})
_MAX_CLAIM_LIMIT = 100
_LEASE_SECONDS = 120
_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|credential|authorization|signature|private.?key|"
    r"community|webhook.?url|api.?key|access.?key|email|recipient(?:_address|_list|_emails))",
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|credential|authorization|signature|"
    r"api[_-]?key|access[_-]?key|community)\b\s*[:=]\s*)[^\s,;]+"
)
_AUTHORIZATION_ASSIGNMENT = re.compile(
    r"(?i)(\bauthorization\b\s*[:=]\s*)(?:bearer\s+)?[^\r\n,;]+"
)
_SENSITIVE_QUERY = re.compile(
    r"(?i)([?&](?:key|token|secret|password|sign|signature|access_key|api_key)=)[^&#\s]+"
)
_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@")
_BEARER_VALUE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")


class _DeliveryAttemptError(RuntimeError):
    """An expected outbound failure with a fixed, non-sensitive summary."""

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _record_alert_activity(connection, alert_id: str | None, event_type: str, metadata: dict[str, Any]) -> None:
    if not alert_id:
        return
    connection.execute(
        """
        INSERT INTO alert_activity
            (id, alert_id, event_type, from_state, to_state, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, clock_timestamp())
        """,
        (
            f"aact_{uuid.uuid4().hex[:16]}",
            str(alert_id),
            event_type,
            None,
            None,
            json.dumps(metadata, ensure_ascii=False, allow_nan=False),
        ),
    )


def _record_delivery_attempt(
    connection,
    *,
    delivery_id: str,
    alert_id: str | None,
    tenant_id: str,
    channel: str,
    event_kind: str,
    attempt_no: int,
    status: str,
    error_code: str = '',
    error_summary: str = '',
    recipient_count: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO alert_delivery_attempts (
            id, delivery_id, alert_id, tenant_id, channel, event_kind,
            attempt_no, status, error_code, error_summary, provider_class,
            recipient_count, started_at, finished_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, clock_timestamp(),
                  CASE WHEN ? IN ('queued', 'sending', 'retrying') THEN NULL ELSE clock_timestamp() END,
                  clock_timestamp())
        """,
        (
            f"adat_{uuid.uuid4().hex[:16]}",
            delivery_id,
            alert_id,
            tenant_id or 'tenant-default',
            'smtp' if channel == 'email' else 'webhook' if channel == 'global_webhook' else channel,
            event_kind or 'active',
            max(1, int(attempt_no or 1)),
            status,
            error_code[:120],
            error_summary[:500],
            channel,
            max(0, int(recipient_count or 0)),
            status,
        ),
    )


def _sanitize_text(value: str) -> str:
    value = _URL_USERINFO.sub(r"\1[REDACTED]@", value)
    value = _AUTHORIZATION_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _SENSITIVE_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    value = _SENSITIVE_QUERY.sub(r"\1[REDACTED]", value)
    return _BEARER_VALUE.sub(r"\1[REDACTED]", value)


def _sanitize_payload_value(value: Any, *, field_name: str = "") -> Any:
    """Remove credential-shaped fields before a payload is persisted."""
    if _SENSITIVE_KEY.search(field_name):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(key): _sanitize_payload_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_payload_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"Unsupported outbox payload value: {type(value).__name__}")


def enqueue_alert_delivery(*, delivery_key: str, channel: str, payload: dict) -> None:
    """Persist one idempotent alert delivery request.

    Repeated calls with a delivery key already in the outbox are no-ops. The
    caller should provide a stable key for one alert transition and channel.
    Credential-like payload fields are redacted before JSONB persistence.
    """
    normalized_key = str(delivery_key or "").strip()
    normalized_channel = str(channel or "").strip()
    if not normalized_key or len(normalized_key) > 512:
        raise ValueError("delivery_key must contain between 1 and 512 characters")
    if normalized_channel not in _ALLOWED_CHANNELS:
        raise ValueError(f"channel must be one of {sorted(_ALLOWED_CHANNELS)}")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")

    safe_payload = _sanitize_payload_value(payload)
    payload_json = json.dumps(safe_payload, ensure_ascii=False, allow_nan=False)
    connection = get_db_connection()
    try:
        inserted = connection.execute(
            """
            INSERT INTO alert_delivery_outbox (
                id, delivery_key, channel, payload, alert_id, tenant_id,
                event_kind, destination_key
            ) VALUES (?, ?, ?, ?::jsonb, ?, ?, ?, ?)
            ON CONFLICT (delivery_key) DO NOTHING
            RETURNING id
            """,
            (
                str(uuid.uuid4()),
                normalized_key,
                normalized_channel,
                payload_json,
                str(payload.get('alert_id') or '') or None,
                str(payload.get('tenant_id') or 'tenant-default'),
                str(payload.get('event_kind') or 'active'),
                str(payload.get('destination_key') or normalized_channel),
            ),
        ).fetchone()
        if inserted:
            alert_id = str(payload.get('alert_id') or '') or None
            _record_alert_activity(
                connection,
                alert_id,
                'NOTIFICATION_QUEUED',
                {
                    'channel': normalized_channel,
                    'event_kind': str(payload.get('event_kind') or 'active'),
                    'destination_key': str(payload.get('destination_key') or normalized_channel),
                    'status': 'queued',
                },
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _claim_deliveries(*, limit: int, worker_id: str) -> list[dict[str, Any]]:
    connection = get_db_connection()
    try:
        # Any expired lease at the retry ceiling is terminal. This also covers
        # a worker that died during its final permitted delivery attempt.
        connection.execute(
            """
            UPDATE alert_delivery_outbox
               SET status = 'failed', lease_owner = '', lease_until = NULL,
                   last_error = 'delivery retry limit exhausted after lease expiry',
                   completed_at = clock_timestamp(), updated_at = clock_timestamp()
             WHERE attempts >= max_attempts
               AND (status = 'pending' OR
                    (status = 'processing' AND lease_until <= clock_timestamp()))
            """
        )
        claimed = connection.execute(
            """
            WITH ready AS (
                SELECT id
                  FROM alert_delivery_outbox
                 WHERE attempts < max_attempts
                   AND ((status = 'pending' AND available_at <= clock_timestamp())
                     OR (status = 'processing' AND lease_until <= clock_timestamp()))
                 ORDER BY available_at, created_at, id
                 LIMIT ?
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE alert_delivery_outbox AS delivery
               SET status = 'processing',
                   attempts = delivery.attempts + 1,
                   lease_owner = ?,
                   lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                   updated_at = clock_timestamp()
              FROM ready
             WHERE delivery.id = ready.id
            RETURNING delivery.id, delivery.delivery_key, delivery.channel,
                      delivery.payload, delivery.attempts, delivery.max_attempts,
                      delivery.alert_id, delivery.tenant_id, delivery.event_kind,
                      delivery.destination_key
            """,
            (limit, worker_id, _LEASE_SECONDS),
        ).fetchall()
        connection.commit()
        items = [dict(row) for row in claimed]
        if items:
            audit_connection = get_db_connection()
            try:
                for item in items:
                    _record_delivery_attempt(
                        audit_connection,
                        delivery_id=str(item['id']),
                        alert_id=str(item.get('alert_id') or '') or None,
                        tenant_id=str(item.get('tenant_id') or 'tenant-default'),
                        channel=str(item.get('channel') or ''),
                        event_kind=str(item.get('event_kind') or 'active'),
                        attempt_no=int(item.get('attempts') or 1),
                        status='sending',
                    )
                audit_connection.commit()
            except Exception:
                audit_connection.rollback()
                logger.warning("Could not record notification delivery attempts", exc_info=True)
            finally:
                audit_connection.close()
        return items
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _deliver(row: dict[str, Any]) -> None:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    if row["channel"] == "global_webhook":
        from core.config import settings
        from services.notification_service import _post_json

        webhook_url = (settings.ALERT_NOTIFY_WEBHOOK_URL or "").strip()
        if not webhook_url:
            raise _DeliveryAttemptError("global_webhook_unconfigured")
        outbound_payload = {
            key: value
            for key, value in payload.items()
            if key not in {
                'alert_id', 'tenant_id', 'event_kind', 'rule_id',
                'destination_key', 'first_occurrence', 'last_occurrence',
                'duration_seconds', 'impact_window', 'alert_count', 'lang',
            }
        }
        ok, _response_body = _post_json(webhook_url, outbound_payload)
        if not ok:
            raise _DeliveryAttemptError("global_webhook_delivery_failed")
        return

    if row["channel"] == "workspace":
        from services import notification_service

        if not notification_service.automatic_notifications_enabled():
            return
        tenant_id = str(payload.get("tenant_id") or "").strip()
        if not tenant_id:
            raise _DeliveryAttemptError("workspace_tenant_missing")
        results = notification_service.dispatch_to_tenant_users(
            payload,
            tenant_id,
            raise_on_error=True,
        )
        row['_recipient_count'] = sum(int(result.get('recipient_count') or 0) for result in results)
        if any(not result.get("success", False) for result in results):
            first_error = next(
                (str(result.get('error') or '').strip() for result in results if not result.get('success', False)),
                '',
            )
            error_code = first_error or "workspace_delivery_failed"
            raise _DeliveryAttemptError(
                error_code,
                retryable=error_code not in {
                    'feishu_unconfigured', 'dingtalk_unconfigured', 'wechat_unconfigured',
                    'email_no_recipients', 'smtp_config_missing', 'smtp_auth_failed',
                    'smtp_tls_failed', 'smtp_invalid_recipient', 'smtp_recipient_rejected',
                },
            )
        return

    if row["channel"] in {"feishu", "dingtalk", "wechat", "email"}:
        from services import notification_service

        if not notification_service.automatic_notifications_enabled():
            return
        tenant_id = str(payload.get("tenant_id") or row.get("tenant_id") or "tenant-default").strip()
        if not tenant_id:
            raise _DeliveryAttemptError("notification_tenant_missing", retryable=False)
        results = notification_service.dispatch_to_tenant_users(
            payload,
            tenant_id,
            channels={str(row["channel"]).strip().lower()},
            raise_on_error=True,
        )
        row['_recipient_count'] = sum(int(result.get('recipient_count') or 0) for result in results)
        if not results:
            raise _DeliveryAttemptError(f"{row['channel']}_delivery_failed")
        failures = [result for result in results if not result.get("success", False)]
        if failures:
            first_error = str(failures[0].get('error') or '').strip() or f"{row['channel']}_delivery_failed"
            non_retryable = first_error in {
                'smtp_config_missing', 'email_no_recipients', 'smtp_invalid_recipient',
                'smtp_auth_failed', 'smtp_tls_failed', 'smtp_recipient_rejected',
                'feishu_unconfigured', 'dingtalk_unconfigured', 'wechat_unconfigured',
            }
            raise _DeliveryAttemptError(first_error, retryable=not non_retryable)
        return

    # The database check constraint protects persisted rows; keep a fail-closed
    # branch here in case data was modified outside the application.
    raise _DeliveryAttemptError("unsupported_delivery_channel", retryable=False)


def _safe_failure_summary(exc: Exception) -> str:
    if isinstance(exc, _DeliveryAttemptError):
        return exc.code
    return f"delivery_attempt_failed:{type(exc).__name__}"


def _finish_delivery(
    *,
    delivery_id: str,
    worker_id: str,
    success: bool,
    attempt: int,
    max_attempts: int,
    alert_id: str | None = None,
    tenant_id: str = 'tenant-default',
    channel: str = '',
    event_kind: str = 'active',
    recipient_count: int = 0,
    retryable: bool = True,
    error_summary: str = "",
) -> str | None:
    """Release a claimed row only while this worker still owns its lease."""
    connection = get_db_connection()
    try:
        if success:
            result = connection.execute(
                """
                UPDATE alert_delivery_outbox
                   SET status = 'succeeded', lease_owner = '', lease_until = NULL,
                       last_error = '', completed_at = clock_timestamp(),
                       updated_at = clock_timestamp()
                 WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (delivery_id, worker_id),
            )
            if int(result.rowcount or 0) == 1:
                _record_delivery_attempt(
                    connection,
                    delivery_id=delivery_id,
                    alert_id=alert_id,
                    tenant_id=tenant_id,
                    channel=channel,
                    event_kind=event_kind,
                    attempt_no=attempt,
                    status='succeeded',
                    recipient_count=recipient_count,
                )
                _record_alert_activity(
                    connection,
                    alert_id,
                    'NOTIFICATION_SENT',
                    {
                        'channel': channel,
                        'event_kind': event_kind,
                        'attempt': attempt,
                        'status': 'succeeded',
                        'recipient_count': max(0, int(recipient_count or 0)),
                    },
                )
            connection.commit()
            return "succeeded" if int(result.rowcount or 0) == 1 else None

        terminal = (not retryable) or attempt >= max_attempts
        backoff_seconds = min(3600, 5 * (2 ** max(0, attempt - 1)))
        if terminal:
            result = connection.execute(
                """
                UPDATE alert_delivery_outbox
                   SET status = 'failed', lease_owner = '', lease_until = NULL,
                       last_error = ?, completed_at = clock_timestamp(),
                       updated_at = clock_timestamp()
                 WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (error_summary, delivery_id, worker_id),
            )
        else:
            result = connection.execute(
                """
                UPDATE alert_delivery_outbox
                   SET status = 'pending', lease_owner = '', lease_until = NULL,
                       available_at = clock_timestamp() + (? * INTERVAL '1 second'),
                       last_error = ?, updated_at = clock_timestamp()
                 WHERE id = ? AND status = 'processing' AND lease_owner = ?
                """,
                (backoff_seconds, error_summary, delivery_id, worker_id),
            )
        skipped = error_summary in {
            'smtp_config_missing', 'email_no_recipients', 'smtp_invalid_recipient',
            'feishu_unconfigured', 'dingtalk_unconfigured', 'wechat_unconfigured',
        }
        status = 'skipped' if terminal and skipped else 'failed' if terminal else 'retrying'
        _record_delivery_attempt(
            connection,
            delivery_id=delivery_id,
            alert_id=alert_id,
            tenant_id=tenant_id,
            channel=channel,
            event_kind=event_kind,
            attempt_no=attempt,
            status=status,
            error_code=error_summary,
            error_summary=error_summary,
            recipient_count=recipient_count,
        )
        _record_alert_activity(
            connection,
            alert_id,
            'NOTIFICATION_SKIPPED' if status == 'skipped' else 'NOTIFICATION_FAILED' if terminal else 'NOTIFICATION_RETRYING',
            {
                'channel': channel,
                'event_kind': event_kind,
                'attempt': attempt,
                'status': status,
                'error_code': error_summary,
                'retryable': bool(retryable),
                'will_retry': not terminal,
                'recipient_count': max(0, int(recipient_count or 0)),
            },
        )
        connection.commit()
        if int(result.rowcount or 0) != 1:
            return None
        return "failed" if terminal else "retried"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def process_alert_delivery_outbox(*, limit: int = 20) -> dict[str, int]:
    """Claim and dispatch a bounded batch, persisting retry and terminal state.

    PostgreSQL row locks with ``SKIP LOCKED`` prevent concurrent workers from
    claiming the same live row. Processing rows with expired leases are
    reclaimable after a worker restart. Retry delays grow exponentially from
    five seconds and cap at one hour; after eight attempts, failures remain
    queryable with status ``failed``.
    """
    try:
        claim_limit = max(0, min(_MAX_CLAIM_LIMIT, int(limit)))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc

    counts = {"claimed": 0, "succeeded": 0, "retried": 0, "failed": 0}
    if claim_limit == 0:
        return counts

    worker_id = str(uuid.uuid4())
    deliveries = _claim_deliveries(limit=claim_limit, worker_id=worker_id)
    counts["claimed"] = len(deliveries)
    for delivery in deliveries:
        delivery_payload = delivery.get('payload')
        if isinstance(delivery_payload, str):
            try:
                delivery_payload = json.loads(delivery_payload)
            except (TypeError, ValueError):
                delivery_payload = {}
        if not isinstance(delivery_payload, dict):
            delivery_payload = {}
        recipient_count = int(delivery_payload.get('recipient_count') or delivery.get('_recipient_count') or 0)
        try:
            try:
                _deliver(delivery)
            except Exception as exc:
                error_summary = _safe_failure_summary(exc)
                logger.warning(
                    "Monitoring alert delivery %s failed (%s)",
                    delivery["id"],
                    error_summary,
                )
                outcome = _finish_delivery(
                    delivery_id=str(delivery["id"]),
                    worker_id=worker_id,
                    success=False,
                    attempt=int(delivery["attempts"]),
                    max_attempts=int(delivery["max_attempts"]),
                    alert_id=str(delivery.get('alert_id') or '') or None,
                    tenant_id=str(delivery.get('tenant_id') or 'tenant-default'),
                    channel=str(delivery.get('channel') or ''),
                    event_kind=str(delivery.get('event_kind') or 'active'),
                    recipient_count=recipient_count,
                    retryable=bool(getattr(exc, 'retryable', True)),
                    error_summary=error_summary,
                )
            else:
                outcome = _finish_delivery(
                    delivery_id=str(delivery["id"]),
                    worker_id=worker_id,
                    success=True,
                    attempt=int(delivery["attempts"]),
                    max_attempts=int(delivery["max_attempts"]),
                    alert_id=str(delivery.get('alert_id') or '') or None,
                    tenant_id=str(delivery.get('tenant_id') or 'tenant-default'),
                    channel=str(delivery.get('channel') or ''),
                    event_kind=str(delivery.get('event_kind') or 'active'),
                    recipient_count=recipient_count,
                )
        except Exception as exc:
            # A delivery whose state update could not be persisted remains
            # leased; the next worker can safely recover it after expiry.
            logger.warning(
                "Could not persist the outcome for monitoring delivery %s (%s)",
                delivery["id"],
                type(exc).__name__,
            )
            outcome = None
        if outcome in counts:
            counts[outcome] += 1
    return counts
