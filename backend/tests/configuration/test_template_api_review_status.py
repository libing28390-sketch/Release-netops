import sqlite3

from api import templates as templates_api


def _database(tmp_path, monkeypatch):
    db_path = tmp_path / "templates.db"
    conn = sqlite3.connect(db_path)
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
            validation_status TEXT DEFAULT 'draft'
        );
        """
    )
    conn.close()

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(templates_api, "get_db_connection", connect)
    monkeypatch.setattr(templates_api, "log_audit_event", lambda **_: None)
    return db_path


def test_create_cannot_forge_official_review_status(tmp_path, monkeypatch) -> None:
    db_path = _database(tmp_path, monkeypatch)
    templates_api.create_template(
        {
            "id": "custom-1",
            "name": "Custom",
            "type": "cli",
            "category": "custom",
            "vendor": "Cisco",
            "content": "interface Loopback0",
            "official_reference": "https://example.invalid/forged",
            "validation_status": "official_reference_reviewed",
        },
        user={"username": "admin", "role": "Administrator"},
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT official_reference, validation_status FROM templates WHERE id = ?",
            ("custom-1",),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("", "draft")


def test_editing_reviewed_template_downgrades_it_to_draft(tmp_path, monkeypatch) -> None:
    db_path = _database(tmp_path, monkeypatch)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO templates
        (id, name, type, category, vendor, content, rollback, last_used,
         description, platform_family, software_version, official_reference,
         validation_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "official-cisco-loopback",
            "Loopback",
            "cli",
            "routing",
            "Cisco",
            "interface Loopback0",
            "no interface Loopback0",
            "",
            "Official reference template",
            "cisco_iosxe",
            "IOS XE 17.x",
            "https://www.cisco.com/",
            "official_reference_reviewed",
        ),
    )
    conn.commit()
    conn.close()

    templates_api.update_template(
        "official-cisco-loopback",
        {
            "name": "Loopback",
            "type": "cli",
            "category": "routing",
            "vendor": "Cisco",
            "content": "interface Loopback1",
            "rollback": "no interface Loopback1",
            "description": "Official reference template",
            "platform_family": "cisco_iosxe",
            "software_version": "IOS XE 17.x",
        },
        user={"username": "admin", "role": "Administrator"},
    )

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT content, official_reference, validation_status FROM templates WHERE id = ?",
            ("official-cisco-loopback",),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("interface Loopback1", "https://www.cisco.com/", "draft")
