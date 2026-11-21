from __future__ import annotations

import pytest
from fastapi import HTTPException

from database import get_db_connection
from services.snmp_mib_service import (
    MibParser,
    parse_and_store_mib,
    list_mibs,
    list_mibs_page,
    get_mib_repository_stats,
    get_mib_detail,
    delete_mib,
    search_mib_nodes,
)
from services.snmp_preset_service import seed_builtin_mibs
from api.devices import reject_local_snmp_model_presets


@pytest.fixture(autouse=True)
def _isolated_snmp_database(isolated_db):
    """Give repository tests the same fresh schema as the application."""
    yield isolated_db


SAMPLE_TEST_MIB = """
SAMPLE-TEST-MIB DEFINITIONS ::= BEGIN

IMPORTS
    enterprises, Integer32, Gauge32, Counter64 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

sampleCorp OBJECT IDENTIFIER ::= { enterprises 99999 }
sampleDevices OBJECT IDENTIFIER ::= { sampleCorp 1 }
sampleCpuUsage OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The CPU busy utilization ratio."
    ::= { sampleDevices 1 }

sampleMemUsage OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The memory utilization ratio."
    ::= { sampleDevices 2 }

sampleIfOctets OBJECT-TYPE
    SYNTAX      Counter64
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Total high capacity interface octets."
    ::= { sampleDevices 3 }

END
"""


def test_mib_parser_extracts_oids_and_types() -> None:
    parser = MibParser(SAMPLE_TEST_MIB)
    nodes = parser.parse()

    assert parser.module_name == "SAMPLE-TEST-MIB"
    assert len(nodes) == 3

    cpu_node = next(n for n in nodes if n["node_name"] == "sampleCpuUsage")
    assert cpu_node["oid"] == "1.3.6.1.4.1.99999.1.1"
    assert "Gauge32" in cpu_node["syntax_type"]
    assert "CPU busy" in cpu_node["description"]

    mem_node = next(n for n in nodes if n["node_name"] == "sampleMemUsage")
    assert mem_node["oid"] == "1.3.6.1.4.1.99999.1.2"

    octets_node = next(n for n in nodes if n["node_name"] == "sampleIfOctets")
    assert octets_node["oid"] == "1.3.6.1.4.1.99999.1.3"
    assert "Counter64" in octets_node["syntax_type"]


def test_mib_store_and_search_workflow() -> None:
    conn = get_db_connection()
    try:
        res = parse_and_store_mib(
            conn,
            filename="SAMPLE-TEST-MIB.txt",
            raw_text=SAMPLE_TEST_MIB,
            vendor="SampleVendor",
            source_type="user_upload",
            description="Sample Test Corporate MIB",
        )
        conn.commit()

        assert res["name"] == "SAMPLE-TEST-MIB"
        assert res["vendor"] == "SampleVendor"
        assert res["node_count"] == 3

        page, total = list_mibs_page(conn, search="SAMPLE-TEST", page=1, page_size=10)
        assert total >= 1
        assert len(page) <= 10
        assert page[0]["name"] == "SAMPLE-TEST-MIB"
        assert "description" not in page[0]
        vendor_page, vendor_total = list_mibs_page(conn, vendor="samplevendor", page=1, page_size=10)
        assert vendor_total >= 1
        assert all(item["vendor"] == "SampleVendor" for item in vendor_page)
        parsed_page, parsed_total = list_mibs_page(
            conn,
            search="SAMPLE-TEST",
            status="parsed",
            page=1,
            page_size=10,
        )
        assert parsed_total >= 1
        assert parsed_page[0]["name"] == "SAMPLE-TEST-MIB"
        failed_page, failed_total = list_mibs_page(
            conn,
            search="SAMPLE-TEST",
            status="failed",
            page=1,
            page_size=10,
        )
        assert failed_page == []
        assert failed_total == 0
        stats = get_mib_repository_stats(conn)
        assert stats["vendor_counts"]["SampleVendor"] >= 1
        assert isinstance(stats["unresolved_oid_node_count"], int)
        filtered_stats = get_mib_repository_stats(
            conn,
            search="SAMPLE-TEST",
            vendor="samplevendor",
        )
        assert filtered_stats["module_count"] == 1
        assert filtered_stats["parsed_module_count"] == 1
        assert filtered_stats["zero_node_module_count"] == 0
        assert filtered_stats["failed_module_count"] == 0

        # Search by keyword
        search_res = search_mib_nodes(conn, query="sampleCpuUsage")
        assert len(search_res) >= 1
        matched = search_res[0]
        assert "sampleCpuUsage" in matched["node_name"]
        assert matched["oid"] == "1.3.6.1.4.1.99999.1.1"
        assert matched["recommended_mode"] == "direct_percent"

        # Search with mib_id filter
        scoped_res = search_mib_nodes(conn, query="cpu", mib_id=res["id"])
        assert len(scoped_res) >= 1
        assert scoped_res[0]["node_name"] == "sampleCpuUsage"

        # The detail-pane search can opt out of hidden description matches.
        description_res = search_mib_nodes(conn, query="CPU busy", mib_id=res["id"])
        assert len(description_res) == 1
        node_scope_res = search_mib_nodes(conn, query="CPU busy", mib_id=res["id"], scope="node")
        assert node_scope_res == []

        # Search by OID prefix
        oid_res = search_mib_nodes(conn, query="1.3.6.1.4.1.99999")
        assert len(oid_res) == 3

        # Detail
        detail = get_mib_detail(conn, res["id"])
        assert detail is not None
        assert len(detail["nodes"]) == 3
        assert detail["resolved_node_count"] == 3
        assert detail["unresolved_node_count"] == 0

        # A module with at least one unresolved node is included by the
        # unresolved-OID quick filter, even though its parse status is parsed.
        conn.execute(
            "UPDATE snmp_mib_nodes SET oid = '' WHERE mib_id = ? AND node_name = ?",
            (res["id"], "sampleCpuUsage"),
        )
        conn.commit()
        unresolved_page, unresolved_total = list_mibs_page(
            conn,
            search="SAMPLE-TEST",
            status="unresolved_oid",
            page=1,
            page_size=10,
        )
        assert unresolved_total == 1
        assert unresolved_page[0]["name"] == "SAMPLE-TEST-MIB"
        unresolved_stats = get_mib_repository_stats(
            conn,
            search="SAMPLE-TEST",
            vendor="samplevendor",
            status="unresolved_oid",
        )
        assert unresolved_stats["module_count"] == unresolved_total
        assert unresolved_stats["unresolved_oid_node_count"] == 1

        # Cleanup
        delete_mib(conn, res["id"])
        conn.commit()
        assert get_mib_detail(conn, res["id"]) is None
    finally:
        conn.close()


def test_local_snmp_model_preset_routes_are_retired() -> None:
    with pytest.raises(HTTPException) as exc_info:
        reject_local_snmp_model_presets(user={"role": "Viewer"})

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail["code"] == "LIBRENMS_RULES_ONLY"


def test_reset_and_search_multi_vendor_mibs() -> None:
    from services.snmp_preset_service import reset_builtin_mibs
    count = reset_builtin_mibs()
    assert count >= 8

    conn = get_db_connection()
    try:
        # Search Cisco process MIB node
        cisco_nodes = search_mib_nodes(conn, query="cpmCPUTotal1minRev")
        assert len(cisco_nodes) >= 1
        assert "cpmCPUTotal1minRev" in cisco_nodes[0]["node_name"]

        # Search Huawei Entity MIB node
        hw_nodes = search_mib_nodes(conn, query="hwEntityCpuUsage")
        assert len(hw_nodes) >= 1
        assert "hwEntityCpuUsage" in hw_nodes[0]["node_name"]

        # Search Juniper MIB node
        jnx_nodes = search_mib_nodes(conn, query="jnxOperatingCPU")
        assert len(jnx_nodes) >= 1
        assert "jnxOperatingCPU" in jnx_nodes[0]["node_name"]

        # Search Fortinet MIB node
        fg_nodes = search_mib_nodes(conn, query="fgSysCpuUsage")
        assert len(fg_nodes) >= 1
        assert "fgSysCpuUsage" in fg_nodes[0]["node_name"]
    finally:
        conn.close()


def test_builtin_mibs_seeder() -> None:
    count = seed_builtin_mibs()
    assert count >= 4

    conn = get_db_connection()
    try:
        mibs = list_mibs(conn)
        names = {m["name"] for m in mibs}
        assert "RFC1213-MIB" in names or "IF-MIB" in names
        duplicate_builtin_rows = conn.execute(
            "SELECT LOWER(TRIM(name)), LOWER(TRIM(vendor)), LOWER(TRIM(filename)), COUNT(*) "
            "FROM snmp_mibs WHERE source_type = 'builtin' AND is_active = 1 "
            "GROUP BY LOWER(TRIM(name)), LOWER(TRIM(vendor)), LOWER(TRIM(filename)) "
            "HAVING COUNT(*) > 1"
        ).fetchall()
        assert duplicate_builtin_rows == []
    finally:
        conn.close()
