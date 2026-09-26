from __future__ import annotations

import io
import asyncio
from backend.tests.pg_test_utils import postgresql_test_driver
import zipfile
import pytest
from fastapi import HTTPException, UploadFile

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
import services.snmp_mib_service as snmp_mib_service
import api.devices as devices_api
from core.config import settings


@pytest.fixture(autouse=True)
def _isolated_snmp_database(isolated_db):
    """Give repository tests the same fresh schema as the application."""
    yield isolated_db
from services.snmp_preset_service import (
    list_preset_profiles,
    seed_builtin_mibs,
)
from api.devices import (
    get_snmp_mibs,
    search_snmp_mib_nodes,
    get_official_model_presets,
    get_snmp_mib_detail,
    remove_snmp_mib,
    upload_snmp_mib_file,
)


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


def test_official_presets_service_and_api() -> None:
    presets = list_preset_profiles()
    assert len(presets) == 23
    assert {item["vendor"] for item in presets} == {"H3C", "Huawei", "ZTE", "Cisco"}
    assert sum(1 for item in presets if item.get("testable", True)) == 22
    assert all(item.get("source_oids") for item in presets if item.get("testable", True))
    assert {item["model"] for item in presets if item["vendor"] == "H3C"} >= {
        "S5000", "S5110", "S5120", "S5130", "S5135", "S5170", "S5500", "S5800",
        "S6300", "S6500", "S6800", "S10500", "S10500 (V5)",
    }
    assert {item["model"] for item in presets if item["vendor"] == "Huawei"} == {
        "S3700", "S5700", "S6700", "S7700", "S8700", "S9700", "S12700", "S16700",
    }
    assert not any(item["model"] == "Catalyst 9300" for item in presets)
    assert not any("Nexus" in item["model"] for item in presets)
    assert not any(item["vendor"] in {"Ruijie", "Juniper", "Fortinet", "Raisecom"} for item in presets)

    h3c = next(p for p in presets if p["vendor"] == "H3C")
    assert h3c["metric_definitions"]["cpu"]["oid"] == "1.3.6.1.4.1.25506.2.6.1.1.1.1.6"
    assert h3c["metric_definitions"]["memory"]["oid"] == "1.3.6.1.4.1.25506.2.6.1.1.1.1.8"
    assert "1.3.6.1.4.1.25506.2.6.1.1.1.1.19" in h3c["source_oids"]["system"]

    huawei = next(p for p in presets if p["vendor"] == "Huawei")
    assert huawei["metric_definitions"]["cpu"]["oid"] == "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5"
    assert huawei["metric_definitions"]["fan"]["oid"] == "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7"

    zte = next(p for p in presets if p["vendor"] == "ZTE")
    assert zte["metric_definitions"]["uptime"]["oid"] == "1.3.6.1.2.1.1.3"
    assert "1.3.6.1.4.1.3902.3.600.2.1.1.3.0.0.1.0" in zte["source_oids"]["system"]
    assert "1.3.6.1.4.1.3902.1082.30.40.2.4.1.2" in zte["source_oids"]["optical"]
    assert "1.3.6.1.4.1.3902.1082.30.40.2.4.1.8" in zte["source_oids"]["optical"]
    assert "IF-MIB::ifName / ifDescr by ifIndex" in zte["source_oids"]["optical_index_lookup"]

    cisco = next(p for p in presets if p["vendor"] == "Cisco")
    assert cisco["metric_definitions"]["cpu"]["oid"] == "1.3.6.1.4.1.9.9.109.1.1.1.1.3"
    assert cisco["metric_definitions"]["memory"]["used_oid"] == "1.3.6.1.4.1.9.9.48.1.1.1.5"
    assert cisco["metric_definitions"]["memory"]["free_oid"] == "1.3.6.1.4.1.9.9.48.1.1.1.6"
    assert "CISCO-PROCESS-MIB::cpmCPUTotal5sec" in cisco["source_oids"]["system"]

    # Test API endpoint
    api_res = get_official_model_presets(user={"role": "Viewer"})
    assert api_res["success"] is True
    assert api_res["total"] == 23


def test_manual_mib_upload_can_be_disabled_explicitly(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SNMP_MIB_MANUAL_UPLOAD_ENABLED", False)
    upload = UploadFile(filename="SAMPLE-TEST-MIB.mib", file=io.BytesIO(SAMPLE_TEST_MIB.encode()))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(upload_snmp_mib_file(file=upload, user={"role": "Operator"}))

    assert exc_info.value.status_code == 410
    assert "Manual MIB uploads are disabled" in str(exc_info.value.detail)


def _create_upload_schema(conn: postgresql_test_driver.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE snmp_mibs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, vendor TEXT NOT NULL,
            filename TEXT NOT NULL, file_size INTEGER NOT NULL, node_count INTEGER NOT NULL,
            source_type TEXT NOT NULL, description TEXT NOT NULL, content_text TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '', source_commit TEXT NOT NULL DEFAULT '',
            relative_path TEXT NOT NULL DEFAULT '', raw_file_path TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '', parse_status TEXT NOT NULL DEFAULT 'legacy',
            parse_error TEXT NOT NULL DEFAULT '', parser_version TEXT NOT NULL DEFAULT 'legacy',
            module_oid TEXT NOT NULL DEFAULT '', import_run_id TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_nodes (
            id TEXT PRIMARY KEY, mib_id TEXT NOT NULL, node_name TEXT NOT NULL,
            oid TEXT NOT NULL, parent_oid TEXT NOT NULL, syntax_type TEXT NOT NULL,
            access_type TEXT NOT NULL, status TEXT NOT NULL, description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def test_manual_mib_zip_upload_imports_supported_members(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SNMP_MIB_MANUAL_UPLOAD_ENABLED", True)
    conn = postgresql_test_driver.connect()
    _create_upload_schema(conn)
    monkeypatch.setattr(devices_api, "get_db_connection", lambda: conn)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("vendor/SAMPLE-TEST-MIB.mib", SAMPLE_TEST_MIB)
        zip_file.writestr("README.md", "ignored")
    archive.seek(0)

    upload = UploadFile(filename="vendor-mibs.zip", file=archive)
    response = asyncio.run(
        upload_snmp_mib_file(
            file=upload,
            vendor="",
            description="",
            user={"role": "Operator"},
        )
    )

    assert response["success"] is True
    assert response["imported"] == 1
    assert response["failed"] == 0
    assert response["data"][0]["name"] == "SAMPLE-TEST-MIB"


def test_manual_large_zip_archive_upload_triggers_background_indexing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "SNMP_MIB_MANUAL_UPLOAD_ENABLED", True)

    # Mock import_mibs_from_directory
    mock_called = False
    def mock_import(mibs_dir=None, target_vendors=None):
        nonlocal mock_called
        mock_called = True
        return {"success": True, "imported": 12, "nodes": 100, "run_id": "test-run-123"}

    import services.librenms_mib_service as sync_module
    monkeypatch.setattr(sync_module, "import_mibs_from_directory", mock_import)
    monkeypatch.setattr(sync_module, "MIBS_DIR", str(tmp_path / "mibs"))

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        for i in range(12):
            zip_file.writestr(f"cisco/TEST-MIB-{i}", f"TEST-MIB-{i} DEFINITIONS ::= BEGIN END")
    archive.seek(0)

    upload = UploadFile(filename="all-mibs.zip", file=archive)
    response = asyncio.run(
        upload_snmp_mib_file(
            file=upload,
            vendor="",
            description="",
            user={"role": "Operator"},
        )
    )

    assert response["success"] is True
    assert response["async"] is True
    assert response["extracted"] == 12
    assert response["vendors"] == ["Cisco"]


def test_zip_member_failure_does_not_abort_other_members(monkeypatch) -> None:
    conn = postgresql_test_driver.connect()
    conn.execute("CREATE TABLE imported_files (filename TEXT PRIMARY KEY)")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("good.mib", "good")
        zip_file.writestr("broken.mib", "broken")
    archive.seek(0)

    def fake_parse_and_store_mib(connection, *, filename, **kwargs):
        if filename == "broken.mib":
            raise ValueError("invalid MIB")
        connection.execute("INSERT INTO imported_files (filename) VALUES (?)", (filename,))
        return {"filename": filename}

    monkeypatch.setattr(snmp_mib_service, "parse_and_store_mib", fake_parse_and_store_mib)
    errors: list[dict[str, str]] = []
    results = snmp_mib_service.parse_and_store_zip(conn, archive.getvalue(), errors=errors)
    conn.commit()

    assert results == [{"filename": "good.mib"}]
    assert errors == [{"filename": "broken.mib", "error": "invalid MIB"}]
    assert [tuple(row) for row in conn.execute("SELECT filename FROM imported_files").fetchall()] == [("good.mib",)]
    conn.close()


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


def test_auto_match_model_mibs() -> None:
    from api.devices import auto_match_model_mibs

    cases = [
        ("H3C", "S5130S-52S-EI", "md-h3c-comware-v7"),
        ("华为", "S5720-28P-PWR-LI-AC", "md-huawei-vrp-switch"),
        ("中兴", "ZXR10-某系列", "md-zte-zxr10-switch"),
        ("Cisco", "C9300-48P-A", "md-cisco-catalyst-categraf"),
    ]
    for vendor, model, expected_id in cases:
        matched = auto_match_model_mibs(vendor=vendor, model=model, user={"role": "Viewer"})
        assert matched["matched"] is True
        assert matched["data"]["preset"]["family_id"] == expected_id

    unsupported = auto_match_model_mibs(
        vendor="Ruijie",
        model="RG-S5750",
        user={"role": "Viewer"},
    )
    assert unsupported["matched"] is False

    unsupported_nexus = auto_match_model_mibs(
        vendor="Cisco",
        model="Nexus 93180YC-FX",
        user={"role": "Viewer"},
    )
    assert unsupported_nexus["matched"] is False
