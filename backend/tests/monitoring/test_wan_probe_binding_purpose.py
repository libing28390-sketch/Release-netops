from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _seed_link_and_targets():
    from database import get_db_connection

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, tenant_id, role, device_category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("purpose-device", "purpose-edge", "192.0.2.20", "site-purpose", "tenant-purpose", "edge", "router"),
        )
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, if_index, speed, oper_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("purpose-interface", "purpose-device", "GigabitEthernet0/0", 8, 1_000_000_000, "up"),
        )
        conn.execute(
            """INSERT INTO wan_links
                (id, link_name, site_id, site_name, device_id, interface_id, interface_name,
                 if_index, tenant_id, contracted_download_bps, contracted_upload_bps, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("purpose-link", "Purpose link", "site-purpose", "Purpose", "purpose-device", "purpose-interface", "GigabitEthernet0/0", 8, "tenant-purpose", 100_000_000, 50_000_000, now, now),
        )
        targets = (
            ("purpose-icmp", "ICMP target", "198.51.100.1", 0, "ICMP_PING"),
            ("purpose-http", "HTTP target", "example.com", 443, "HTTPS_GET"),
            ("purpose-tcp", "TCP target", "198.51.100.2", 443, "TCP_CONNECT"),
        )
        for target_id, name, host, port, probe_type in targets:
            conn.execute(
                """INSERT INTO outbound_probe_targets
                    (id, target_name, host, port, probe_type, is_active, enabled, group_name,
                     url, expected_status_code, expected_keyword, timeout_ms, tenant_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, TRUE, TRUE, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (target_id, name, host, port, probe_type, "purpose", "", 200, "", 2000, "tenant-purpose", now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _actor() -> dict[str, str]:
    return {"id": "purpose-operator", "username": "purpose-operator", "tenant_id": "tenant-purpose"}


def test_probe_binding_purpose_defaults_and_lists(isolated_db):
    _seed_link_and_targets()
    from services.wan_p2_service import list_probe_bindings, upsert_probe_binding

    default_binding = upsert_probe_binding(
        {"link_id": "purpose-link", "target_id": "purpose-icmp"}, _actor()
    )
    quality_binding = upsert_probe_binding(
        {"link_id": "purpose-link", "target_id": "purpose-icmp", "purpose": "quality"}, _actor()
    )
    application_binding = upsert_probe_binding(
        {"link_id": "purpose-link", "target_id": "purpose-http", "purpose": "application"}, _actor()
    )

    assert default_binding["purpose"] == "availability"
    assert quality_binding["purpose"] == "quality"
    assert application_binding["purpose"] == "application"
    listed = list_probe_bindings(link_id="purpose-link", tenant_id="tenant-purpose")
    assert {item["purpose"] for item in listed} == {"availability", "quality", "application"}
    assert {item["purpose"] for item in list_probe_bindings(link_id="purpose-link", purpose="quality")} == {"quality"}


def test_probe_binding_purpose_rejects_incompatible_protocols(isolated_db):
    _seed_link_and_targets()
    from services.wan_p2_service import upsert_probe_binding

    with pytest.raises(ValueError, match="quality.*TCP_CONNECT"):
        upsert_probe_binding(
            {"link_id": "purpose-link", "target_id": "purpose-tcp", "purpose": "quality"}, _actor()
        )
    with pytest.raises(ValueError, match="availability.*HTTPS_GET"):
        upsert_probe_binding(
            {"link_id": "purpose-link", "target_id": "purpose-http"}, _actor()
        )


def test_probe_binding_purpose_migration_is_idempotent_and_scoped_unique(isolated_db):
    from database import get_db_connection
    from database.migrations.m0266_wan_probe_binding_purpose import upgrade

    _seed_link_and_targets()
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO wan_probe_bindings (id, link_id, target_id, purpose, created_at, updated_at) VALUES (?, ?, ?, 'availability', ?, ?)",
            ("legacy-http-binding", "purpose-link", "purpose-http", now, now),
        )
        upgrade(conn.cursor(), True)
        conn.commit()
        assert conn.execute("SELECT purpose FROM wan_probe_bindings WHERE id = ?", ("legacy-http-binding",)).fetchone()[0] == "application"
        upgrade(conn.cursor(), True)
        conn.commit()
        columns = {
            str(row[0])
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'wan_probe_bindings'"
            ).fetchall()
        }
        assert "purpose" in columns
        index_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'wan_probe_bindings'"
            ).fetchall()
        }
        assert "uq_wan_probe_bindings_link_target_purpose" in index_names
    finally:
        conn.close()
