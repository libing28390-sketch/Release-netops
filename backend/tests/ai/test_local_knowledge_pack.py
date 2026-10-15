from __future__ import annotations

import json
import zipfile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_local_pack_builds_the_four_vendor_core_matrix_without_network(tmp_path: Path) -> None:
    from ai.security.classification import classify_text
    from build_local_knowledge_pack import CORE_FEATURES, VENDORS, build_pack

    catalog = ROOT / "data" / "kb_import" / "source_catalog.yaml"
    first_archive = tmp_path / "first.zip"
    first_source = tmp_path / "first-source"
    first_manifest = tmp_path / "first-manifest.json"
    first_coverage = tmp_path / "first-coverage.json"

    result = build_pack(
        catalog_path=catalog,
        source_dir=first_source,
        manifest_path=first_manifest,
        coverage_path=first_coverage,
        archive_path=first_archive,
    )

    assert result["status"] == "PASS"
    assert result["document_count"] == 94
    assert result["vendors"] == list(VENDORS)
    assert result["core_feature_count"] == len(CORE_FEATURES) == 10
    assert result["core_document_count"] == 40
    assert result["supplemental_document_count"] == 40
    assert result["special_document_count"] == 14
    assert result["gold_400_case_count"] == 400
    assert result["anchor_answer_case_count"] == 44
    assert result["anchor_candidate_mapped_case_count"] == 42

    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    coverage = json.loads(first_coverage.read_text(encoding="utf-8"))
    documents = sorted(first_source.rglob("*.md"))
    assert len(documents) == 94
    assert manifest["test_only"] is True
    assert manifest["production_eligible"] is False
    assert manifest["gold_replacement"] is False
    assert manifest["secrets"] is False
    assert manifest["document_count"] == len(documents)
    assert manifest["core_document_count"] == 40
    assert manifest["supplemental_document_count"] == 40
    assert manifest["special_document_count"] == 14
    assert manifest["schema_version"] == "knowledge-export-v1"
    assert manifest["pack_schema_version"] == 1
    assert manifest["embeddings_exported"] is False
    assert manifest["reindex_required_on_import"] is True

    core_pairs = {
        (item["vendor"], item["feature"])
        for item in manifest["documents"]
        if item["feature"] in CORE_FEATURES
    }
    assert core_pairs == {(vendor, feature) for vendor in VENDORS for feature in CORE_FEATURES}

    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "test_only: true" in text
        assert "production_eligible: false" in text
        assert "review_status: source_provenance_verified" in text
        assert not any(
            finding.category
            in {
                "credential",
                "private_key",
                "snmp_community",
                "radius_or_tacacs_key",
                "jwt",
                "cookie",
            }
            for finding in classify_text(text)
        )

    anchor_cases = coverage["anchor_50"]["cases"]
    anchor_by_id = {item["id"]: item for item in anchor_cases}
    assert anchor_by_id["ANCHOR-017"]["candidate_document_ids"] == [
        "local.huawei.vrp.vxlan_evpn.v1"
    ]
    assert anchor_by_id["ANCHOR-003"]["candidate_document_ids"] == [
        "local.huawei.vrp.interface_status_ce6885.v1"
    ]
    assert anchor_by_id["ANCHOR-016"]["candidate_document_ids"] == [
        "local.huawei.vrp.ospf_bfd.v1"
    ]
    assert anchor_by_id["ANCHOR-020"]["candidate_document_ids"] == [
        "local.huawei.vrp.super_password.v1"
    ]
    assert anchor_by_id["ANCHOR-028"]["candidate_document_ids"] == [
        "local.cisco.iosxe.aaa_authentication.v1"
    ]
    assert anchor_by_id["ANCHOR-035"]["candidate_document_ids"] == [
        "local.ruijie.ruijie_rgos.access_port.v1"
    ]
    assert anchor_by_id["ANCHOR-036"]["candidate_document_ids"] == [
        "local.ruijie.ruijie_rgos.lacp.v1"
    ]
    assert anchor_by_id["ANCHOR-037"]["candidate_document_ids"] == [
        "local.ruijie.ruijie_rgos.static_route.v1"
    ]
    assert anchor_by_id["ANCHOR-038"]["candidate_document_ids"] == [
        "local.ruijie.ruijie_rgos.ospf.v1"
    ]
    assert anchor_by_id["ANCHOR-040"]["candidate_document_ids"] == [
        "local.ruijie.ruijie_rgos.acl.v1"
    ]

    verification_ids = {
        item["document_id"]
        for item in manifest["documents"]
        if ".verification.v1" in item["document_id"]
    }
    assert len(verification_ids) == 40
    assert {
        vendor: sum(
            document_id.startswith(f"local.{vendor.casefold()}.")
            for document_id in verification_ids
        )
        for vendor in VENDORS
    } == {vendor: 10 for vendor in VENDORS}

    # The generated artifact must be consumable by the same bounded ZIP
    # importer used for ordinary knowledge exports.  This catches drift in
    # the member path, schema version, and hash field names before any DB work.
    from ai.services.knowledge_bundle_import_service import _read_bundle

    with zipfile.ZipFile(first_archive) as archive:
        archive_members = set(archive.namelist())
    imported_manifest, imported_documents = _read_bundle(first_archive.read_bytes())
    assert imported_manifest["schema_version"] == "knowledge-export-v1"
    assert len(imported_documents) == 94
    assert all(item["path"].startswith("documents/") for item in imported_documents)
    assert all(item["path"] in archive_members for item in imported_documents)
    assert all("content_sha256" in item["manifest"] for item in imported_documents)
    assert all("content_bytes" in item["manifest"] for item in imported_documents)


def test_local_pack_archive_is_deterministic(tmp_path: Path) -> None:
    from build_local_knowledge_pack import build_pack

    catalog = ROOT / "data" / "kb_import" / "source_catalog.yaml"
    first_archive = tmp_path / "first.zip"
    second_archive = tmp_path / "second.zip"

    build_pack(
        catalog_path=catalog,
        source_dir=tmp_path / "first-source",
        manifest_path=tmp_path / "first-manifest.json",
        coverage_path=tmp_path / "first-coverage.json",
        archive_path=first_archive,
    )
    build_pack(
        catalog_path=catalog,
        source_dir=tmp_path / "second-source",
        manifest_path=tmp_path / "second-manifest.json",
        coverage_path=tmp_path / "second-coverage.json",
        archive_path=second_archive,
    )

    assert first_archive.read_bytes() == second_archive.read_bytes()


def test_local_pack_imports_and_retrieves_in_an_isolated_postgres_tenant(
    isolated_db,
    tmp_path: Path,
) -> None:
    """Exercise the complete local-pack path without changing shared Gold data."""

    from ai.services.knowledge_bundle_import_service import import_knowledge_bundle
    from ai.services.knowledge_service import knowledge_service
    from ai.services.rag_retriever import rag_retriever
    from build_local_knowledge_pack import build_pack
    import database

    archive_path = tmp_path / "local-pack.zip"
    build_pack(
        catalog_path=ROOT / "data" / "kb_import" / "source_catalog.yaml",
        source_dir=tmp_path / "source",
        manifest_path=tmp_path / "manifest.json",
        coverage_path=tmp_path / "coverage.json",
        archive_path=archive_path,
    )
    tenant_id = "tenant-local-pack-e2e"
    knowledge_base = knowledge_service.create_knowledge_base(
        "Local pack E2E",
        tenant_id=tenant_id,
    )

    imported = import_knowledge_bundle(
        archive_path.read_bytes(),
        tenant_id=tenant_id,
        knowledge_base_id=knowledge_base["id"],
    )

    assert imported["success"] is True
    assert imported["document_count"] == 94
    assert imported["official_claims"] == "downgraded_to_user_document"
    assert imported["reconciliation"]["vendors"] == {
        "Cisco": 24,
        "H3C": 22,
        "Huawei": 26,
        "Ruijie": 22,
    }

    with database.get_db_connection() as conn:
        raw_rows = conn.execute(
            "SELECT tenant_id, status, knowledge_source_type, COUNT(*) "
            "FROM ai_document WHERE knowledge_base_id = ? "
            "GROUP BY tenant_id, status, knowledge_source_type "
            "ORDER BY tenant_id, status, knowledge_source_type",
            (knowledge_base["id"],),
        ).fetchall()
    assert {(row[0], row[1], row[2], int(row[3])) for row in raw_rows} == {
        ("tenant-default", "active", "user_document", 94),
    }

    documents = knowledge_service.list_documents(
        knowledge_source_type="user_document",
        tenant_id=tenant_id,
        page=1,
        page_size=100,
        sort_by="created_at",
        sort_order="asc",
    )
    assert documents["total"] == 94
    assert {item["vendor"] for item in documents["items"]} == {
        "Cisco",
        "H3C",
        "Huawei",
        "Ruijie",
    }
    with __import__("database").get_db_connection() as conn:
        trust_rows = conn.execute(
            "SELECT source_trust_level, knowledge_source_type, COUNT(*) "
            "FROM ai_document WHERE knowledge_base_id = ? GROUP BY source_trust_level, knowledge_source_type",
            (knowledge_base["id"],),
        ).fetchall()
    assert {(row[0], row[1], int(row[2])) for row in trust_rows} == {
        ("internal", "user_document", 94),
    }

    retrieved = rag_retriever.retrieve(
        "Ruijie RGOS access port 配置和核验命令",
        top_k=5,
        vendor="Ruijie",
        feature="access_port",
        tenant_id=tenant_id,
        knowledge_scope="enterprise",
    )
    assert retrieved
    assert retrieved[0]["document_id"] == "local.ruijie.ruijie_rgos.access_port.v1"
    assert all(item["vendor"] == "Ruijie" for item in retrieved)
