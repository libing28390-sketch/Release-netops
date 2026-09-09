from __future__ import annotations

import uuid

import pytest
from psycopg2.errors import CheckViolation

from database.migrations import m0215_ssh_algorithm_profiles as migration


def test_m0215_adds_profile_columns_and_constraints(isolated_db):
    assert migration.VERSION == 215
    conn = isolated_db["module"].get_db_connection()
    try:
        columns = conn.execute(
            """
            SELECT table_name, column_name, column_default, is_nullable
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name IN ('devices', 'physical_assets')
               AND column_name = 'ssh_algorithm_profile'
             ORDER BY table_name
            """
        ).fetchall()
        assert [row["table_name"] for row in columns] == ["devices", "physical_assets"]
        for row in columns:
            assert "auto" in str(row["column_default"])
            assert row["is_nullable"] == "NO"

        constraints = conn.execute(
            """
            SELECT t.table_name, t.constraint_name, c.check_clause
              FROM information_schema.check_constraints c
              JOIN information_schema.table_constraints t
                ON t.constraint_name = c.constraint_name
             WHERE t.table_schema = current_schema()
               AND t.table_name IN ('devices', 'physical_assets')
               AND t.constraint_name LIKE 'ck_%_ssh_algorithm_profile'
             ORDER BY table_name
            """
        ).fetchall()
        assert [row["table_name"] for row in constraints] == ["devices", "physical_assets"]
        assert all("legacy_break_glass" in row["check_clause"] for row in constraints)

        with pytest.raises(CheckViolation):
            conn.execute(
                "INSERT INTO devices (id, ssh_algorithm_profile) VALUES (?, ?)",
                (f"profile-check-{uuid.uuid4().hex[:8]}", "not-a-profile"),
            )
        conn.rollback()
    finally:
        conn.close()
