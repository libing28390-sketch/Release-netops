from __future__ import annotations

from database import get_db_connection
from database.migrations import run_migrations
from database.schema import _init_db_logic


_M0313_TO_0319_TABLES = (
    "cmdb_device_interface_address_observations",
    "ipam_endpoint_collection_states",
    "ipam_current_endpoint_observations",
    "ipam_current_fdb_observations",
    "ipam_current_fhrp_collection_states",
    "ipam_current_fhrp_observations",
    "ipam_fhrp_groups",
    "ipam_fhrp_group_members",
    "ipam_fhrp_group_vips",
)


def _migration_catalog_snapshot(conn, tables: tuple[str, ...]) -> dict[str, tuple]:
    snapshot = {}
    for table in tables:
        columns = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT column_name, data_type, is_nullable, column_default
                     FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = ?
                    ORDER BY column_name""",
                (table,),
            ).fetchall()
        )
        constraints = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT conname, pg_get_constraintdef(oid), convalidated
                     FROM pg_constraint
                    WHERE conrelid = to_regclass(?)
                    ORDER BY conname""",
                (table,),
            ).fetchall()
        )
        indexes = tuple(
            tuple(row)
            for row in conn.execute(
                """SELECT indexname, indexdef
                     FROM pg_indexes
                    WHERE schemaname = current_schema() AND tablename = ?
                    ORDER BY indexname""",
                (table,),
            ).fetchall()
        )
        snapshot[table] = (columns, constraints, indexes)
    return snapshot


def test_m0313_to_m0319_non_vrf_startup_chain_is_catalog_idempotent(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        original_catalog = _migration_catalog_snapshot(conn, _M0313_TO_0319_TABLES)
        conn.execute("DELETE FROM schema_migrations WHERE version BETWEEN 313 AND 319")
        conn.commit()

        # Match application startup: the monolithic baseline runs before the
        # versioned migrations and owns some base columns/indexes.
        _init_db_logic(conn, allow_legacy_import=False)
        conn.commit()

        assert run_migrations(conn, use_pg=True, strict_history=True) == 7
        upgraded_catalog = _migration_catalog_snapshot(conn, _M0313_TO_0319_TABLES)
        assert run_migrations(conn, use_pg=True, strict_history=True) == 0
        repeated_catalog = _migration_catalog_snapshot(conn, _M0313_TO_0319_TABLES)
        applied_versions = [
            int(row["version"])
            for row in conn.execute(
                """SELECT version FROM schema_migrations
                     WHERE version BETWEEN 313 AND 319 ORDER BY version"""
            ).fetchall()
        ]
        conn.commit()

    assert applied_versions == list(range(313, 320))
    assert original_catalog == upgraded_catalog == repeated_catalog
