import importlib
import json
import sqlite3

import pytest

from database.migrations import m0112_ai_knowledge_directories


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")


def _knowledge_connection():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
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
    m0112_ai_knowledge_directories.upgrade(connection.cursor(), use_pg=False)
    connection.commit()
    return connection


def test_directory_tree_seeds_once_and_supports_nested_crud(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    service = knowledge_service_module.KnowledgeService()

    tree = service.list_knowledge_directories("kb-1", tenant_id="tenant-a")
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
    refreshed = service.list_knowledge_directories("kb-1", tenant_id="tenant-a")
    assert any(node["path"] == "01_product/huawei_devices/models" for node in refreshed["items"][0]["children"][0]["children"])

    with pytest.raises(ValueError, match="同级目录"):
        service.create_knowledge_directory("kb-1", "HUAWEI_DEVICES", parent_id=product["id"], tenant_id="tenant-a")

    service.delete_knowledge_directory(renamed["id"], tenant_id="tenant-a")
    after_delete = service.list_knowledge_directories("kb-1", tenant_id="tenant-a")
    assert after_delete["total"] == 29
    assert all(node["name"] != "huawei_devices" for node in after_delete["items"][0]["children"])


def test_directory_tree_is_tenant_scoped(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    service = knowledge_service_module.KnowledgeService()

    tenant_b = service.list_knowledge_directories("kb-1", tenant_id="tenant-b")
    tenant_a = service.list_knowledge_directories("kb-1", tenant_id="tenant-a")
    assert tenant_b["total"] == 30
    assert tenant_a["total"] == 30
    assert {node["id"] for node in tenant_a["items"]}.isdisjoint({node["id"] for node in tenant_b["items"]})


def test_document_listing_filters_by_directory_metadata(monkeypatch):
    connection = sqlite3.connect(":memory:")
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
        tenant_id="tenant-a",
        directory_path="01_product/huawei",
    )

    assert result["total"] == 1
    assert result["items"][0]["id"] == "doc-1"
