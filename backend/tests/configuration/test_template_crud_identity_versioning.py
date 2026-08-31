from backend.tests.pg_test_utils import postgresql_test_driver
from api import templates as templates_api


ADMIN = {"username": "session-admin", "role": "Administrator"}


def _database(tmp_path, monkeypatch):
    db_path = tmp_path / "template-center.db"
    conn = postgresql_test_driver.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE templates (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            category TEXT,
            vendor TEXT,
            content TEXT,
            rollback TEXT,
            last_used TEXT,
            description TEXT DEFAULT '',
            platform_family TEXT DEFAULT '',
            software_version TEXT DEFAULT '',
            official_reference TEXT DEFAULT '',
            validation_status TEXT DEFAULT 'draft',
            code TEXT DEFAULT '',
            source_type TEXT DEFAULT 'custom',
            risk_level TEXT DEFAULT 'low',
            status TEXT DEFAULT 'draft',
            current_version TEXT DEFAULT '1.0',
            is_official INTEGER DEFAULT 0,
            created_by TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            variable_schema_json TEXT DEFAULT '[]',
            example_values_json TEXT DEFAULT '{}',
            usage_notes TEXT DEFAULT '',
            risk_notes TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            favorite_count INTEGER DEFAULT 0,
            use_count INTEGER DEFAULT 0,
            quality_score INTEGER DEFAULT 0
        );

        CREATE TABLE config_template_versions (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            version TEXT NOT NULL,
            source TEXT NOT NULL,
            rollback_source TEXT NOT NULL DEFAULT '',
            variable_schema_json TEXT NOT NULL DEFAULT '[]',
            example_values_json TEXT NOT NULL DEFAULT '{}',
            render_options_json TEXT NOT NULL DEFAULT '{}',
            change_summary TEXT NOT NULL DEFAULT '',
            checksum TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            UNIQUE(template_id, version)
        );
        """
    )
    conn.close()

    def connect():
        connection = postgresql_test_driver.connect(db_path)
        connection.row_factory = postgresql_test_driver.Row
        return connection

    audit_events = []
    monkeypatch.setattr(templates_api, "get_db_connection", connect)
    monkeypatch.setattr(templates_api, "log_audit_event", lambda **event: audit_events.append(event))
    monkeypatch.setattr(templates_api, "_invalidate_templates_cache", lambda: None)
    return db_path, audit_events


def _payload(**overrides):
    payload = {
        "id": "custom-versioned",
        "name": "Versioned template",
        "type": "Jinja2",
        "category": "interface",
        "vendor": "Cisco",
        "platform_family": "cisco_iosxe",
        "software_version": "17.x",
        "description": "Initial description",
        "content": "interface {{ interface_name | default('Loopback0') }}",
        "rollback": "no interface {{ interface_name | default('Loopback0') }}",
        "example_values": {"interface_name": "Loopback0"},
        "actor_username": "forged-client-user",
        "actor_role": "ForgedRole",
    }
    payload.update(overrides)
    return payload


def test_session_identity_wins_and_updates_append_immutable_versions(tmp_path, monkeypatch):
    db_path, audit_events = _database(tmp_path, monkeypatch)

    created = templates_api.create_template(_payload(), user=ADMIN)
    updated = templates_api.update_template(
        "custom-versioned",
        _payload(
            description="Changed description",
            content="interface {{ interface_name | default('Loopback1') }}",
            rollback="no interface {{ interface_name | default('Loopback1') }}",
            example_values={"interface_name": "Loopback1"},
        ),
        user=ADMIN,
    )

    conn = postgresql_test_driver.connect(db_path)
    conn.row_factory = postgresql_test_driver.Row
    try:
        template = dict(conn.execute(
            "SELECT created_by, current_version, content FROM templates WHERE id = ?",
            ("custom-versioned",),
        ).fetchone())
        versions = [dict(row) for row in conn.execute(
            "SELECT version, source, created_by FROM config_template_versions "
            "WHERE template_id = ? ORDER BY version",
            ("custom-versioned",),
        ).fetchall()]
    finally:
        conn.close()

    assert created["version"] == "1.0"
    assert updated["version"] == "1.1"
    assert template["created_by"] == "session-admin"
    assert template["current_version"] == "1.1"
    assert [item["version"] for item in versions] == ["1.0", "1.1"]
    assert "Loopback0" in versions[0]["source"]
    assert "Loopback1" in versions[1]["source"]
    assert {item["created_by"] for item in versions} == {"session-admin"}
    assert [event["actor_username"] for event in audit_events] == ["session-admin", "session-admin"]
    assert all(event["actor_role"] == "Administrator" for event in audit_events)


def test_unchanged_save_does_not_create_a_duplicate_version(tmp_path, monkeypatch):
    db_path, _audit_events = _database(tmp_path, monkeypatch)
    payload = _payload()
    templates_api.create_template(payload, user=ADMIN)

    result = templates_api.update_template("custom-versioned", payload, user=ADMIN)

    conn = postgresql_test_driver.connect(db_path)
    try:
        version_count = conn.execute(
            "SELECT COUNT(*) FROM config_template_versions WHERE template_id = ?",
            ("custom-versioned",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["version"] == "1.0"
    assert version_count == 1


def test_archive_is_idempotent_and_does_not_duplicate_audit(tmp_path, monkeypatch):
    _db_path, audit_events = _database(tmp_path, monkeypatch)
    templates_api.create_template(_payload(), user=ADMIN)

    first = templates_api.delete_template("custom-versioned", user=ADMIN)
    second = templates_api.delete_template("custom-versioned", user=ADMIN)

    assert first["already_archived"] is False
    assert second["already_archived"] is True
    assert [event["event_type"] for event in audit_events] == [
        "TEMPLATE_CREATE",
        "TEMPLATE_DELETE",
    ]


def test_template_center_crud_routes_keep_legacy_aliases():
    route_methods = {
        (route.path, method)
        for route in templates_api.router.routes
        for method in getattr(route, "methods", set())
    }

    for method, suffix in (
        ("POST", ""),
        ("PUT", "/{template_id}"),
        ("DELETE", "/{template_id}"),
    ):
        assert (f"/config-templates{suffix}", method) in route_methods
        assert (f"/templates{suffix}", method) in route_methods


def test_next_version_skips_existing_candidate(tmp_path, monkeypatch):
    db_path, _audit_events = _database(tmp_path, monkeypatch)
    conn = postgresql_test_driver.connect(db_path)
    conn.execute(
        "INSERT INTO config_template_versions "
        "(id, template_id, version, source, created_at) VALUES (?, ?, ?, ?, ?)",
        ("version-11", "custom-versioned", "1.1", "source", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    try:
        assert templates_api._next_template_version(conn, "custom-versioned", "1.0") == "1.2"
        assert templates_api._next_template_version(conn, "other-template", "2.4.9") == "2.4.10"
    finally:
        conn.close()
