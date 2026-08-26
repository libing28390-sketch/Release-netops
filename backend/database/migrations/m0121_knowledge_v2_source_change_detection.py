"""Add durable, append-only official-source change detection for ING-019.

Refresh observations are audit evidence rather than mutable state.  This
migration extends the ING-018 timeline with explicit removal, replacement and
version-update signals, then protects the evidence boundary even for callers
that bypass the service layer.  A referenced source version must be the exact
tenant/source/hash/byte-size fact recorded by ``kb_source_version``.
"""

from __future__ import annotations


VERSION = 121
NAME = "knowledge_v2_source_change_detection"


_COLUMNS = {
    "detection_type": "TEXT NOT NULL DEFAULT 'none' CHECK (detection_type IN ('none','removed','replacement','version_updated'))",
    "replacement_url": "TEXT NOT NULL DEFAULT ''",
    "version_signal_json": "JSONB NOT NULL DEFAULT '{}'::jsonb",
}


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    if use_pg:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = %s)",
            (table,),
        )
        return bool(cursor.fetchone()[0])
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,))
    return cursor.fetchone() is not None


def _table_columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        )
        return {str(row[0]) for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cursor.fetchall()}


def _add_detection_columns(cursor, use_pg: bool) -> None:
    existing = _table_columns(cursor, "kb_source_refresh_observation", use_pg)
    for name, definition in _COLUMNS.items():
        if name in existing:
            continue
        if not use_pg and name == "version_signal_json":
            definition = "TEXT NOT NULL DEFAULT '{}'"
        if use_pg:
            cursor.execute(
                f"ALTER TABLE kb_source_refresh_observation ADD COLUMN IF NOT EXISTS {name} {definition}"
            )
        else:
            cursor.execute(f"ALTER TABLE kb_source_refresh_observation ADD COLUMN {name} {definition}")


def _create_pg_guards(cursor) -> None:
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION kb_source_refresh_observation_append_only_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'kb_source_refresh_observation_append_only';
        END;
        $$
        """
    )
    cursor.execute("DROP TRIGGER IF EXISTS trg_kb_source_refresh_observation_append_only ON kb_source_refresh_observation")
    cursor.execute(
        """
        CREATE TRIGGER trg_kb_source_refresh_observation_append_only
        BEFORE UPDATE OR DELETE ON kb_source_refresh_observation
        FOR EACH ROW EXECUTE FUNCTION kb_source_refresh_observation_append_only_guard()
        """
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION kb_source_refresh_observation_insert_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF jsonb_typeof(NEW.version_signal_json) <> 'object' THEN
                RAISE EXCEPTION 'kb_source_refresh_observation_version_signal_must_be_object';
            END IF;
            IF (NEW.detection_type = 'replacement') <> (btrim(NEW.replacement_url) <> '') THEN
                RAISE EXCEPTION 'kb_source_refresh_observation_replacement_shape_invalid';
            END IF;
            IF NEW.detection_type = 'version_updated'
               AND NEW.version_signal_json = '{}'::jsonb THEN
                RAISE EXCEPTION 'kb_source_refresh_observation_version_signal_required';
            END IF;
            IF NEW.source_version_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM kb_source_version AS version
                   WHERE version.id = NEW.source_version_id
                     AND version.tenant_id = NEW.tenant_id
                     AND version.source_registry_id = NEW.source_registry_id
                     AND version.content_hash = NEW.content_hash
                     AND version.byte_size = NEW.byte_size
               ) THEN
                RAISE EXCEPTION 'kb_source_refresh_observation_source_version_mismatch';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    cursor.execute("DROP TRIGGER IF EXISTS trg_kb_source_refresh_observation_insert_guard ON kb_source_refresh_observation")
    cursor.execute(
        """
        CREATE TRIGGER trg_kb_source_refresh_observation_insert_guard
        BEFORE INSERT ON kb_source_refresh_observation
        FOR EACH ROW EXECUTE FUNCTION kb_source_refresh_observation_insert_guard()
        """
    )


def _create_sqlite_guards(cursor) -> None:
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_kb_source_refresh_observation_append_only_update
        BEFORE UPDATE ON kb_source_refresh_observation
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'kb_source_refresh_observation_append_only');
        END
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_kb_source_refresh_observation_append_only_delete
        BEFORE DELETE ON kb_source_refresh_observation
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'kb_source_refresh_observation_append_only');
        END
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_kb_source_refresh_observation_insert_guard
        BEFORE INSERT ON kb_source_refresh_observation
        FOR EACH ROW
        WHEN
            CASE
                WHEN json_valid(NEW.version_signal_json) = 0 THEN 1
                WHEN json_type(NEW.version_signal_json) <> 'object' THEN 1
                WHEN (NEW.detection_type = 'replacement') <> (trim(NEW.replacement_url) <> '') THEN 1
                WHEN NEW.detection_type = 'version_updated' AND json(NEW.version_signal_json) = json('{}') THEN 1
                WHEN NEW.source_version_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM kb_source_version AS version
                    WHERE version.id = NEW.source_version_id
                      AND version.tenant_id = NEW.tenant_id
                      AND version.source_registry_id = NEW.source_registry_id
                      AND version.content_hash = NEW.content_hash
                      AND version.byte_size = NEW.byte_size
                ) THEN 1
                ELSE 0
            END
        BEGIN
            SELECT RAISE(ABORT, 'kb_source_refresh_observation_insert_invariant');
        END
        """
    )


def _create_change_action_table(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ" if use_pg else "TEXT"
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_source_change_action (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            refresh_observation_id TEXT NOT NULL,
            source_registry_id TEXT NOT NULL,
            detection_type TEXT NOT NULL CHECK (detection_type IN ('removed','replacement','version_updated')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','applying','applied','failed')),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error_code TEXT NOT NULL DEFAULT '',
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            applied_at {time_type},
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            applied_by TEXT NOT NULL DEFAULT '',
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, refresh_observation_id),
            FOREIGN KEY (tenant_id, refresh_observation_id)
                REFERENCES kb_source_refresh_observation(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, source_registry_id)
                REFERENCES kb_source_registry(tenant_id, id)
                ON UPDATE RESTRICT ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_source_change_action_pending "
        "ON kb_source_change_action(tenant_id, status, created_at)"
    )


def _create_pg_change_action_guard(cursor) -> None:
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION kb_source_change_action_scope_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM kb_source_refresh_observation AS observation
                WHERE observation.id = NEW.refresh_observation_id
                  AND observation.tenant_id = NEW.tenant_id
                  AND observation.source_registry_id = NEW.source_registry_id
                  AND observation.detection_type = NEW.detection_type
            ) THEN
                RAISE EXCEPTION 'kb_source_change_action_observation_scope_mismatch';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    cursor.execute("DROP TRIGGER IF EXISTS trg_kb_source_change_action_scope ON kb_source_change_action")
    cursor.execute(
        """
        CREATE TRIGGER trg_kb_source_change_action_scope
        BEFORE INSERT OR UPDATE ON kb_source_change_action
        FOR EACH ROW EXECUTE FUNCTION kb_source_change_action_scope_guard()
        """
    )


def _create_sqlite_change_action_guard(cursor) -> None:
    for name, operation in (
        ("trg_kb_source_change_action_scope_insert", "INSERT"),
        ("trg_kb_source_change_action_scope_update", "UPDATE"),
    ):
        cursor.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {name}
            BEFORE {operation} ON kb_source_change_action
            FOR EACH ROW
            WHEN NOT EXISTS (
                SELECT 1
                FROM kb_source_refresh_observation AS observation
                WHERE observation.id = NEW.refresh_observation_id
                  AND observation.tenant_id = NEW.tenant_id
                  AND observation.source_registry_id = NEW.source_registry_id
                  AND observation.detection_type = NEW.detection_type
            )
            BEGIN
                SELECT RAISE(ABORT, 'kb_source_change_action_observation_scope_mismatch');
            END
            """
        )


def _create_document_index(cursor, use_pg: bool) -> None:
    if not _table_exists(cursor, "kb_document", use_pg):
        return
    columns = _table_columns(cursor, "kb_document", use_pg)
    if {"tenant_id", "source_registry_id", "lifecycle_status"} <= columns:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_kb_document_source_lifecycle "
            "ON kb_document(tenant_id, source_registry_id, lifecycle_status)"
        )


def upgrade(cursor, use_pg: bool) -> None:
    # m0120 is the immediate predecessor.  Fail closed rather than synthesizing
    # a partial observation table: the runner will not mark this migration
    # applied and can safely retry after the predecessor is restored.
    if not _table_exists(cursor, "kb_source_refresh_observation", use_pg):
        raise RuntimeError("m0121 requires m0120 kb_source_refresh_observation")
    _add_detection_columns(cursor, use_pg)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_source_refresh_detection "
        "ON kb_source_refresh_observation(tenant_id, detection_type, checked_at DESC)"
    )
    if use_pg:
        _create_pg_guards(cursor)
    else:
        _create_sqlite_guards(cursor)
    _create_change_action_table(cursor, use_pg)
    if use_pg:
        _create_pg_change_action_guard(cursor)
    else:
        _create_sqlite_change_action_guard(cursor)
    _create_document_index(cursor, use_pg)


def downgrade(cursor, use_pg: bool) -> None:
    # Detection observations are audit evidence; rollback disables the writer
    # rather than deleting history or rewriting immutable source facts.
    return None
