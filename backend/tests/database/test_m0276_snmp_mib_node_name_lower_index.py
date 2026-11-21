from __future__ import annotations

import json

import database
from database.migrations import m0276_snmp_mib_node_name_lower_index as migration


INDEX_NAME = "idx_snmp_mib_nodes_name_lower"


def test_m0276_fresh_schema_and_migration_support_case_insensitive_lookup(isolated_db):
    connection = database.get_db_connection()
    try:
        fresh_index = connection.execute(
            """SELECT pg_get_indexdef(index_class.oid)
                 FROM pg_class AS index_class
                 JOIN pg_namespace AS index_namespace
                   ON index_namespace.oid = index_class.relnamespace
                WHERE index_namespace.nspname = current_schema()
                  AND index_class.relname = ?""",
            (INDEX_NAME,),
        ).fetchone()
        assert fresh_index is not None
        assert "lower(node_name)" in str(fresh_index[0]).lower()

        connection.execute(f"DROP INDEX {INDEX_NAME}")
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        index_definition = connection.execute(
            """SELECT pg_get_indexdef(index_class.oid)
                 FROM pg_class AS index_class
                 JOIN pg_namespace AS index_namespace
                   ON index_namespace.oid = index_class.relnamespace
                WHERE index_namespace.nspname = current_schema()
                  AND index_class.relname = ?""",
            (INDEX_NAME,),
        ).fetchone()
        assert index_definition is not None
        assert "lower(node_name)" in str(index_definition[0]).lower()

        created_at = "2026-10-07T00:00:00+00:00"
        connection.execute(
            """INSERT INTO snmp_mibs
               (id, name, vendor, filename, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "m0276-plan-test-mib",
                "m0276 synthetic planner fixture",
                "Huawei",
                "m0276-plan-test.mib",
                created_at,
                created_at,
            ),
        )
        connection.execute(
            """INSERT INTO snmp_mib_nodes (id, mib_id, node_name, oid, created_at)
               SELECT 'm0276-plan-node-' || node_number::text,
                      'm0276-plan-test-mib',
                      CASE WHEN node_number = 1 THEN 'ifName'
                           ELSE 'syntheticNode' || node_number::text END,
                      '1.3.6.1.2.1.2.2.1.' || node_number::text,
                      ?
                 FROM generate_series(1, 30000) AS generated(node_number)""",
            (created_at,),
        )
        connection.commit()
        connection.execute("ANALYZE snmp_mibs")
        connection.execute("ANALYZE snmp_mib_nodes")
        connection.commit()

        plan_row = connection.execute(
            """
            EXPLAIN (FORMAT JSON)
            SELECT n.oid, m.vendor, n.node_name
              FROM snmp_mib_nodes n
              JOIN snmp_mibs m ON m.id = n.mib_id
             WHERE m.is_active = 1 AND LOWER(n.node_name) = LOWER(?)
               AND TRIM(COALESCE(n.oid, '')) <> ''
             ORDER BY CASE WHEN LOWER(TRIM(COALESCE(m.vendor, ''))) = LOWER(?) THEN 0
                           WHEN LOWER(TRIM(COALESCE(m.vendor, ''))) = 'standard' THEN 1
                           ELSE 2 END,
                      m.name
             LIMIT 8
            """,
            ("ifName", "huawei"),
        ).fetchone()
        assert plan_row is not None
        plan_document = plan_row[0]
        if isinstance(plan_document, str):
            plan_document = json.loads(plan_document)

        plan_nodes = [plan_document[0]["Plan"]]
        uses_expression_index = False
        while plan_nodes:
            plan_node = plan_nodes.pop()
            if plan_node.get("Index Name") == INDEX_NAME:
                uses_expression_index = True
                break
            plan_nodes.extend(plan_node.get("Plans", []))

        assert uses_expression_index, plan_document
    finally:
        connection.close()
