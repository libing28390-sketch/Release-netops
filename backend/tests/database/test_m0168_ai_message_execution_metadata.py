def test_m0168_adds_and_backfills_ai_message_execution_metadata(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_messages)").fetchall()}
        assert {"execution_mode", "external_egress", "input_tokens", "output_tokens", "latency_ms"}.issubset(columns)

        indexes = {row[1] for row in conn.execute("PRAGMA index_list(ai_messages)").fetchall()}
        assert "ix_ai_messages_execution_mode" in indexes


def test_m0168_backfill_does_not_invent_unknown_provider_usage(isolated_db) -> None:
    from database.migrations import m0168_ai_message_execution_metadata as migration

    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_conversations (id, tenant_id, user_id_opaque, title, status, context_budget, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("conv_m168", "tenant-a", "opaque", "test", "active", 32768, "2026-08-24T00:00:00Z", "2026-08-24T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO ai_messages (id, conversation_id, sequence_no, role, content_safe, citations_json, token_count, execution_mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("msg_local", "conv_m168", 1, "assistant", "local", '[{"citation_id":"c1"}]', 1, None, "2026-08-24T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO ai_messages (id, conversation_id, sequence_no, role, content_safe, citations_json, token_count, actual_model_id, provider_id, execution_mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("msg_cloud", "conv_m168", 2, "assistant", "cloud", "[]", 1, "model-deepseek", "provider-deepseek", None, "2026-08-24T00:00:01Z"),
        )
        conn.execute(
            "INSERT INTO ai_messages (id, conversation_id, sequence_no, role, content_safe, citations_json, token_count, execution_mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("msg_unknown", "conv_m168", 3, "assistant", "old", "[]", 1, None, "2026-08-24T00:00:02Z"),
        )
        migration.upgrade(conn, False)
        rows = conn.execute(
            "SELECT id, execution_mode, external_egress, input_tokens, output_tokens FROM ai_messages WHERE conversation_id = ? ORDER BY sequence_no",
            ("conv_m168",),
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("msg_local", "local_knowledge", 0, None, None),
        ("msg_cloud", "provider_generated", 1, None, None),
        ("msg_unknown", "legacy_unknown", None, None, None),
    ]
