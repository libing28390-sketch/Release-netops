from __future__ import annotations

import io
import json
import uuid
import zipfile
from urllib.parse import urlparse, urlunparse

import pytest
import psycopg2

import database.core as database_core
import database.schema as database_schema
from database import init_db
from ai.services.knowledge_bundle_import_service import KnowledgeBundleImportError, import_knowledge_bundle
from ai.services.knowledge_export_service import knowledge_export_service
from ai.services.knowledge_service import knowledge_service


@pytest.fixture
def pg_host_databases():
    """Provide two disposable PostgreSQL databases for the host transfer test."""
    original_url = database_core._DATABASE_URL
    original_use_pg = database_core._USE_PG
    original_schema_use_pg = database_schema._USE_PG
    original_initialized = database_schema._db_initialized
    original_pool = database_core._pg_pool
    parsed = urlparse(original_url)
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    names = [f"nexora_bundle_test_{index}_{uuid.uuid4().hex[:10]}" for index in ("a", "b")]
    urls = {name: urlunparse(parsed._replace(path=f"/{name}")) for name in names}

    admin = psycopg2.connect(admin_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            for name in names:
                cursor.execute(f'CREATE DATABASE "{name}"')
    finally:
        admin.close()

    def switch(name: str) -> None:
        current_pool = database_core._pg_pool
        if current_pool is not None and current_pool is not original_pool:
            current_pool.closeall()
        database_core._pg_pool = None
        database_core._DATABASE_URL = urls[name]
        database_core._USE_PG = True
        database_schema._USE_PG = True
        database_schema._db_initialized = False
        init_db()

    try:
        yield switch, names
    finally:
        current_pool = database_core._pg_pool
        if current_pool is not None and current_pool is not original_pool:
            current_pool.closeall()
        database_core._pg_pool = original_pool
        database_core._DATABASE_URL = original_url
        database_core._USE_PG = original_use_pg
        database_schema._USE_PG = original_schema_use_pg
        database_schema._db_initialized = original_initialized
        cleanup = psycopg2.connect(admin_url)
        cleanup.autocommit = True
        try:
            with cleanup.cursor() as cursor:
                for name in names:
                    cursor.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            cleanup.close()


def _tamper_bundle(bundle: bytes) -> bytes:
    source_buffer = io.BytesIO(bundle)
    output = io.BytesIO()
    with zipfile.ZipFile(source_buffer) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            if name.startswith("documents/"):
                content += b"\nTAMPERED"
            target.writestr(name, content)
    return output.getvalue()


def test_host_a_export_host_b_import_reconciles_and_tamper_rolls_back(pg_host_databases) -> None:
    switch, names = pg_host_databases
    switch(names[0])
    kb_a = knowledge_service.create_knowledge_base("Host A", tenant_id="tenant-portable")
    knowledge_service.add_document_and_chunk(
        knowledge_base_id=kb_a["id"],
        name="Huawei S5700 OSPF",
        content="# OSPF\n\nospf 1\n area 0.0.0.0",
        vendor="Huawei",
        platform="vrp",
        tenant_id="tenant-portable",
        metadata={
            "vendor": "Huawei",
            "cli_platform": "vrp",
            "product_model": "S5700",
            "software_release": "V200R023",
            "source_type": "user_document",
            "document_category": "configuration",
        },
    )
    exported = knowledge_export_service.build_export(tenant_id="tenant-portable")
    assert exported["manifest"]["document_count"] == 1

    switch(names[1])
    imported = import_knowledge_bundle(exported["content"], tenant_id="tenant-portable")
    report = imported["reconciliation"]
    assert report == {
        "manifest_document_count": 1,
        "imported_document_count": 1,
        "vendors": {"Huawei": 1},
        "models": ["S5700"],
        "software_releases": ["V200R023"],
        "source_types": ["user_document"],
        "effective_source_types": ["user_document"],
        "metadata_mismatches": [],
        "embedding_status": "rebuilt_on_destination",
    }
    destination = knowledge_service.list_documents(tenant_id="tenant-portable", page=1, page_size=20)
    assert destination["total"] == 1
    detail = knowledge_service.get_document_detail(destination["items"][0]["id"], tenant_id="tenant-portable")
    assert detail["vendor"] == "Huawei"
    assert detail["metadata"]["product_model"] == "S5700"
    assert detail["metadata"]["software_release"] == "V200R023"

    with pytest.raises(KnowledgeBundleImportError) as exc:
        import_knowledge_bundle(_tamper_bundle(exported["content"]), tenant_id="tenant-portable")
    assert exc.value.code == "KNOWLEDGE_BUNDLE_HASH_MISMATCH"
    assert knowledge_service.list_documents(tenant_id="tenant-portable", page=1, page_size=20)["total"] == 1
