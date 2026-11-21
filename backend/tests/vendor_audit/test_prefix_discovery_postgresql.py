from __future__ import annotations

from services import prefix_discovery_service as prefix_service


def test_discovered_prefix_persists_text_and_native_cidr_on_postgresql(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices (id, hostname, status, role, tenant_id) VALUES (?, ?, ?, ?, ?)",
            ("device-prefix-pg", "core-prefix-pg", "online", "core", "tenant-default"),
        )

    candidates = prefix_service.build_prefix_candidates({
        "device": {
            "id": "device-prefix-pg",
            "hostname": "core-prefix-pg",
            "tenant_id": "tenant-default",
        },
        "categories": [{
            "key": "interfaces",
            "records": [{
                "INTERFACE": "Loopback0",
                "IP_ADDRESS": "198.51.100.10/32",
            }],
        }],
    })

    first = prefix_service.persist_prefix_candidates(candidates, collection_run_id="prefix-pg-first")
    second = prefix_service.persist_prefix_candidates(candidates, collection_run_id="prefix-pg-second")

    with database.get_db_connection() as conn:
        rows = conn.execute(
            "SELECT prefix, prefix_cidr::text AS prefix_cidr FROM prefixes WHERE prefix = ?",
            ("198.51.100.10/32",),
        ).fetchall()

    assert first["created"] == 1
    assert second["updated"] == 1
    assert [dict(row) for row in rows] == [{
        "prefix": "198.51.100.10/32",
        "prefix_cidr": "198.51.100.10/32",
    }]
