from __future__ import annotations

import json
import uuid

from database import get_db_connection
from database.migrations import m0199_provider_endpoint_allowlist_repair as migration


def test_m0199_repairs_empty_cloud_allowlists_and_preserves_explicit_values(isolated_db):
    suffix = uuid.uuid4().hex[:12]
    rows = {
        "legacy": f"m0199-legacy-{suffix}",
        "explicit": f"m0199-explicit-{suffix}",
        "malformed": f"m0199-malformed-{suffix}",
        "local": f"m0199-local-{suffix}",
        "insecure": f"m0199-insecure-{suffix}",
    }
    conn = get_db_connection()
    try:
        now = "2026-09-01T00:00:00+00:00"
        values = [
            (rows["legacy"], "deepseek", "https://api.deepseek.com", "[]"),
            (rows["explicit"], "openai", "https://api.openai.com/v1", json.dumps(["https://api.openai.com/v1"])),
            (rows["malformed"], "openai_compatible", "https://example.test/v1", "{}"),
            (rows["local"], "ollama", "http://127.0.0.1:11434/v1", "[]"),
            (rows["insecure"], "openai", "http://api.example.test/v1", "[]"),
        ]
        for provider_id, provider_type, base_url, allowlist in values:
            conn.execute(
                """
                INSERT INTO ai_provider (
                    id, name, provider_type, base_url, api_key_encrypted, api_key_masked,
                    timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at,
                    tags_json, health_status, data_region, allowed_data_classification,
                    no_training_confirmed, retention_days, data_processing_agreement_ref,
                    agreement_reviewed_at, approved_endpoint_patterns_json
                ) VALUES (?, ?, ?, ?, NULL, NULL, 30, 3, NULL, 1, 'pytest', ?, ?, '[]', 'unknown', 'unknown', 'PUBLIC', 0, NULL, NULL, NULL, ?)
                """,
                (provider_id, provider_id, provider_type, base_url, now, now, allowlist),
            )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        result = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT id, approved_endpoint_patterns_json FROM ai_provider WHERE id IN (?, ?, ?, ?, ?) ORDER BY id",
                tuple(rows.values()),
            ).fetchall()
        }
        assert result[rows["legacy"]] == '["https://api.deepseek.com"]'
        assert result[rows["explicit"]] == '["https://api.openai.com/v1"]'
        assert result[rows["malformed"]] == '["https://example.test/v1"]'
        assert result[rows["local"]] == "[]"
        assert result[rows["insecure"]] == "[]"
    finally:
        conn.close()
