from __future__ import annotations

import pytest

from backend.tests.pg_test_utils import postgresql_test_driver
from database import get_db_connection
from database.migrations import build_migration_plan
from database.migrations.m0302_asset_chassis_members import upgrade as upgrade_m0302
from database.migrations.m0305_asset_chassis_dynamic_indexes import upgrade


def _reject_insert(connection, sql: str, values: tuple[object, ...], savepoint: str) -> None:
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        with pytest.raises(postgresql_test_driver.IntegrityError):
            connection.execute(sql, values)
    finally:
        connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def test_m0305_replaces_only_the_fixed_index_check_and_preserves_data(isolated_db):
    connection = get_db_connection()
    asset_id = "m0305-dynamic-entity-index"
    insert_sql = """
        INSERT INTO asset_chassis_members
            (asset_id, entity_index, serial_number, collected_at)
        VALUES (?, ?, ?, now())
    """
    try:
        connection.execute("DROP TABLE asset_chassis_members")
        # Build the old deployed shape from its versioned migration, rather
        # than relying on whichever schema happens to be in a developer DB.
        upgrade_m0302(connection.cursor(), use_pg=True)
        connection.execute(
            "ALTER TABLE asset_chassis_members "
            "ADD CONSTRAINT ck_asset_chassis_members_serial_not_forbidden "
            "CHECK (serial_number <> 'forbidden')"
        )
        connection.execute(
            "INSERT INTO physical_assets (id, created_at, updated_at) VALUES (?, ?, ?)",
            (asset_id, "2026-11-02T00:00:00+00:00", "2026-11-02T00:00:00+00:00"),
        )
        for entity_index in (1, 2, 3):
            connection.execute(
                insert_sql,
                (asset_id, entity_index, f"legacy-serial-{entity_index}"),
            )
        connection.commit()

        old_check = connection.execute(
            """SELECT conname, pg_get_constraintdef(oid, true)
                 FROM pg_constraint
                WHERE conrelid = 'asset_chassis_members'::regclass
                  AND contype = 'c'
                  AND pg_get_expr(conbin, conrelid) LIKE '%entity_index%'"""
        ).fetchall()
        # PostgreSQL generates this name for m0302's unnamed, column-level CHECK.
        assert [row[0] for row in old_check] == [
            "asset_chassis_members_entity_index_check"
        ]
        assert "entity_index" in old_check[0][1]

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        plan = build_migration_plan(connection, use_pg=True)
        assert 305 in plan.discovered_versions

        constraints = connection.execute(
            """SELECT conname, contype, pg_get_constraintdef(oid, true)
                 FROM pg_constraint
                WHERE conrelid = 'asset_chassis_members'::regclass
                ORDER BY contype, conname"""
        ).fetchall()
        constraint_map = {str(row[0]): (str(row[1]), str(row[2])) for row in constraints}
        assert "asset_chassis_members_entity_index_check" not in constraint_map
        assert constraint_map[_positive_constraint_name()][0] == "c"
        assert "CHECK (entity_index > 0)" in constraint_map[_positive_constraint_name()][1]
        assert constraint_map["ck_asset_chassis_members_serial_not_forbidden"][0] == "c"
        assert "serial_number <> 'forbidden'" in constraint_map[
            "ck_asset_chassis_members_serial_not_forbidden"
        ][1]

        primary_keys = [definition for _name, kind, definition in constraints if kind == "p"]
        foreign_keys = [definition for _name, kind, definition in constraints if kind == "f"]
        assert primary_keys == ["PRIMARY KEY (asset_id, entity_index)"]
        assert foreign_keys == [
            "FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE"
        ]

        for entity_index in (4, 2_147_483_647):
            connection.execute(
                insert_sql,
                (asset_id, entity_index, f"dynamic-serial-{entity_index}"),
            )
        connection.commit()

        rows = connection.execute(
            """SELECT entity_index, serial_number
                 FROM asset_chassis_members
                WHERE asset_id = ?
                ORDER BY entity_index""",
            (asset_id,),
        ).fetchall()
        assert [(row[0], row[1]) for row in rows] == [
            (1, "legacy-serial-1"),
            (2, "legacy-serial-2"),
            (3, "legacy-serial-3"),
            (4, "dynamic-serial-4"),
            (2_147_483_647, "dynamic-serial-2147483647"),
        ]

        for entity_index, savepoint in ((0, "m0305_zero"), (-1, "m0305_negative")):
            _reject_insert(
                connection,
                insert_sql,
                (asset_id, entity_index, "invalid-index"),
                savepoint,
            )

        _reject_insert(
            connection,
            insert_sql,
            (asset_id, 5, "forbidden"),
            "m0305_other_check",
        )
        _reject_insert(
            connection,
            insert_sql,
            ("m0305-missing-asset", 6, "missing-fk"),
            "m0305_foreign_key",
        )
        _reject_insert(
            connection,
            insert_sql,
            (asset_id, 1, "duplicate-pk"),
            "m0305_primary_key",
        )
    finally:
        connection.close()


def _positive_constraint_name() -> str:
    return "ck_asset_chassis_members_entity_index_positive"
