"""Migration m0103: Create Nexora AI Platform core database tables."""

from __future__ import annotations

VERSION = 103
NAME = "ai_platform_tables"


def upgrade(cursor, use_pg: bool) -> None:
    # 1. ai_provider
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_provider (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            provider_type TEXT NOT NULL,
            base_url TEXT,
            api_key_encrypted TEXT,
            api_key_masked TEXT,
            timeout INTEGER DEFAULT 30,
            max_retries INTEGER DEFAULT 3,
            proxy_url TEXT,
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_provider_type ON ai_provider(provider_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_provider_enabled ON ai_provider(enabled)")

    # 2. ai_model
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_model (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            name TEXT NOT NULL,
            model_code TEXT NOT NULL,
            model_type TEXT NOT NULL DEFAULT 'chat',
            thinking_supported INTEGER DEFAULT 0,
            tool_call_supported INTEGER DEFAULT 1,
            json_supported INTEGER DEFAULT 1,
            context_length INTEGER DEFAULT 32768,
            max_output_tokens INTEGER DEFAULT 4096,
            default_temperature REAL DEFAULT 0.7,
            default_max_tokens INTEGER DEFAULT 2048,
            enabled INTEGER DEFAULT 1,
            is_default INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 10,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (provider_id) REFERENCES ai_provider(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_provider ON ai_model(provider_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_default ON ai_model(is_default)")

    # 3. ai_model_route
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_model_route (
            id TEXT PRIMARY KEY,
            scene TEXT NOT NULL UNIQUE,
            model_id TEXT NOT NULL,
            fallback_model_id TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (model_id) REFERENCES ai_model(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_model_route_scene ON ai_model_route(scene)")

    # 4. ai_prompt
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_prompt (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            scene TEXT NOT NULL,
            vendor TEXT DEFAULT 'all',
            platform TEXT DEFAULT 'all',
            system_prompt TEXT NOT NULL,
            user_prompt_template TEXT NOT NULL,
            output_schema TEXT DEFAULT '{}',
            temperature REAL DEFAULT 0.2,
            max_tokens INTEGER DEFAULT 2048,
            version INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_prompt_code ON ai_prompt(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_prompt_scene ON ai_prompt(scene)")

    # 5. ai_prompt_version
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_prompt_version (
            id TEXT PRIMARY KEY,
            prompt_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt_template TEXT NOT NULL,
            output_schema TEXT DEFAULT '{}',
            temperature REAL DEFAULT 0.2,
            max_tokens INTEGER DEFAULT 2048,
            created_by TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (prompt_id) REFERENCES ai_prompt(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_prompt_version_pid ON ai_prompt_version(prompt_id, version)")

    # 6. ai_request_log
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_request_log (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            user_id TEXT,
            scene TEXT NOT NULL,
            provider_id TEXT,
            model_id TEXT,
            prompt_id TEXT,
            prompt_version INTEGER,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_request_log_reqid ON ai_request_log(request_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_request_log_created ON ai_request_log(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_request_log_scene ON ai_request_log(scene)")

    # 7. ai_usage_daily
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_usage_daily (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            scene TEXT NOT NULL,
            requests INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            avg_latency REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_date ON ai_usage_daily(date)")

    # 8. ai_tool
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_tool (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            risk_level TEXT NOT NULL DEFAULT 'R0',
            input_schema TEXT DEFAULT '{}',
            permission_code TEXT,
            enabled INTEGER DEFAULT 1,
            require_confirmation INTEGER DEFAULT 0,
            require_approval INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_tool_name ON ai_tool(name)")

    # 9. ai_agent
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            system_prompt TEXT NOT NULL,
            allowed_tools TEXT DEFAULT '[]',
            max_steps INTEGER DEFAULT 10,
            timeout INTEGER DEFAULT 60,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_code ON ai_agent(code)")

    # 10. ai_agent_run
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent_run (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            user_id TEXT,
            question TEXT NOT NULL,
            status TEXT NOT NULL,
            risk_level TEXT DEFAULT 'R0',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            final_result TEXT,
            error_message TEXT,
            FOREIGN KEY (agent_id) REFERENCES ai_agent(id) ON DELETE CASCADE
        )
        """
    )

    # 11. ai_agent_step
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_agent_step (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_no INTEGER NOT NULL,
            step_type TEXT NOT NULL,
            tool_name TEXT,
            tool_input TEXT,
            tool_output TEXT,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (run_id) REFERENCES ai_agent_run(id) ON DELETE CASCADE
        )
        """
    )

    # 12. ai_knowledge_base
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_knowledge_base (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    # 13. ai_document
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_document (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT NOT NULL,
            name TEXT NOT NULL,
            source TEXT,
            vendor TEXT DEFAULT 'all',
            platform TEXT DEFAULT 'all',
            version TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (knowledge_base_id) REFERENCES ai_knowledge_base(id) ON DELETE CASCADE
        )
        """
    )

    # 14. ai_document_chunk
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            metadata_json TEXT DEFAULT '{}',
            page INTEGER,
            section TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (document_id) REFERENCES ai_document(id) ON DELETE CASCADE
        )
        """
    )
