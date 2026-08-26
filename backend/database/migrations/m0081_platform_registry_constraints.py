"""Complete P0 referential, status and current-release constraints."""

from __future__ import annotations


VERSION = 81
NAME = "platform_registry_constraints"


def _constraint_exists(cursor, table: str, name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname = ? AND c.conname = ?",
        (table, name),
    ).fetchone()
    return bool(row)


def _add_pg_constraint(cursor, table: str, name: str, definition: str) -> None:
    if not _constraint_exists(cursor, table, name):
        cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition} NOT VALID")


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_devices_platform_profile ON devices(platform_profile_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_platform_profiles_current_release ON platform_profiles(current_release_id)")
    # Repair pre-constraint databases deterministically before adding the
    # one-published-release invariant.  Prefer the profile pointer, otherwise
    # retain the newest release number.
    for profile in cursor.execute("SELECT id, current_release_id FROM platform_profiles").fetchall():
        published = cursor.execute(
            "SELECT id FROM platform_releases WHERE profile_id = ? AND status = 'PUBLISHED' ORDER BY release_number DESC",
            (profile[0],),
        ).fetchall()
        if len(published) <= 1:
            continue
        ids = [row[0] for row in published]
        keep = profile[1] if profile[1] in ids else ids[0]
        cursor.execute(
            "UPDATE platform_releases SET status = 'DEPRECATED' WHERE profile_id = ? AND status = 'PUBLISHED' AND id <> ?",
            (profile[0], keep),
        )
        cursor.execute("UPDATE platform_profiles SET current_release_id = ? WHERE id = ?", (keep, profile[0]))
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_releases_one_published ON platform_releases(profile_id) WHERE status = 'PUBLISHED'")

    if use_pg:
        _add_pg_constraint(
            cursor,
            "devices",
            "fk_devices_platform_profile",
            "FOREIGN KEY (platform_profile_id) REFERENCES platform_profiles(id) ON DELETE SET NULL",
        )
        _add_pg_constraint(
            cursor,
            "platform_profiles",
            "fk_platform_profiles_current_release",
            "FOREIGN KEY (current_release_id) REFERENCES platform_releases(id) ON DELETE SET NULL",
        )
        _add_pg_constraint(
            cursor,
            "platform_releases",
            "ck_platform_releases_status",
            "CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'DEPRECATED'))",
        )
        return

    # SQLite cannot add a foreign key to an existing table without rebuilding
    # the full legacy schema.  These equivalent triggers enforce the same
    # invariant for all new writes while keeping old installations upgradeable.
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_devices_platform_profile_fk_insert
           BEFORE INSERT ON devices
           WHEN NEW.platform_profile_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM platform_profiles WHERE id = NEW.platform_profile_id)
           BEGIN SELECT RAISE(ABORT, 'invalid devices.platform_profile_id'); END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_devices_platform_profile_fk_update
           BEFORE UPDATE OF platform_profile_id ON devices
           WHEN NEW.platform_profile_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM platform_profiles WHERE id = NEW.platform_profile_id)
           BEGIN SELECT RAISE(ABORT, 'invalid devices.platform_profile_id'); END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_profiles_current_release_fk
           BEFORE UPDATE OF current_release_id ON platform_profiles
           WHEN NEW.current_release_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM platform_releases WHERE id = NEW.current_release_id)
           BEGIN SELECT RAISE(ABORT, 'invalid platform_profiles.current_release_id'); END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_releases_status_check_insert
           BEFORE INSERT ON platform_releases
           WHEN NEW.status NOT IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'DEPRECATED')
           BEGIN SELECT RAISE(ABORT, 'invalid platform_releases.status'); END"""
    )
    cursor.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_releases_status_check_update
           BEFORE UPDATE OF status ON platform_releases
           WHEN NEW.status NOT IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'PUBLISHED', 'DEPRECATED')
           BEGIN SELECT RAISE(ABORT, 'invalid platform_releases.status'); END"""
    )
