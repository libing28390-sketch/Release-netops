"""Add get_startup_config action definition, TFTP policy settings, and config_type metadata."""

from __future__ import annotations


VERSION = 153
NAME = "config_backup_tftp_and_startup"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    # The action catalog uses the registry's canonical columns
    # (risk_level/consumers_json/field_types_json), not the older ad-hoc names
    # used by the original version of this migration.  Keep this guarded for
    # isolated compatibility tests that intentionally omit registry tables.
    if _columns(cursor, "action_definitions", use_pg):
        from database.migrations.m0072_platform_registry_p0 import (
            _seed_action_definitions,
        )

        _seed_action_definitions(cursor)

    # 1. Add columns to config_snapshots
    snapshot_cols = _columns(cursor, "config_snapshots", use_pg)
    if "config_type" not in snapshot_cols:
        cursor.execute("ALTER TABLE config_snapshots ADD COLUMN config_type TEXT DEFAULT 'running'")
    if "has_unsaved_changes" not in snapshot_cols:
        cursor.execute("ALTER TABLE config_snapshots ADD COLUMN has_unsaved_changes INTEGER DEFAULT 0")
    if "unsaved_diff_summary" not in snapshot_cols:
        cursor.execute("ALTER TABLE config_snapshots ADD COLUMN unsaved_diff_summary TEXT DEFAULT ''")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_snapshots_dev_type_ts "
        "ON config_snapshots(device_id, config_type, timestamp DESC)"
    )

    # 2. Add columns to config_backup_policies
    policy_cols = _columns(cursor, "config_backup_policies", use_pg)
    if "collect_startup_config" not in policy_cols:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN collect_startup_config INTEGER DEFAULT 0")
    if "tftp_enabled" not in policy_cols:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_enabled INTEGER DEFAULT 0")
    if "tftp_server" not in policy_cols:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_server TEXT DEFAULT ''")
    if "tftp_port" not in policy_cols:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_port INTEGER DEFAULT 69")
    if "tftp_path_prefix" not in policy_cols:
        cursor.execute("ALTER TABLE config_backup_policies ADD COLUMN tftp_path_prefix TEXT DEFAULT 'backups'")

    # 3. Add columns to config_backup_runs
    runs_cols = _columns(cursor, "config_backup_runs", use_pg)
    if "tftp_status" not in runs_cols:
        cursor.execute("ALTER TABLE config_backup_runs ADD COLUMN tftp_status TEXT DEFAULT 'none'")
    if "tftp_server" not in runs_cols:
        cursor.execute("ALTER TABLE config_backup_runs ADD COLUMN tftp_server TEXT DEFAULT ''")
    if "tftp_log" not in runs_cols:
        cursor.execute("ALTER TABLE config_backup_runs ADD COLUMN tftp_log TEXT DEFAULT ''")
    if "tftp_uploaded_count" not in runs_cols:
        cursor.execute("ALTER TABLE config_backup_runs ADD COLUMN tftp_uploaded_count INTEGER DEFAULT 0")
