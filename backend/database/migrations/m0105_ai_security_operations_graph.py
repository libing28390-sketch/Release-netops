"""Security boundary, AI orchestration, topology graph, alert control and PAM audit.

This migration adds the durable metadata needed by the remediation plans. Raw
credentials, raw AI payloads and raw terminal streams are deliberately absent
from the new AI/audit tables; sensitive values remain in the existing encrypted
credential/recording controls and are never sent to an external model.
"""

from __future__ import annotations

VERSION = 105
NAME = "ai_security_operations_graph"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _ensure_columns(cursor, table: str, columns: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    # The baseline bootstrap normally creates these tables. Keep the
    # migration safe for an isolated/fresh migration test and for partially
    # provisioned installations: a missing legacy table is created by its
    # owning migration instead of making m0105 fail halfway through.
    if not existing:
        return
    for name, definition in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _create_tables(cursor) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS ai_security_policies (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            external_ai_enabled INTEGER NOT NULL DEFAULT 0,
            default_action TEXT NOT NULL DEFAULT 'BLOCK',
            rules_json TEXT NOT NULL DEFAULT '{}',
            provider_allowlist_json TEXT NOT NULL DEFAULT '[\"deepseek\"]',
            approved_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_outbound_audits (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            scene TEXT NOT NULL,
            provider_type TEXT,
            model_code TEXT,
            decision TEXT NOT NULL,
            max_data_level TEXT,
            finding_categories_json TEXT NOT NULL DEFAULT '[]',
            payload_bytes INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            error_code TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_security_incidents (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            task_id TEXT,
            request_id TEXT,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'high',
            category TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_kill_switch (
            id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_model_capabilities (
            model_code TEXT PRIMARY KEY,
            provider_type TEXT NOT NULL,
            thinking_supported INTEGER NOT NULL DEFAULT 0,
            tool_call_supported INTEGER NOT NULL DEFAULT 1,
            json_supported INTEGER NOT NULL DEFAULT 1,
            stream_supported INTEGER NOT NULL DEFAULT 1,
            max_context_tokens INTEGER NOT NULL DEFAULT 131072,
            max_output_tokens INTEGER NOT NULL DEFAULT 8192,
            contract_version TEXT NOT NULL DEFAULT 'nxa.ai.v1',
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            user_id_opaque TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            context_budget INTEGER NOT NULL DEFAULT 32768,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            role TEXT NOT NULL,
            content_safe TEXT NOT NULL DEFAULT '',
            reasoning_internal TEXT,
            tool_calls_json TEXT NOT NULL DEFAULT '[]',
            citations_json TEXT NOT NULL DEFAULT '[]',
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE,
            UNIQUE (conversation_id, sequence_no)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_tasks (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            tenant_id TEXT NOT NULL,
            user_id_opaque TEXT NOT NULL,
            scene TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued',
            max_steps INTEGER NOT NULL DEFAULT 8,
            max_tool_calls INTEGER NOT NULL DEFAULT 12,
            deadline_at TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            finished_at TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_tool_calls (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            step_no INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            input_schema_version TEXT NOT NULL DEFAULT 'nxa.tool.v1',
            input_safe_json TEXT NOT NULL DEFAULT '{}',
            result_safe_json TEXT NOT NULL DEFAULT '{}',
            source TEXT,
            freshness TEXT,
            status TEXT NOT NULL,
            policy_decision TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ai_evidence (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            tool_call_id TEXT,
            source_type TEXT NOT NULL,
            source_id TEXT,
            citation TEXT,
            fact_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0,
            collected_at TEXT NOT NULL
        )
        """,
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
        """
        CREATE TABLE IF NOT EXISTS topology_nodes (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            display_name TEXT,
            device_id TEXT,
            site_id TEXT,
            role_identity TEXT,
            function TEXT,
            zone TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            layout_override_json TEXT,
            rank REAL,
            first_seen TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, canonical_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS topology_edges (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            source_interface TEXT,
            target_interface TEXT,
            relation_type TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'undirected',
            existence TEXT NOT NULL DEFAULT 'observed',
            existence_confidence REAL NOT NULL DEFAULT 0,
            semantic_confidence REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            is_manual INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            first_seen TEXT,
            last_seen TEXT,
            stale_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, source_node_id, target_node_id, source_interface, target_interface, relation_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS topology_edge_evidence (
            id TEXT PRIMARY KEY,
            edge_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            protocol TEXT,
            observation_json TEXT NOT NULL DEFAULT '{}',
            priority INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            observed_at TEXT NOT NULL,
            FOREIGN KEY (edge_id) REFERENCES topology_edges(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS topology_change_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_rule_states (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            target_key TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'OK',
            pending_since TEXT,
            recovery_since TEXT,
            breach_count INTEGER NOT NULL DEFAULT 0,
            recovery_count INTEGER NOT NULL DEFAULT 0,
            flap_count INTEGER NOT NULL DEFAULT 0,
            last_value REAL,
            last_status TEXT,
            last_transition_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (rule_id, target_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_activity (
            id TEXT PRIMARY KEY,
            alert_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_id TEXT,
            from_state TEXT,
            to_state TEXT,
            note TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES alert_events(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_correlations (
            id TEXT PRIMARY KEY,
            alert_id TEXT NOT NULL,
            root_alert_id TEXT,
            correlation_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES alert_events(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_storms (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT,
            alert_count INTEGER NOT NULL DEFAULT 0,
            site_count INTEGER NOT NULL DEFAULT 0,
            type_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_silences (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_rule_versions (
            id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            checksum TEXT NOT NULL,
            change_type TEXT NOT NULL,
            changed_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (rule_id, version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_dry_runs (
            id TEXT PRIMARY KEY,
            rule_id TEXT,
            tenant_id TEXT NOT NULL,
            input_summary_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_operation_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            session_id TEXT,
            source_type TEXT NOT NULL,
            actor_id TEXT,
            device_id TEXT,
            action_code TEXT NOT NULL,
            risk_level TEXT NOT NULL DEFAULT 'L0',
            policy_decision TEXT NOT NULL,
            accepted_state TEXT NOT NULL DEFAULT 'unknown',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            previous_hash TEXT,
            event_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_command_events (
            id TEXT PRIMARY KEY,
            operation_event_id TEXT,
            session_id TEXT NOT NULL,
            command_index INTEGER NOT NULL,
            command_safe TEXT NOT NULL,
            canonical_action TEXT NOT NULL,
            vendor_platform TEXT,
            cli_mode TEXT,
            risk_level TEXT NOT NULL DEFAULT 'L0',
            risk_dimensions_json TEXT NOT NULL DEFAULT '{}',
            policy_decision TEXT NOT NULL,
            confirmation_required INTEGER NOT NULL DEFAULT 0,
            accepted_state TEXT NOT NULL DEFAULT 'unknown',
            execution_status TEXT NOT NULL DEFAULT 'pending',
            approval_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_command_outputs (
            id TEXT PRIMARY KEY,
            command_event_id TEXT NOT NULL,
            output_safe TEXT NOT NULL DEFAULT '',
            output_hash TEXT NOT NULL,
            device_state TEXT NOT NULL DEFAULT 'unknown',
            dlp_categories_json TEXT NOT NULL DEFAULT '[]',
            recording_offset_start INTEGER,
            recording_offset_end INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (command_event_id) REFERENCES pam_command_events(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_policy_events (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            command_event_id TEXT,
            event_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            actor_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_privilege_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            from_mode TEXT,
            to_mode TEXT,
            actor_id TEXT,
            evidence_safe TEXT,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pam_recordings (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            storage_uri TEXT,
            sha256 TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            retention_until TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """,
    ]
    for statement in statements:
        cursor.execute(statement)


def _create_indexes(cursor) -> None:
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_ai_security_audits_tenant_created ON ai_outbound_audits(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_security_incidents_status ON ai_security_incidents(status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation ON ai_messages(conversation_id, sequence_no)",
        "CREATE INDEX IF NOT EXISTS ix_ai_tasks_tenant_state ON ai_tasks(tenant_id, state, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_tool_calls_task ON ai_tool_calls(task_id, step_no)",
        "CREATE INDEX IF NOT EXISTS ix_ai_evidence_task ON ai_evidence(task_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS ix_topology_nodes_tenant_type ON topology_nodes(tenant_id, node_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_topology_edges_tenant_status ON topology_edges(tenant_id, status, relation_type)",
        "CREATE INDEX IF NOT EXISTS ix_topology_edge_evidence_edge ON topology_edge_evidence(edge_id, observed_at)",
        "CREATE INDEX IF NOT EXISTS ix_topology_change_events_entity ON topology_change_events(entity_type, entity_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_alert_states_rule_target ON alert_rule_states(rule_id, target_key)",
        "CREATE INDEX IF NOT EXISTS ix_alert_activity_alert ON alert_activity(alert_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_alert_correlations_root ON alert_correlations(root_alert_id, confidence)",
        "CREATE INDEX IF NOT EXISTS ix_alert_storms_tenant_window ON alert_storms(tenant_id, window_start, status)",
        "CREATE INDEX IF NOT EXISTS ix_pam_operation_tenant_created ON pam_operation_events(tenant_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_pam_command_session_index ON pam_command_events(session_id, command_index)",
        "CREATE INDEX IF NOT EXISTS ix_pam_command_outputs_event ON pam_command_outputs(command_event_id)",
        "CREATE INDEX IF NOT EXISTS ix_pam_policy_session ON pam_policy_events(session_id, created_at)",
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
    ]
    for statement in indexes:
        cursor.execute(statement)


def _seed_capabilities(cursor) -> None:
    timestamp = "CURRENT_TIMESTAMP"
    for model_code, thinking in (("deepseek-v4-flash", 0), ("deepseek-v4-pro", 1)):
        cursor.execute(
            f"""
            INSERT INTO ai_model_capabilities (
                model_code, provider_type, thinking_supported, tool_call_supported,
                json_supported, stream_supported, max_context_tokens,
                max_output_tokens, contract_version, updated_at
            )
            SELECT ?, 'deepseek', ?, 1, 1, 1, 131072, 8192, 'nxa.ai.v1', {timestamp}
            WHERE NOT EXISTS (SELECT 1 FROM ai_model_capabilities WHERE model_code = ?)
            """,
            (model_code, thinking, model_code),
        )
    # Existing installations may have been seeded with the pre-V4 names.
    # Migrate the identifiers rather than leaving an old model as default.
    # ``ai_model`` belongs to the baseline schema. Guard the compatibility
    # update so a standalone fresh-database migration remains runnable.
    ai_model_columns = _columns(cursor, "ai_model", True)
    if {"model_code", "name", "thinking_supported"}.issubset(ai_model_columns):
        cursor.execute(
            "UPDATE ai_model SET model_code = 'deepseek-v4-flash', name = 'DeepSeek V4 Flash', thinking_supported = 0 WHERE lower(model_code) = 'deepseek-chat'"
        )
        cursor.execute(
            "UPDATE ai_model SET model_code = 'deepseek-v4-pro', name = 'DeepSeek V4 Pro', thinking_supported = 1 WHERE lower(model_code) = 'deepseek-reasoner'"
        )


def upgrade(cursor, use_pg: bool) -> None:
    _create_tables(cursor)
    # These additions are compatible with old installations where the
    # bootstrap table already exists. They are metadata only; raw payloads are
    # intentionally not added to any audit table.
    _ensure_columns(cursor, "alert_events", {
        "pending_since": "TEXT",
        "recovery_since": "TEXT",
        "resolve_type": "TEXT",
        "flap_count": "INTEGER DEFAULT 0",
        "is_suppressed": "INTEGER DEFAULT 0",
        "suppression_type": "TEXT",
        "suppressed_by_alert_id": "TEXT",
        "root_alert_id": "TEXT",
        "correlation_id": "TEXT",
        "correlation_confidence": "REAL DEFAULT 0",
        "storm_id": "TEXT",
        "suggested_severity": "TEXT",
        "impact_score": "REAL DEFAULT 0",
        "rule_version": "INTEGER",
    }, use_pg)
    _ensure_columns(cursor, "alert_silences", {
        "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
    }, use_pg)
    _ensure_columns(cursor, "ai_knowledge_base", {
        "tenant_id": "TEXT DEFAULT 'tenant-default'",
        "acl_json": "TEXT DEFAULT '{}'",
    }, use_pg)
    _ensure_columns(cursor, "ai_agent_run", {
        "max_steps": "INTEGER DEFAULT 6",
        "max_tool_calls": "INTEGER DEFAULT 12",
        "deadline_at": "TEXT",
        "cancel_requested": "INTEGER DEFAULT 0",
    }, use_pg)
    _ensure_columns(cursor, "ai_document", {
        "tenant_id": "TEXT DEFAULT 'tenant-default'",
        "acl_json": "TEXT DEFAULT '{}'",
        "source_trust_level": "TEXT DEFAULT 'internal'",
        "knowledge_source_type": "TEXT DEFAULT 'user_document'",
        "metadata_json": "TEXT DEFAULT '{}'",
    }, use_pg)
    _ensure_columns(cursor, "pam_sessions", {
        "tenant_id": "TEXT DEFAULT 'tenant-default'",
        "source_type": "TEXT DEFAULT 'interactive'",
        "platform_user_id": "TEXT",
        "device_account_id": "TEXT",
        "recording_id": "TEXT",
        "last_event_hash": "TEXT",
    }, use_pg)
    _ensure_columns(cursor, "topology_edges", {
        "existence_confidence": "REAL DEFAULT 0",
    }, use_pg)
    _ensure_columns(cursor, "pam_command_events", {
        "accepted_state": "TEXT DEFAULT 'unknown'",
        "execution_status": "TEXT DEFAULT 'pending'",
    }, use_pg)
    _ensure_columns(cursor, "pam_change_transactions", {
        "target_type": "TEXT",
        "target_name": "TEXT",
        "config_diff_id": "TEXT",
        "verification_state": "TEXT DEFAULT 'pending'",
        "rollback_state": "TEXT DEFAULT 'not_requested'",
        "commit_model": "TEXT DEFAULT 'direct'",
    }, use_pg)
    _create_indexes(cursor)
    if {"tenant_id", "created_at"}.issubset(_columns(cursor, "pam_sessions", use_pg)):
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_pam_sessions_tenant_created ON pam_sessions(tenant_id, created_at)")
    if _columns(cursor, "ai_document", use_pg):
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_documents_scope ON ai_document(tenant_id, status, vendor, platform)")
    _seed_capabilities(cursor)
    cursor.execute(
        "INSERT INTO ai_kill_switch (id, enabled, reason, changed_at) SELECT 1, 0, 'default-deny until explicitly enabled', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM ai_kill_switch WHERE id = 1)"
    )
