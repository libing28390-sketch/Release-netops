from __future__ import annotations

import io
import json
import queue
import zipfile

import pytest

import database
from ai.services.knowledge_bundle_import_service import KnowledgeBundleImportError, import_knowledge_bundle
from ai.services.knowledge_export_service import knowledge_export_service
from ai.services.knowledge_service import knowledge_service


def _switch_database(path: str) -> None:
    try:
        while True:
            database._pool.get_nowait().close()
    except queue.Empty:
        pass
    database.DB_PATH = path
    database._db_initialized = False
    database.init_db()


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


def test_host_a_export_host_b_import_reconciles_and_tamper_rolls_back(isolated_db, tmp_path) -> None:
    host_a = str(tmp_path / "host-a.db")
    host_b = str(tmp_path / "host-b.db")
    _switch_database(host_a)
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

    _switch_database(host_b)
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
