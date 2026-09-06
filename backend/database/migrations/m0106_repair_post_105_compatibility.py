"""Repair additive columns introduced after migration m0105 was deployed.

Migration ``m0105`` was applied to some installations before its compatibility
columns were added to the migration module.  Those databases have the new
tables, but older versions of the baseline AI/PAM/alert tables.  This
idempotent migration brings existing installations to the same shape as a
fresh install without rewriting or deleting application data.
"""

from __future__ import annotations

VERSION = 106
NAME = "repair_post_105_compatibility"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}



def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> set[str]:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return existing
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return existing | set(definitions)


def _create_missing_pam_tables(cursor) -> None:
    """Create PAM tables that were added after m0105 was first deployed."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS pam_approval_requests (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            command_event_id TEXT,
            requester_id TEXT NOT NULL,
            approver_id TEXT,
            state TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '',
            mfa_verified INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            decided_at TEXT,
            decision_note TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_change_transactions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            device_id TEXT,
            ticket_id TEXT,
            state TEXT NOT NULL DEFAULT 'draft',
            risk_level TEXT NOT NULL DEFAULT 'L3',
            before_snapshot_id TEXT,
            after_snapshot_id TEXT,
            diff_json TEXT NOT NULL DEFAULT '{}',
            rollback_plan_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL,
            approved_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_file_transfer_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            direction TEXT NOT NULL,
            file_name_safe TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            policy_decision TEXT NOT NULL DEFAULT 'BLOCK',
            actor_id TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_session_interventions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_jit_grants (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            allowed_actions_json TEXT NOT NULL DEFAULT '[]',
            denied_actions_json TEXT NOT NULL DEFAULT '[]',
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            break_glass INTEGER NOT NULL DEFAULT 0,
            mfa_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_break_glass_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            grant_id TEXT NOT NULL,
            subject_user_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            mfa_verified INTEGER NOT NULL DEFAULT 0,
            post_review_state TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_batch_operations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            created_by TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending_approval',
            target_ids_json TEXT NOT NULL DEFAULT '[]',
            max_targets INTEGER NOT NULL DEFAULT 0,
            concurrency INTEGER NOT NULL DEFAULT 1,
            canary_count INTEGER NOT NULL DEFAULT 0,
            failure_threshold REAL NOT NULL DEFAULT 0.1,
            command_risk_level TEXT NOT NULL DEFAULT 'L3',
            blast_radius_json TEXT NOT NULL DEFAULT '{}',
            change_transaction_id TEXT,
            scheduled_at TEXT,
            completed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            stopped_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_deferred_actions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            command_event_id TEXT,
            action_code TEXT NOT NULL,
            execute_at TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'scheduled',
            risk_level TEXT NOT NULL DEFAULT 'L3',
            reason TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_behavior_flags (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id TEXT,
            session_id TEXT,
            risk_level TEXT NOT NULL DEFAULT 'L1',
            risk_score INTEGER NOT NULL DEFAULT 0,
            signals_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            reviewed_by TEXT,
            reviewed_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_tacacs_reconciliations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            command_event_id TEXT,
            nexora_action TEXT NOT NULL,
            external_action TEXT NOT NULL,
            matched INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_rollback_checkpoints (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            change_transaction_id TEXT NOT NULL,
            device_id TEXT,
            checkpoint_type TEXT NOT NULL DEFAULT 'pre_change',
            snapshot_id TEXT,
            health_state TEXT NOT NULL DEFAULT 'unknown',
            verification_state TEXT NOT NULL DEFAULT 'pending',
            rollback_state TEXT NOT NULL DEFAULT 'not_requested',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_session_summaries (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            generated_by TEXT NOT NULL DEFAULT 'deterministic',
            created_at TEXT NOT NULL,
            UNIQUE (tenant_id, session_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_external_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            event_type TEXT NOT NULL,
            destination_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'queued',
            error_code TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        )
        """,
    ]
    for statement in statements:
        cursor.execute(statement)


def upgrade(cursor, use_pg: bool) -> None:
    _create_missing_pam_tables(cursor)
    _ensure_columns(
        cursor,
        "alert_silences",
        {"created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"},
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_knowledge_base",
        {
            "tenant_id": "TEXT DEFAULT 'tenant-default'",
            "acl_json": "TEXT DEFAULT '{}'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_agent_run",
        {
            "max_steps": "INTEGER DEFAULT 6",
            "max_tool_calls": "INTEGER DEFAULT 12",
            "deadline_at": "TEXT",
            "cancel_requested": "INTEGER DEFAULT 0",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_document",
        {
            "tenant_id": "TEXT DEFAULT 'tenant-default'",
            "acl_json": "TEXT DEFAULT '{}'",
            "source_trust_level": "TEXT DEFAULT 'internal'",
            "knowledge_source_type": "TEXT DEFAULT 'user_document'",
            "metadata_json": "TEXT DEFAULT '{}'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "pam_change_transactions",
        {
            "target_type": "TEXT",
            "target_name": "TEXT",
            "config_diff_id": "TEXT",
            "verification_state": "TEXT DEFAULT 'pending'",
            "rollback_state": "TEXT DEFAULT 'not_requested'",
            "commit_model": "TEXT DEFAULT 'direct'",
        },
        use_pg,
    )

    # Normalize only NULL/empty compatibility values.  Existing tenant data
    # and audit records are preserved; legacy rows are assigned to the
    # historical default tenant used by the pre-tenant schema.
    for table in ("ai_knowledge_base", "ai_document"):
        columns = _columns(cursor, table, use_pg)
        if "tenant_id" in columns:
            cursor.execute(
                f"UPDATE {table} SET tenant_id = ? "
                "WHERE tenant_id IS NULL OR tenant_id = ''",
                ("tenant-default",),
            )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_knowledge_base_scope "
        "ON ai_knowledge_base(tenant_id, enabled)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_documents_scope "
        "ON ai_document(tenant_id, status, vendor, platform)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_agent_run_status "
        "ON ai_agent_run(status)"
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_pam_approvals_scope ON pam_approval_requests(tenant_id, state, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_transactions_device ON pam_change_transactions(tenant_id, device_id, state)",
        "CREATE INDEX IF NOT EXISTS ix_pam_transfers_session ON pam_file_transfer_events(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_interventions_session ON pam_session_interventions(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_jit_scope ON pam_jit_grants(tenant_id, subject_user_id, state, ends_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_break_glass_review ON pam_break_glass_events(tenant_id, post_review_state, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_batch_scope ON pam_batch_operations(tenant_id, state, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_deferred_due ON pam_deferred_actions(tenant_id, state, execute_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_behavior_scope ON pam_behavior_flags(tenant_id, state, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_tacacs_event ON pam_tacacs_reconciliations(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_checkpoint_transaction ON pam_rollback_checkpoints(tenant_id, change_transaction_id, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_external_queue ON pam_external_events(tenant_id, state, created_at)",
    ):
        cursor.execute(statement)
