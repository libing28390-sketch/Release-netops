"""Repair PAM control-plane tables omitted from an already-applied m0105."""

from __future__ import annotations

from importlib import import_module

VERSION = 107
NAME = "repair_pam_control_plane_tables"


def upgrade(cursor, use_pg: bool) -> None:
    # Keep the table contract in one place.  m0106 contains the same
    # idempotent creation helper used for fresh installs; importing it here
    # lets an already-applied m0106 receive the later table repair without
    # rewriting migration history.
    previous = import_module(
        f"{__package__}.m0106_repair_post_105_compatibility"
    )
    previous._create_missing_pam_tables(cursor)

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
