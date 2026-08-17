from __future__ import annotations

import uuid

import pytest

from database.core import _USE_PG, get_db_connection


pytestmark = pytest.mark.skipif(not _USE_PG, reason="PostgreSQL is the only release authority for SEC/COP/DIA")


def test_m0142_postgresql_tables_constraints_and_metadata_boundary():
    suffix = uuid.uuid4().hex[:10]
    event_id = f"pg_sec_{suffix}"
    with get_db_connection() as conn:
        assert conn.execute("SELECT current_setting('server_version_num')").fetchone()
        assert conn.execute(
            "SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ai_security_events' AND column_name='finding_categories_json'"
        ).fetchone()[0] == "jsonb"
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO ai_security_events (id, request_id, tenant_id, policy_version, classification, data_region, decision, disposition, finding_categories_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, event_id, "tenant-pg-test", "sec-v2", "UNKNOWN", "unknown", "ALLOW", "sent", ["credential"], "now"),
            )
            conn.rollback()
        conn.execute(
            "INSERT INTO ai_security_events (id, request_id, tenant_id, policy_version, classification, data_region, decision, disposition, finding_categories_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, event_id, "tenant-pg-test", "sec-v2", "CONFIDENTIAL", "cn", "TOKENIZE", "prepared", ["ip_address"], "now"),
        )
        row = conn.execute("SELECT finding_categories_json, payload_bytes FROM ai_security_events WHERE id = ?", (event_id,)).fetchone()
        assert row[0] == ["ip_address"]
        assert row[1] == 0
        conn.rollback()
