from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from database import get_db_connection
from database.migrations.m0241_monitoring_notification_outbox import upgrade
from services import monitoring_notification_outbox_service as outbox


def _get_delivery(delivery_key: str) -> dict:
    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT * FROM alert_delivery_outbox WHERE delivery_key = ?",
            (delivery_key,),
        ).fetchone()
        return dict(row)
    finally:
        connection.close()


def test_outbox_migration_is_idempotent_and_baseline_has_claim_indexes(isolated_db) -> None:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            upgrade(cursor, use_pg=True)
            upgrade(cursor, use_pg=True)
        connection.commit()
        rows = connection.execute(
            """
            SELECT indexname FROM pg_indexes
             WHERE schemaname = current_schema()
               AND tablename = 'alert_delivery_outbox'
            """
        ).fetchall()
        assert {row[0] for row in rows} >= {
            "alert_delivery_outbox_pkey",
            "alert_delivery_outbox_delivery_key_key",
            "idx_alert_delivery_outbox_claim",
            "idx_alert_delivery_outbox_status_created",
        }
    finally:
        connection.close()


def test_probe_target_tenant_migration_backfills_existing_and_defaults_new_rows(isolated_db) -> None:
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO outbound_probe_targets (id, target_name, host, port, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("legacy-probe-target", "legacy tenant migration test", "192.0.2.250", 443, "2026-09-19T00:00:00Z"),
        )
        connection.execute("DROP INDEX idx_outbound_probe_targets_tenant_id")
        connection.execute("ALTER TABLE outbound_probe_targets DROP COLUMN tenant_id")
        with connection.cursor() as cursor:
            upgrade(cursor, use_pg=True)
            upgrade(cursor, use_pg=True)
        connection.execute(
            """
            INSERT INTO outbound_probe_targets (id, target_name, host, port, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("new-probe-target", "new tenant migration test", "192.0.2.251", 443, "2026-09-19T00:00:00Z"),
        )
        connection.commit()
        rows = connection.execute(
            "SELECT id, tenant_id FROM outbound_probe_targets "
            "WHERE id IN ('legacy-probe-target', 'new-probe-target') ORDER BY id"
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("legacy-probe-target", "tenant-default"),
            ("new-probe-target", "tenant-default"),
        ]
    finally:
        connection.close()


def test_enqueue_is_idempotent_and_redacts_credential_fields(isolated_db) -> None:
    payload = {
        "title": "Device alert",
        "webhook_url": "https://hooks.invalid/send?key=private-value",
        "metadata": {"access_token": "private-value"},
        "signature": "private-value",
        "database_url": "postgresql://user:private-value@db.invalid/probe",
        "message": "password=private-value Authorization: Bearer private-value",
    }

    outbox.enqueue_alert_delivery(
        delivery_key="alert:device-1:active:workspace",
        channel="workspace",
        payload=payload,
    )
    outbox.enqueue_alert_delivery(
        delivery_key="alert:device-1:active:workspace",
        channel="workspace",
        payload={"title": "duplicate must not replace first"},
    )

    stored = _get_delivery("alert:device-1:active:workspace")
    assert stored["status"] == "pending"
    assert stored["payload"]["title"] == "Device alert"
    assert stored["payload"]["webhook_url"] == "[REDACTED]"
    assert stored["payload"]["metadata"]["access_token"] == "[REDACTED]"
    assert stored["payload"]["signature"] == "[REDACTED]"
    assert "private-value" not in str(stored["payload"])
    assert "[REDACTED]" in stored["payload"]["message"]


def test_workspace_delivery_is_scoped_to_payload_tenant(isolated_db, monkeypatch) -> None:
    from services import notification_service

    outbox.enqueue_alert_delivery(
        delivery_key="alert:tenant-device:active:workspace",
        channel="workspace",
        payload={"tenant_id": "tenant-acme", "title": "Tenant alert"},
    )
    calls: list[tuple[dict, str, bool]] = []

    monkeypatch.setattr(notification_service, "automatic_notifications_enabled", lambda: True)

    def dispatch_to_tenant_users(alert, tenant_id, *, raise_on_error=False):
        calls.append((alert, tenant_id, raise_on_error))
        return [{"success": True}]

    monkeypatch.setattr(notification_service, "dispatch_to_tenant_users", dispatch_to_tenant_users)
    monkeypatch.setattr(
        notification_service,
        "dispatch_to_all_users",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unscoped dispatch used")),
    )

    result = outbox.process_alert_delivery_outbox(limit=1)

    assert result == {"claimed": 1, "succeeded": 1, "retried": 0, "failed": 0}
    assert len(calls) == 1
    alert, tenant_id, raise_on_error = calls[0]
    assert alert["tenant_id"] == "tenant-acme"
    assert tenant_id == "tenant-acme"
    assert raise_on_error is True


def test_failed_delivery_persists_backoff_then_can_succeed(isolated_db, monkeypatch) -> None:
    outbox.enqueue_alert_delivery(
        delivery_key="alert:device-2:active:global",
        channel="global_webhook",
        payload={"msgtype": "text", "text": {"content": "alert"}},
    )

    def fail(_row):
        raise RuntimeError("private-value in an external URL")

    monkeypatch.setattr(outbox, "_deliver", fail)
    first = outbox.process_alert_delivery_outbox(limit=1)
    assert first == {"claimed": 1, "succeeded": 0, "retried": 1, "failed": 0}
    pending = _get_delivery("alert:device-2:active:global")
    assert pending["attempts"] == 1
    assert pending["status"] == "pending"
    assert pending["available_at"] > pending["updated_at"]
    assert "private-value" not in pending["last_error"]

    connection = get_db_connection()
    try:
        connection.execute(
            "UPDATE alert_delivery_outbox SET available_at = clock_timestamp() - INTERVAL '1 second' WHERE delivery_key = ?",
            ("alert:device-2:active:global",),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(outbox, "_deliver", lambda _row: None)
    second = outbox.process_alert_delivery_outbox(limit=1)
    assert second == {"claimed": 1, "succeeded": 1, "retried": 0, "failed": 0}
    succeeded = _get_delivery("alert:device-2:active:global")
    assert succeeded["status"] == "succeeded"
    assert succeeded["attempts"] == 2
    assert succeeded["completed_at"] is not None


def test_retry_ceiling_is_queryable_as_final_failure(isolated_db, monkeypatch) -> None:
    outbox.enqueue_alert_delivery(
        delivery_key="alert:device-3:active:workspace",
        channel="workspace",
        payload={"title": "Persistent failure"},
    )
    monkeypatch.setattr(outbox, "_deliver", lambda _row: (_ for _ in ()).throw(RuntimeError("secret")))

    for attempt in range(1, 9):
        result = outbox.process_alert_delivery_outbox(limit=1)
        if attempt < 8:
            assert result["retried"] == 1
            connection = get_db_connection()
            try:
                connection.execute(
                    "UPDATE alert_delivery_outbox SET available_at = clock_timestamp() - INTERVAL '1 second' WHERE delivery_key = ?",
                    ("alert:device-3:active:workspace",),
                )
                connection.commit()
            finally:
                connection.close()
        else:
            assert result["failed"] == 1

    failed = _get_delivery("alert:device-3:active:workspace")
    assert failed["status"] == "failed"
    assert failed["attempts"] == 8
    assert failed["completed_at"] is not None
    assert "secret" not in failed["last_error"]


def test_expired_worker_lease_is_reclaimed_and_workers_claim_distinct_rows(isolated_db, monkeypatch) -> None:
    for suffix in ("one", "two"):
        outbox.enqueue_alert_delivery(
            delivery_key=f"alert:concurrent:{suffix}",
            channel="workspace",
            payload={"title": suffix},
        )

    connection = get_db_connection()
    try:
        connection.execute(
            """
            UPDATE alert_delivery_outbox
               SET status = 'processing', attempts = 1, lease_owner = 'dead-worker',
                   lease_until = clock_timestamp() - INTERVAL '1 second'
             WHERE delivery_key = ?
            """,
            ("alert:concurrent:one",),
        )
        connection.commit()
    finally:
        connection.close()

    barrier = threading.Barrier(2)
    claimed_ids: list[str] = []
    claimed_ids_lock = threading.Lock()

    def deliver(row):
        with claimed_ids_lock:
            claimed_ids.append(str(row["id"]))
        barrier.wait(timeout=10)

    monkeypatch.setattr(outbox, "_deliver", deliver)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: outbox.process_alert_delivery_outbox(limit=1), range(2)))

    assert len(claimed_ids) == 2
    assert len(set(claimed_ids)) == 2
    assert all(result["claimed"] == 1 and result["succeeded"] == 1 for result in results)
    assert _get_delivery("alert:concurrent:one")["status"] == "succeeded"
    assert _get_delivery("alert:concurrent:two")["status"] == "succeeded"
