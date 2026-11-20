from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog

from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from database.migrations import m0116_knowledge_v2_source_registry as m0116
from database.migrations import m0117_knowledge_v2_document_versions as m0117
from database.migrations import m0119_knowledge_v2_document_lifecycle as m0119
from database.migrations import m0120_knowledge_v2_source_freshness as m0120
from database.migrations import m0121_knowledge_v2_source_change_detection as m0121


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    return conn


def _apply_through_m0120(conn: postgresql_test_driver.Connection) -> None:
    for migration in (m0116, m0117, m0119, m0120):
        migration.upgrade(conn.cursor(), True)
    conn.commit()


def _seed_source_version(conn: postgresql_test_driver.Connection, *, source_id: str = "source-121", version_id: str = "version-121") -> tuple[str, str, str, int]:
    tenant_id = "tenant-121"
    content_hash = "a" * 64
    byte_size = 121
    conn.execute(
        """
        INSERT INTO kb_source_registry (
            id, tenant_id, source_type, source_kind, canonical_url, allowed_host,
            trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by
        ) VALUES (?, ?, 'official_vendor', 'official_url', ?, 'docs.example', 'official', '{}', ?, ?, 'test', 'test')
        """,
        (source_id, tenant_id, f"https://docs.example/{source_id}", "2026-08-09", "2026-08-09"),
    )
    conn.execute(
        """
        INSERT INTO kb_source_version (
            id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
            parser_name, parser_version, status, created_at, updated_at, created_by, updated_by
        ) VALUES (?, ?, ?, '2026-08-09', ?, ?, 'html', '1', 'fetched', '2026-08-09', '2026-08-09', 'test', 'test')
        """,
        (version_id, tenant_id, source_id, content_hash, byte_size),
    )
    conn.commit()
    return tenant_id, source_id, content_hash, byte_size


def _observation_values(*, observation_id: str, tenant_id: str, source_id: str, version_id: str | None, content_hash: str, byte_size: int, detection_type: str = "version_updated", replacement_url: str = "", version_signal: str = '{"previous_content_hash":"old"}') -> tuple:
    return (
        observation_id, tenant_id, source_id, version_id, "2026-08-09T00:00:00Z",
        "GET", 200, "changed", content_hash, byte_size, "", "", "https://docs.example/current",
        "text/html", "", "{}", "{}", "2026-08-09T00:00:00Z", "test",
        detection_type, replacement_url, version_signal,
    )


_OBSERVATION_SQL = """
    INSERT INTO kb_source_refresh_observation (
        id, tenant_id, source_registry_id, source_version_id, checked_at,
        request_method, http_status, outcome, content_hash, byte_size,
        source_etag, source_last_modified, fetch_url, response_content_type,
        error_code, error_json, metadata_json, created_at, created_by,
        detection_type, replacement_url, version_signal_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def test_m0121_upgrade_from_m0120_adds_guards_and_is_idempotent():
    conn = _connection()
    try:
        _apply_through_m0120(conn)
        m0121.upgrade(conn.cursor(), True)
        conn.commit()
        m0121.upgrade(conn.cursor(), True)
        conn.commit()

        columns = pg_catalog.table_columns(conn, "kb_source_refresh_observation")
        assert {"detection_type", "replacement_url", "version_signal_json"} <= columns
        refresh_indexes = pg_catalog.index_names(conn, "kb_source_refresh_observation")
        document_indexes = pg_catalog.index_names(conn, "kb_document")
        assert "ix_kb_source_refresh_detection" in refresh_indexes
        assert "ix_kb_document_source_lifecycle" in document_indexes
        action_indexes = pg_catalog.index_names(conn, "kb_source_change_action")
        assert "ix_kb_source_change_action_pending" in action_indexes
        action_foreign_keys = pg_catalog.foreign_key_targets(conn, "kb_source_change_action")
        assert {"kb_source_refresh_observation", "kb_source_registry"} <= action_foreign_keys
        triggers = pg_catalog.trigger_names(conn)
        assert {
            "trg_kb_source_refresh_observation_append_only",
            "trg_kb_source_refresh_observation_insert_guard",
            "trg_kb_source_change_action_scope",
        } <= triggers
    finally:
        conn.close()


def test_m0121_historical_schema_accepts_valid_append_only_observation():
    conn = _connection()
    try:
        _apply_through_m0120(conn)
        m0121.upgrade(conn.cursor(), True)
        tenant_id, source_id, content_hash, byte_size = _seed_source_version(conn)
        conn.execute(
            _OBSERVATION_SQL,
            _observation_values(
                observation_id="observation-valid", tenant_id=tenant_id, source_id=source_id,
                version_id="version-121", content_hash=content_hash, byte_size=byte_size,
            ),
        )
        conn.commit()

        with pytest.raises(postgresql_test_driver.DatabaseError, match="append_only"):
            conn.execute("UPDATE kb_source_refresh_observation SET outcome = 'unchanged' WHERE id = 'observation-valid'")
        conn.rollback()
        with pytest.raises(postgresql_test_driver.DatabaseError, match="append_only"):
            conn.execute("DELETE FROM kb_source_refresh_observation WHERE id = 'observation-valid'")
        conn.rollback()
    finally:
        conn.close()


def test_m0121_change_action_is_tenant_scoped_retry_outbox_with_status_and_scope_guards():
    conn = _connection()
    try:
        _apply_through_m0120(conn)
        m0121.upgrade(conn.cursor(), True)
        tenant_id, source_id, content_hash, byte_size = _seed_source_version(conn)
        conn.execute(
            _OBSERVATION_SQL,
            _observation_values(
                observation_id="observation-action", tenant_id=tenant_id, source_id=source_id,
                version_id="version-121", content_hash=content_hash, byte_size=byte_size,
                detection_type="replacement", replacement_url="https://docs.example/new",
            ),
        )
        action_sql = """
            INSERT INTO kb_source_change_action (
                id, tenant_id, refresh_observation_id, source_registry_id, detection_type,
                status, attempt_count, last_error_code, created_at, updated_at,
                created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            "action-121", tenant_id, "observation-action", source_id, "replacement",
            "pending", 0, "", "2026-08-09", "2026-08-09", "test", "test",
        )
        conn.execute(action_sql, values)
        conn.execute(
            "UPDATE kb_source_change_action SET status = 'applying', attempt_count = 1, updated_by = 'worker' WHERE id = 'action-121'"
        )
        conn.commit()
        with pytest.raises(postgresql_test_driver.IntegrityError):
            conn.execute(action_sql, ("action-duplicate", *values[1:]))
        conn.rollback()
        with pytest.raises(postgresql_test_driver.IntegrityError):
            conn.execute(action_sql, ("action-status", tenant_id, "observation-action", source_id, "replacement", "unknown", 0, "", "2026-08-09", "2026-08-09", "test", "test"))
        conn.rollback()
        with pytest.raises(postgresql_test_driver.DatabaseError, match="scope_mismatch"):
            conn.execute(action_sql, ("action-scope", tenant_id, "observation-action", source_id, "removed", "pending", 0, "", "2026-08-09", "2026-08-09", "test", "test"))
        conn.rollback()
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("source_id", "version_id", "content_hash", "byte_size", "detection_type", "replacement_url", "version_signal"),
    [
        ("source-other", "version-121", "a" * 64, 121, "version_updated", "", '{"change":"new"}'),
        ("source-121", "version-121", "b" * 64, 121, "version_updated", "", '{"change":"new"}'),
        ("source-121", "version-121", "a" * 64, 122, "version_updated", "", '{"change":"new"}'),
        ("source-121", "version-121", "a" * 64, 121, "replacement", "", '{"change":"redirect"}'),
        ("source-121", "version-121", "a" * 64, 121, "none", "https://docs.example/replacement", "{}"),
        ("source-121", "version-121", "a" * 64, 121, "version_updated", "", "{}"),
        ("source-121", "version-121", "a" * 64, 121, "version_updated", "", "[]"),
    ],
)
def test_m0121_raw_sql_rejects_cross_source_fact_and_signal_shape_mismatches(
    source_id: str,
    version_id: str,
    content_hash: str,
    byte_size: int,
    detection_type: str,
    replacement_url: str,
    version_signal: str,
):
    conn = _connection()
    try:
        _apply_through_m0120(conn)
        m0121.upgrade(conn.cursor(), True)
        tenant_id, _, _, _ = _seed_source_version(conn)
        if source_id == "source-other":
            _seed_source_version(conn, source_id="source-other", version_id="version-other")
        with pytest.raises(postgresql_test_driver.DatabaseError, match="kb_source_refresh_observation_"):
            conn.execute(
                _OBSERVATION_SQL,
                _observation_values(
                    observation_id=f"invalid-{detection_type}-{byte_size}-{source_id}",
                    tenant_id=tenant_id,
                    source_id=source_id,
                    version_id=version_id,
                    content_hash=content_hash,
                    byte_size=byte_size,
                    detection_type=detection_type,
                    replacement_url=replacement_url,
                    version_signal=version_signal,
                ),
            )
    finally:
        conn.close()


def test_m0121_postgres_information_schema_queries_are_scoped_to_current_schema():
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple]] = []

        def execute(self, sql: str, params: tuple) -> None:
            self.calls.append((sql, params))

        def fetchall(self) -> list[tuple[str]]:
            return []

        def fetchone(self) -> tuple[bool]:
            return (False,)

    cursor = Cursor()
    assert m0121._table_columns(cursor, "kb_source_refresh_observation", True) == set()
    assert m0121._table_exists(cursor, "kb_source_refresh_observation", True) is False
    assert all("table_schema = current_schema()" in sql for sql, _ in cursor.calls)
