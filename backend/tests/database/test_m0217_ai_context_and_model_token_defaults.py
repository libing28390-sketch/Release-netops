from __future__ import annotations


def test_m0217_raises_defaults_and_only_backfills_legacy_remote_models(isolated_db) -> None:
    from database.migrations import m0217_ai_context_and_model_token_defaults as migration

    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_conversations (id, tenant_id, user_id_opaque, title, status, context_budget, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', 32768, ?, ?)",
            (
                "conversation-m217",
                "tenant-m217",
                "opaque-m217",
                "legacy default",
                "2026-09-10T00:00:00Z",
                "2026-09-10T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, enabled, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            ("provider-m217", "DeepSeek", "deepseek", "2026-09-10T00:00:00Z", "2026-09-10T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO ai_model (
                id, provider_id, name, model_code, model_type, context_length,
                max_output_tokens, default_max_tokens, enabled, is_default,
                priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'chat', 128000, 4096, 2048, 1, 0, 10, ?, ?)
            """,
            (
                "model-m217",
                "provider-m217",
                "DeepSeek Chat",
                "deepseek-chat",
                "2026-09-10T00:00:00Z",
                "2026-09-10T00:00:00Z",
            ),
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        row = conn.execute(
            "SELECT context_length, max_output_tokens, default_max_tokens FROM ai_model WHERE id = ?",
            ("model-m217",),
        ).fetchone()
        conversation_budget = conn.execute(
            "SELECT context_budget FROM ai_conversations WHERE id = ?",
            ("conversation-m217",),
        ).fetchone()[0]
        defaults = {
            row[0]
            for row in conn.execute(
                "SELECT column_default FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'ai_model' AND column_name IN ('context_length', 'max_output_tokens', 'default_max_tokens')"
            ).fetchall()
        }

    assert tuple(row) == (131072, 16384, 4096)
    assert conversation_budget == 8192
    assert any("131072" in str(value) for value in defaults)
    assert any("16384" in str(value) for value in defaults)
    assert any("4096" in str(value) for value in defaults)


def test_m0217_does_not_upgrade_local_model_capabilities(isolated_db) -> None:
    from database.migrations import m0217_ai_context_and_model_token_defaults as migration

    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, enabled, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            ("provider-local-m217", "Ollama", "ollama", "2026-09-10T00:00:00Z", "2026-09-10T00:00:00Z"),
        )
        conn.execute(
            """
            INSERT INTO ai_model (
                id, provider_id, name, model_code, model_type, context_length,
                max_output_tokens, default_max_tokens, enabled, is_default,
                priority, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'chat', 32768, 4096, 2048, 1, 0, 10, ?, ?)
            """,
            (
                "model-local-m217",
                "provider-local-m217",
                "Local Llama",
                "llama3.1",
                "2026-09-10T00:00:00Z",
                "2026-09-10T00:00:00Z",
            ),
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        row = conn.execute(
            "SELECT context_length, max_output_tokens, default_max_tokens FROM ai_model WHERE id = ?",
            ("model-local-m217",),
        ).fetchone()

    assert tuple(row) == (32768, 4096, 2048)
