from __future__ import annotations

import sqlite3

import services.librenms_mib_service as sync_librenms_mibs
from services.snmp_mib_service import MibParser


SAMPLE_MIB = """
SAMPLE-IMPORT-MIB DEFINITIONS ::= BEGIN

sampleRoot OBJECT IDENTIFIER ::= { enterprises 99998 }
sampleMetric OBJECT-TYPE
    SYNTAX Gauge32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "Sample metric"
    ::= { sampleRoot 1 }

END
"""


def _create_import_schema(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE snmp_mib_sources (
            id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_name TEXT NOT NULL,
            source_commit TEXT NOT NULL, root_path TEXT NOT NULL, manifest_path TEXT NOT NULL,
            file_count INTEGER NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_import_runs (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_type TEXT NOT NULL,
            source_commit TEXT NOT NULL, source_path TEXT NOT NULL, parser_version TEXT NOT NULL,
            status TEXT NOT NULL, total_files INTEGER NOT NULL, processed_files INTEGER NOT NULL DEFAULT 0,
            imported_files INTEGER NOT NULL DEFAULT 0, updated_files INTEGER NOT NULL DEFAULT 0,
            skipped_files INTEGER NOT NULL DEFAULT 0, failed_files INTEGER NOT NULL DEFAULT 0,
            duplicate_files INTEGER NOT NULL DEFAULT 0, zero_node_files INTEGER NOT NULL DEFAULT 0,
            total_nodes INTEGER NOT NULL DEFAULT 0, current_path TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE snmp_mib_import_items (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source_id TEXT NOT NULL,
            relative_path TEXT NOT NULL, vendor_key TEXT NOT NULL, vendor_name TEXT NOT NULL,
            filename TEXT NOT NULL, sha256 TEXT NOT NULL, file_size INTEGER NOT NULL,
            raw_file_path TEXT NOT NULL, status TEXT NOT NULL, mib_id TEXT NOT NULL,
            module_name TEXT NOT NULL, node_count INTEGER NOT NULL, error TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )


def test_librenms_import_scans_root_and_vendor_files_idempotently(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mib-import.sqlite"

    def open_conn():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    conn = open_conn()
    _create_import_schema(conn)
    conn.close()
    monkeypatch.setattr(sync_librenms_mibs, "get_db_connection", open_conn)
    mibs_dir = tmp_path / "mibs"
    vendor_dir = mibs_dir / "cisco"
    vendor_dir.mkdir(parents=True)
    (mibs_dir / "IF-MIB").write_text(SAMPLE_MIB, encoding="utf-8")
    (vendor_dir / "SAMPLE-IMPORT-MIB").write_text(SAMPLE_MIB, encoding="utf-8")
    monkeypatch.setenv("MIB_REPOSITORY_ROOT", str(tmp_path / "repository"))

    first = sync_librenms_mibs.import_mibs_from_directory(mibs_dir)
    assert first["success"] is True
    assert first["total_files"] == 2
    assert first["processed"] == 2
    assert first["imported"] == 2
    assert first["errors"] == 0
    assert first["zero_node"] == 0
    assert (tmp_path / "repository" / "sources" / "librenms" / "librenms" / "local" / "manifest.json").exists()

    repair_conn = open_conn()
    try:
        repair_conn.execute(
            "UPDATE snmp_mib_nodes SET oid = '' WHERE mib_id = "
            "(SELECT id FROM snmp_mibs WHERE relative_path = ? LIMIT 1)",
            ("IF-MIB",),
        )
        repair_conn.commit()
    finally:
        repair_conn.close()

    second = sync_librenms_mibs.import_mibs_from_directory(mibs_dir)
    assert second["success"] is True
    assert second["imported"] == 0
    assert second["updated"] == 1
    assert second["skipped"] == 1
    assert second["duplicates"] == 1

    conn = open_conn()
    try:
        source_count = conn.execute("SELECT COUNT(*) FROM snmp_mib_sources").fetchone()[0]
        run_count = conn.execute("SELECT COUNT(*) FROM snmp_mib_import_runs").fetchone()[0]
        item_count = conn.execute("SELECT COUNT(*) FROM snmp_mib_import_items").fetchone()[0]
        assert source_count == 1
        assert run_count == 2
        assert item_count == 4
        assert conn.execute("SELECT COUNT(*) FROM snmp_mibs WHERE source_id = ?", (first["source_id"],)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM snmp_mib_nodes WHERE oid = ''").fetchone()[0] == 0
    finally:
        conn.close()


def test_librenms_update_after_upstream_commit_reuses_same_active_row(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mib-commit-update.sqlite"

    def open_conn():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    conn = open_conn()
    _create_import_schema(conn)
    conn.close()

    mibs_dir = tmp_path / "mibs"
    mibs_dir.mkdir()
    mib_path = mibs_dir / "SAME-MODULE-MIB"
    mib_path.write_text(SAMPLE_MIB, encoding="utf-8")
    monkeypatch.setattr(sync_librenms_mibs, "get_db_connection", open_conn)
    commits = iter(["commit-a", "commit-b"])
    monkeypatch.setattr(sync_librenms_mibs, "git_commit", lambda _repo: next(commits))
    monkeypatch.setenv("MIB_REPOSITORY_ROOT", str(tmp_path / "repository"))

    first = sync_librenms_mibs.import_mibs_from_directory(mibs_dir)
    first_conn = open_conn()
    first_id = first_conn.execute("SELECT id FROM snmp_mibs WHERE is_active = 1").fetchone()[0]
    first_conn.close()

    mib_path.write_text(SAMPLE_MIB.replace("99998", "99997"), encoding="utf-8")
    second = sync_librenms_mibs.import_mibs_from_directory(mibs_dir)

    conn = open_conn()
    try:
        active_rows = conn.execute(
            "SELECT id, sha256, source_commit FROM snmp_mibs WHERE is_active = 1"
        ).fetchall()
        assert first["source_id"] == second["source_id"]
        assert second["imported"] == 0
        assert second["updated"] == 1
        assert len(active_rows) == 1
        assert active_rows[0][0] == first_id
        assert active_rows[0][2] == "commit-b"
        assert conn.execute("SELECT COUNT(*) FROM snmp_mib_nodes").fetchone()[0] == 1
    finally:
        conn.close()


def test_librenms_full_snapshot_retires_removed_path(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "mib-removed.sqlite"

    def open_conn():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    conn = open_conn()
    _create_import_schema(conn)
    conn.close()

    mibs_dir = tmp_path / "mibs"
    vendor_dir = mibs_dir / "cisco"
    vendor_dir.mkdir(parents=True)
    keep_path = mibs_dir / "KEEP-MIB"
    remove_path = vendor_dir / "REMOVE-MIB"
    keep_path.write_text(SAMPLE_MIB, encoding="utf-8")
    remove_path.write_text(SAMPLE_MIB.replace("99998", "99997"), encoding="utf-8")
    monkeypatch.setattr(sync_librenms_mibs, "get_db_connection", open_conn)
    monkeypatch.setenv("MIB_REPOSITORY_ROOT", str(tmp_path / "repository"))

    sync_librenms_mibs.import_mibs_from_directory(mibs_dir)
    remove_path.unlink()
    second = sync_librenms_mibs.import_mibs_from_directory(mibs_dir)

    conn = open_conn()
    try:
        assert second["deactivated"] == 1
        assert conn.execute("SELECT COUNT(*) FROM snmp_mibs WHERE is_active = 1").fetchone()[0] == 1
        assert conn.execute(
            "SELECT is_active FROM snmp_mibs WHERE relative_path = ?",
            ("cisco/REMOVE-MIB",),
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_symbol_index_resolves_dependency_declared_later(tmp_path) -> None:
    mibs_dir = tmp_path / "mibs"
    vendor_dir = mibs_dir / "cisco"
    vendor_dir.mkdir(parents=True)

    metric_file = vendor_dir / "A-METRIC-MIB"
    dependency_file = vendor_dir / "Z-LATE-OID-MIB"
    metric_file.write_text(
        """
A-METRIC-MIB DEFINITIONS ::= BEGIN

metric OBJECT-TYPE
    SYNTAX Gauge32
    MAX-ACCESS read-only
    STATUS current
    ::= { lateRoot 1 }

END
""",
        encoding="utf-8",
    )
    dependency_file.write_text(
        """
Z-LATE-OID-MIB DEFINITIONS ::= BEGIN

lateRoot OBJECT IDENTIFIER ::= { enterprises 99997 }

END
""",
        encoding="utf-8",
    )

    _, symbols_by_vendor = sync_librenms_mibs.build_symbol_index(
        [metric_file, dependency_file],
        mibs_dir,
        max_passes=4,
    )

    assert "lateRoot" in symbols_by_vendor["cisco"]
    parser = MibParser(
        metric_file.read_text(encoding="utf-8"),
        external_symbols=symbols_by_vendor["cisco"],
    )
    nodes = parser.parse()
    assert nodes[0]["oid"] == "1.3.6.1.4.1.99997.1"
