"""PostgreSQL-authoritative contracts for Security Gateway, Copilot and DIA.

All columns are additive and metadata-only.  Raw prompts, provider payloads,
credentials, terminal output and attachment bodies are intentionally absent.
The SQLite branch exists only so old local fixtures can import the migration;
release acceptance is performed against PostgreSQL.
"""

from __future__ import annotations

VERSION = 142
NAME = "ai_security_copilot_diagnostics"


def _json_type(use_pg: bool) -> str:
    return "JSONB"


def _json_default(use_pg: bool, value: str = "{}") -> str:
    return f"'{value}'::jsonb"


def upgrade(cursor, use_pg: bool) -> None:
    json_type = _json_type(use_pg)
    statements = [
        f"""
        CREATE TABLE IF NOT EXISTS ai_security_events (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            workspace_id TEXT,
            site_id TEXT,
            department TEXT,
            document_scope TEXT,
            user_role TEXT,
            user_id_opaque TEXT,
            policy_version TEXT NOT NULL,
            classification TEXT NOT NULL,
            data_region TEXT NOT NULL,
            decision TEXT NOT NULL,
            disposition TEXT NOT NULL,
            provider_id TEXT,
            model_id TEXT,
            finding_categories_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            payload_bytes INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            created_at TEXT NOT NULL,
            CHECK (classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET')),
            CHECK (decision IN ('ALLOW', 'MINIMIZE', 'TOKENIZE', 'BLOCK')),
            CHECK (disposition IN ('prepared', 'blocked', 'sent', 'failed'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_security_scope_policies (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            document_scope_json {json_type} NOT NULL DEFAULT {_json_default(use_pg)},
            user_roles_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            provider_allowlist_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            allowed_classifications_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '["PUBLIC","INTERNAL"]')},
            status TEXT NOT NULL DEFAULT 'active',
            policy_version TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, scope_type, scope_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_provider_security_controls (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            kill_switch INTEGER NOT NULL DEFAULT 0,
            allowed_data_regions_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '["unknown"]')},
            allowed_classifications_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '["PUBLIC","INTERNAL","CONFIDENTIAL"]')},
            reason_code TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL,
            UNIQUE (tenant_id, provider_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_conversation_feedback (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            user_id_opaque TEXT NOT NULL,
            rating TEXT NOT NULL,
            reasons_json TEXT NOT NULL DEFAULT '[]',
            comment_safe TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE (tenant_id, conversation_id, message_id, user_id_opaque),
            CHECK (rating IN ('positive', 'negative'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_diagnostic_cases (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            symptom_safe TEXT NOT NULL DEFAULT '',
            scope_json {json_type} NOT NULL DEFAULT {_json_default(use_pg)},
            plan_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            evidence_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            conclusion_json {json_type} NOT NULL DEFAULT {_json_default(use_pg)},
            handoff_json {json_type} NOT NULL DEFAULT {_json_default(use_pg)},
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (status IN ('open', 'investigating', 'resolved', 'archived'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_diagnostic_runs (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'symptom',
            playbook_code TEXT NOT NULL,
            vendor TEXT,
            platform TEXT,
            device_id TEXT,
            read_only INTEGER NOT NULL DEFAULT 1,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_code TEXT,
            UNIQUE (tenant_id, id),
            CHECK (state IN ('symptom', 'scope', 'hypothesis', 'evidence', 'check', 'conclusion', 'remediation', 'verification', 'completed', 'failed'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_diagnostic_steps (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            step_no INTEGER NOT NULL,
            purpose TEXT NOT NULL,
            command_safe TEXT,
            target_safe TEXT,
            status TEXT NOT NULL,
            evidence_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            duration_ms INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (run_id, step_no),
            CHECK (status IN ('planned', 'authorized', 'running', 'passed', 'warning', 'failed', 'skipped'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_attachment_security_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            conversation_id TEXT,
            file_name_safe TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            classification TEXT NOT NULL,
            decision TEXT NOT NULL,
            finding_categories_json {json_type} NOT NULL DEFAULT {_json_default(use_pg, '[]')},
            created_at TEXT NOT NULL,
            CHECK (decision IN ('ALLOW', 'MINIMIZE', 'BLOCK'))
        )
        """,
    ]
    for statement in statements:
        cursor.execute(statement)

    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_ai_security_events_tenant_created ON ai_security_events(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_security_events_request ON ai_security_events(request_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_security_events_decision ON ai_security_events(tenant_id, decision, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_security_scope_policy ON ai_security_scope_policies(tenant_id, scope_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_provider_security_controls ON ai_provider_security_controls(tenant_id, provider_id, kill_switch)",
        "CREATE INDEX IF NOT EXISTS ix_ai_feedback_conversation ON ai_conversation_feedback(tenant_id, conversation_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_diagnostic_cases_tenant ON ai_diagnostic_cases(tenant_id, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_diagnostic_steps_run ON ai_diagnostic_steps(tenant_id, run_id, step_no)",
        "CREATE INDEX IF NOT EXISTS ix_ai_attachment_security_tenant ON ai_attachment_security_events(tenant_id, created_at)",
    ]
    for statement in indexes:
        cursor.execute(statement)


def downgrade(cursor, use_pg: bool) -> None:
    # Contract is additive; rollback disables routes and retains evidence.
    return None
