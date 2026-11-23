import importlib
import json
from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from database.migrations import m0112_ai_knowledge_directories


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")


def _knowledge_connection():
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_knowledge_base (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            tenant_id TEXT DEFAULT 'tenant-default',
            acl_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        INSERT INTO ai_knowledge_base (id, name, tenant_id, created_at)
        VALUES ('kb-1', 'Default KB', 'tenant-a', '2026-08-08T00:00:00Z');
        """
    )
    m0112_ai_knowledge_directories.upgrade(connection.cursor(), use_pg=True)
    connection.commit()
    return connection


def test_directory_tree_seeds_once_and_supports_nested_crud(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    service = knowledge_service_module.KnowledgeService()

    tree = service.list_knowledge_directories("kb-1", tenant_id=None)
    assert tree["total"] == 30
    assert [node["name"] for node in tree["items"]] == [
        "01_product",
        "02_commands",
        "03_configuration",
        "04_cli_outputs",
        "05_troubleshooting",
        "06_examples",
    ]
    product = tree["items"][0]
    assert [node["name"] for node in product["children"]] == ["huawei", "h3c", "cisco", "ruijie"]

    custom = service.create_knowledge_directory("kb-1", "models", parent_id=product["children"][0]["id"], tenant_id="tenant-a", created_by="tester")
    assert custom["path"] == "01_product/huawei/models"
    assert custom["depth"] == 2

    renamed = service.rename_knowledge_directory(product["children"][0]["id"], "huawei_devices", tenant_id="tenant-a")
    assert renamed["path"] == "01_product/huawei_devices"
    refreshed = service.list_knowledge_directories("kb-1", tenant_id=None)
    assert any(node["path"] == "01_product/huawei_devices/models" for node in refreshed["items"][0]["children"][0]["children"])

    with pytest.raises(ValueError, match="同级目录"):
        service.create_knowledge_directory("kb-1", "HUAWEI_DEVICES", parent_id=product["id"], tenant_id="tenant-a")

    # Seeded (built-in) directories may be renamed but never deleted.
    with pytest.raises(ValueError, match="系统内置目录不可删除"):
        service.delete_knowledge_directory(renamed["id"], tenant_id="tenant-a")

    # A user-created directory is deletable; it moved with its renamed parent.
    service.delete_knowledge_directory(custom["id"], tenant_id="tenant-a")
    after_delete = service.list_knowledge_directories("kb-1", tenant_id=None)
    assert after_delete["total"] == 30
    huawei_devices = after_delete["items"][0]["children"][0]
    assert huawei_devices["name"] == "huawei_devices"
    assert not huawei_devices.get("children")


def test_directory_tree_lists_historical_tenants_and_new_roots_use_default(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    service = knowledge_service_module.KnowledgeService()

    service._ensure_default_directories(connection.cursor(), "kb-1", "tenant-a", "legacy-a")
    service._ensure_default_directories(connection.cursor(), "kb-1", "tenant-b", "legacy-b")
    connection.commit()

    tree = service.list_knowledge_directories("kb-1", tenant_id=None)
    assert tree["total"] == 90
    assert {node["tenant_id"] for node in tree["items"]} == {"tenant-a", "tenant-b", "tenant-default"}

    new_root = service.create_knowledge_directory(
        "kb-1", "new-root", tenant_id="tenant-history-c", created_by="tester",
    )
    assert new_root["tenant_id"] == "tenant-default"


def test_new_knowledge_base_uses_default_tenant(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    created = knowledge_service_module.KnowledgeService().create_knowledge_base(
        "New single-org KB", tenant_id="tenant-history-c",
    )

    assert created["tenant_id"] == "tenant-default"
    assert connection.execute(
        "SELECT tenant_id FROM ai_knowledge_base WHERE id = ?", (created["id"],),
    ).fetchone()[0] == "tenant-default"


def test_document_listing_filters_by_directory_metadata(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            status TEXT,
            knowledge_source_type TEXT,
            tenant_id TEXT,
            acl_json TEXT,
            source_trust_level TEXT,
            metadata_json TEXT,
            created_at TEXT
        );
        CREATE TABLE ai_document_chunk (id TEXT PRIMARY KEY, document_id TEXT);
        """
    )
    connection.executemany(
        "INSERT INTO ai_document VALUES (?, ?, ?, 'upload', ?, ?, 'active', 'internal_sop', 'tenant-a', '{}', 'internal', ?, ?)",
        [
            ('doc-1', 'kb-1', 'Huawei Models', 'Huawei', 'huawei_vrp', json.dumps({'knowledge_directory_path': 'kb_import/01_product/huawei/models'}), '2026-08-08T00:00:00Z'),
            ('doc-2', 'kb-1', 'Cisco Models', 'Cisco', 'cisco_ios', json.dumps({'knowledge_directory_path': 'kb_import/01_product/cisco/models'}), '2026-08-07T00:00:00Z'),
        ],
    )
    connection.commit()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        tenant_id=None,
        directory_path="01_product/huawei",
    )

    assert result["total"] == 1
    assert result["items"][0]["id"] == "doc-1"
