from __future__ import annotations

import hashlib
import json

import services.librenms_mib_service as mib_service


SOURCE_ID = "source-librenms-cache-test"
SOURCE_COMMIT = "source-commit-a"
RULE_CONTRACT_VERSION = "nexora.librenms.rules.v1"


def _bundle(tmp_path, content: bytes = b"TEST-MIB\r\nline\r\n"):
    bundle = tmp_path / "librenms"
    mibs_dir = bundle / "mibs" / "cisco"
    mibs_dir.mkdir(parents=True)
    mib_path = mibs_dir / "TEST-MIB"
    mib_path.write_bytes(content)
    relative_path = "cisco/TEST-MIB"
    manifest = {
        "mibs": [{
            "bundle_path": f"mibs/{relative_path}",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }],
    }
    (bundle / "source-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return mibs_dir.parent, mib_path


def _seed_marker(conn, mibs_dir, mib_path, *, node_count=2, unresolved=False, source_commit=SOURCE_COMMIT):
    now = "2026-10-01T00:00:00+00:00"
    relative_path = "cisco/TEST-MIB"
    file_hash = hashlib.sha256(mib_path.read_bytes()).hexdigest()
    conn.execute(
        """INSERT INTO snmp_mib_sources
           (id, source_type, source_name, source_commit, root_path, manifest_path,
            file_count, status, error, created_at, updated_at)
           VALUES (?, 'librenms', 'librenms', ?, ?, '', 1, 'ready', '', ?, ?)""",
        (SOURCE_ID, source_commit, str(mibs_dir), now, now),
    )
    conn.execute(
        """INSERT INTO snmp_mib_import_runs
           (id, source_id, source_type, source_commit, source_path, parser_version,
            status, total_files, processed_files, failed_files, total_nodes,
            started_at, completed_at, created_at, updated_at)
           VALUES (?, ?, 'librenms', ?, ?, ?, 'completed', 1, 1, 0, ?, ?, ?, ?, ?)""",
        (
            "mib-run-cache-test",
            SOURCE_ID,
            source_commit,
            str(mibs_dir),
            mib_service.PARSER_VERSION,
            node_count,
            now,
            now,
            now,
            now,
        ),
    )
    conn.execute(
        """INSERT INTO snmp_mibs
           (id, name, vendor, filename, file_size, node_count, source_type,
            description, content_text, source_id, source_commit, relative_path,
            raw_file_path, sha256, parse_status, parse_error, parser_version,
            import_run_id, is_active, created_at, updated_at)
           VALUES (?, 'TEST-MIB', 'Cisco', 'TEST-MIB', ?, ?, 'librenms', '', '',
                   ?, ?, ?, ?, ?, 'parsed', '', ?, ?, 1, ?, ?)""",
        (
            "mib-cache-test",
            len(mib_path.read_text(encoding="utf-8").encode("utf-8")),
            node_count,
            SOURCE_ID,
            source_commit,
            relative_path,
            str(mib_path),
            file_hash,
            mib_service.PARSER_VERSION,
            "mib-run-cache-test",
            now,
            now,
        ),
    )
    for index in range(node_count):
        conn.execute(
            """INSERT INTO snmp_mib_nodes
               (id, mib_id, node_name, oid, parent_oid, syntax_type,
                access_type, status, description, created_at)
               VALUES (?, 'mib-cache-test', ?, ?, '', '', '', 'current', '', ?)""",
            (
                f"node-cache-test-{index}",
                f"testNode{index}",
                "" if unresolved and index == 0 else f"1.3.6.1.4.1.999.{index + 1}",
                now,
            ),
        )
    conn.commit()


def _marker(conn, mibs_dir, mib_path, **kwargs):
    return mib_service._persistent_cache_marker(
        conn,
        mibs_path=mibs_dir,
        files=[mib_path],
        source_id=SOURCE_ID,
        source_commit=kwargs.pop("source_commit", SOURCE_COMMIT),
        rules_source_commit=kwargs.pop("rules_source_commit", ""),
        rules_contract_version=kwargs.pop("rules_contract_version", ""),
        max_files=kwargs.pop("max_files", None),
    )


def test_marker_allows_crlf_size_difference_and_stable_unresolved_nodes(isolated_db, tmp_path):
    mibs_dir, mib_path = _bundle(tmp_path)
    conn = isolated_db["module"].get_db_connection()
    try:
        _seed_marker(conn, mibs_dir, mib_path, unresolved=True)
        marker = _marker(conn, mibs_dir, mib_path)
    finally:
        conn.close()

    assert marker == {"run_id": "mib-run-cache-test", "nodes": 2, "zero_node": 0}


def test_manifest_whitelist_excludes_unlisted_bundle_files(tmp_path):
    mibs_dir, mib_path = _bundle(tmp_path)
    unlisted = mibs_dir / "cisco" / "TEST-MIB-UNLISTED"
    unlisted.write_text(
        "TEST-MIB-UNLISTED DEFINITIONS ::= BEGIN END",
        encoding="utf-8",
    )
    manifest_entries = mib_service._source_manifest_entries(mibs_dir)

    assert manifest_entries is not None
    selected, ignored, missing = mib_service._manifest_whitelisted_files(
        mibs_dir,
        [mib_path, unlisted],
        manifest_entries,
    )

    assert selected == [mib_path]
    assert ignored == 1
    assert missing == []


def test_incomplete_pinned_bundle_fails_before_database_access(tmp_path, monkeypatch):
    mibs_dir, mib_path = _bundle(tmp_path)
    mib_path.unlink()
    monkeypatch.setattr(mib_service, "MIBS_DIR", mibs_dir)
    monkeypatch.setattr(
        mib_service,
        "get_db_connection",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be touched")),
    )

    result = mib_service.import_mibs_from_directory(
        mibs_dir=mibs_dir,
        target_vendors=["Cisco"],
    )

    assert result["success"] is False
    assert "1 manifest file(s) are missing" in result["message"]


def test_marker_rejects_missing_node_record(isolated_db, tmp_path):
    mibs_dir, mib_path = _bundle(tmp_path)
    conn = isolated_db["module"].get_db_connection()
    try:
        _seed_marker(conn, mibs_dir, mib_path)
        conn.execute("DELETE FROM snmp_mib_nodes WHERE id = ?", ("node-cache-test-1",))
        conn.commit()
        marker = _marker(conn, mibs_dir, mib_path)
    finally:
        conn.close()

    assert marker is None


def test_marker_rejects_source_hash_parser_and_rule_changes(isolated_db, tmp_path, monkeypatch):
    original_parser_version = mib_service.PARSER_VERSION
    mibs_dir, mib_path = _bundle(tmp_path)
    conn = isolated_db["module"].get_db_connection()
    try:
        _seed_marker(conn, mibs_dir, mib_path)
        assert _marker(conn, mibs_dir, mib_path) is not None

        assert _marker(conn, mibs_dir, mib_path, source_commit="source-commit-b") is None

        original = mib_path.read_bytes()
        mib_path.write_bytes(original + b"changed")
        assert _marker(conn, mibs_dir, mib_path) is None
        mib_path.write_bytes(original)

        monkeypatch.setattr(mib_service, "PARSER_VERSION", "mib-regex-next")
        assert _marker(conn, mibs_dir, mib_path) is None
    finally:
        conn.close()

    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO snmp_librenms_rules
               (id, os_key, vendor, platform, display_name, detection_json,
                oid_candidates_json, source_path, source_commit, rule_status,
                generated_at, updated_at)
               VALUES (?, ?, '', '', '', ?, '[]', '', ?, 'active', ?, ?)""",
            (
                "librenms-cache-rule",
                "cache-rule",
                json.dumps({"rule_contract_version": RULE_CONTRACT_VERSION}),
                SOURCE_COMMIT,
                "2026-10-01T00:00:00+00:00",
                "2026-10-01T00:00:00+00:00",
            ),
        )
        conn.commit()
        monkeypatch.setattr(mib_service, "PARSER_VERSION", original_parser_version)
        assert _marker(
            conn,
            mibs_dir,
            mib_path,
            rules_source_commit=SOURCE_COMMIT,
            rules_contract_version=RULE_CONTRACT_VERSION,
        ) is not None
        assert _marker(
            conn,
            mibs_dir,
            mib_path,
            rules_source_commit="source-commit-b",
            rules_contract_version=RULE_CONTRACT_VERSION,
        ) is None
        assert _marker(
            conn,
            mibs_dir,
            mib_path,
            rules_source_commit=SOURCE_COMMIT,
            rules_contract_version="nexora.librenms.rules.next",
        ) is None
    finally:
        conn.close()
