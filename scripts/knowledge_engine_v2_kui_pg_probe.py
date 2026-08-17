"""PostgreSQL-only KUI-001..KUI-008 document-management probe.

The regular pytest fixture intentionally uses SQLite for compatibility tests;
this probe exercises the real PostgreSQL connection and rolls every fixture
write back.  It verifies semantic filters, tenant isolation, pagination and
the rule that the internal ``kb_import`` prefix never appears in the response
summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402
from ai.services import knowledge_service as knowledge_service_module  # noqa: E402


class _SameConnectionContext:
    def __init__(self, connection: Any):
        self.connection = connection

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("KUI PostgreSQL gate refused to run: DATABASE_URL is not PostgreSQL")

    conn = core.get_db_connection()
    cur = conn.cursor()
    kb = cur.execute("SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1").fetchone()
    if not kb:
        conn.rollback()
        conn.close()
        raise RuntimeError("KUI PostgreSQL probe requires an existing ai_knowledge_base")

    knowledge_base_id = str(kb[0])
    doc_ids = ("__kui_pg_probe_huawei", "__kui_pg_probe_other_tenant")
    now = "2026-08-17T00:00:00+00:00"
    original_get_db_connection = knowledge_service_module.get_db_connection
    try:
        cur.execute(
            "INSERT INTO ai_document "
            "(id, knowledge_base_id, name, source, vendor, platform, status, "
            "knowledge_source_type, tenant_id, acl_json, source_trust_level, metadata_json, "
            "product_family, product_series, product_model, os_family, software_release, "
            "feature_domain, document_category, created_at, updated_at) "
            "VALUES (?, ?, ?, 'upload', ?, ?, 'active', ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_ids[0], knowledge_base_id, "KUI Huawei OSPF", "Huawei", "huawei_vrp",
                "official_vendor", "tenant-kui-a", "official", '{"knowledge_directory_path":"__kui_probe_unique/huawei"}',
                "CloudEngine", "CE6800", "CE6885", "VRP", "V800R022", "ospf", "01_product", now, now,
            ),
        )
        cur.execute(
            "INSERT INTO ai_document "
            "(id, knowledge_base_id, name, source, vendor, platform, status, "
            "knowledge_source_type, tenant_id, acl_json, source_trust_level, metadata_json, "
            "product_family, product_series, product_model, os_family, software_release, "
            "feature_domain, document_category, created_at, updated_at) "
            "VALUES (?, ?, ?, 'upload', ?, ?, 'active', ?, ?, '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_ids[1], knowledge_base_id, "KUI Other Tenant", "Huawei", "huawei_vrp",
                "official_vendor", "tenant-kui-b", "official", '{"knowledge_directory_path":"__kui_probe_unique/huawei"}',
                "CloudEngine", "CE6800", "CE6885", "VRP", "V800R022", "ospf", "01_product", now, now,
            ),
        )
        cur.execute("INSERT INTO ai_document_chunk (id, document_id, content, created_at) VALUES (?, ?, ?, ?)", ("__kui_pg_probe_chunk", doc_ids[0], "ospf evidence", now))

        knowledge_service_module.get_db_connection = lambda: _SameConnectionContext(conn)
        result = knowledge_service_module.KnowledgeService().list_documents(
            tenant_id="tenant-kui-a",
            vendor="Huawei",
            product_family="CloudEngine",
            product_model="CE6885",
            os_family="VRP",
            software_release="V800R022",
            feature_domain="ospf",
            document_category="01_product",
            page=1,
            page_size=1,
        )
        if result["total"] != 1 or result["items"][0]["id"] != doc_ids[0]:
            raise AssertionError(f"semantic filter result mismatch: {result}")
        if "kb_import" in json.dumps(result, ensure_ascii=False):
            raise AssertionError("internal kb_import prefix leaked into KUI response")

        facets = knowledge_service_module.KnowledgeService().list_document_facets(
            tenant_id="tenant-kui-a",
            directory_path="__kui_probe_unique/huawei",
        )
        if facets["vendors"] != [{"value": "Huawei", "count": 1}]:
            raise AssertionError(f"facet vendor mismatch: {facets}")
        if facets["families"] != [{"value": "CloudEngine", "count": 1}]:
            raise AssertionError(f"facet family mismatch: {facets}")
        if facets["series"] != [{"value": "CE6800", "count": 1}]:
            raise AssertionError(f"facet series mismatch: {facets}")
        if "kb_import" in json.dumps(facets, ensure_ascii=False):
            raise AssertionError("internal kb_import prefix leaked into KUI facets")

        detail = knowledge_service_module.KnowledgeService().get_document_detail(
            doc_ids[0], tenant_id="tenant-kui-a"
        )
        if not detail or detail["raw_source"]["source"] != "upload" or "source_version_history" not in detail:
            raise AssertionError(f"detail contract mismatch: {detail}")

        visible_ids = {item["id"] for item in knowledge_service_module.KnowledgeService().list_documents(tenant_id="tenant-kui-a", page_size=100)["items"]}
        if doc_ids[1] in visible_ids or doc_ids[0] not in visible_ids:
            raise AssertionError("tenant isolation failed in KUI document list")

        return {
            "postgresql": True,
            "semantic_filter": True,
            "tenant_isolation": True,
            "pagination": result["page_size"] == 1 and result["total_pages"] == 1,
            "product_facets": True,
            "detail_contract": True,
            "internal_path_redaction": True,
        }
    finally:
        knowledge_service_module.get_db_connection = original_get_db_connection
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(_run(), ensure_ascii=False, sort_keys=True))
