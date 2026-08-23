from __future__ import annotations

from ai.services.citation_service import (
    answer_contract,
    build_grounded_citations,
    citation_from_chunk,
    refusal_for_missing_evidence,
    validate_citations,
)


def _chunk(**overrides):
    value = {
        "chunk_id": "chunk-1",
        "document_id": "doc-1",
        "document_name": "CE6800 OSPF Guide",
        "section": "验证命令",
        "source": "https://support.example.com/ce6800/ospf?utm_source=nexora",
        "vendor": "Huawei",
        "product_model": "CE6800",
        "platform": "huawei_vrp5_v200",
        "software_release": "V200R022",
        "document_version": "2026.08",
        "document_status": "published",
        "source_trust_level": "official",
        "knowledge_source_type": "official_document",
        "metadata": {"os_family": "VRP", "updated_at": "2026-08-01"},
    }
    value.update(overrides)
    return value


def test_cit_001_contract_contains_identity_and_location_fields():
    citation = citation_from_chunk(_chunk()).to_dict()
    assert citation["vendor"] == "Huawei"
    assert citation["product"] == "CE6800"
    assert citation["os_family"] == "VRP"
    assert citation["software_version"] == "V200R022"
    assert citation["document"] == "CE6800 OSPF Guide"
    assert citation["document_version"] == "2026.08"
    assert citation["url"] == "https://support.example.com/ce6800/ospf"
    assert citation["section"] == "验证命令"
    assert citation["chunk_id"] == "chunk-1"


def test_cit_002_maps_each_grounded_chunk_to_a_conclusion():
    citations, warnings = build_grounded_citations([_chunk(), _chunk(chunk_id="chunk-2", document_id="doc-2")])
    contract = answer_contract(intent="knowledge", citations=citations, grounded=True)
    assert not warnings
    assert len(citations) == 2
    assert contract["conclusion_citations"]["conclusion-1"] == [citations[0]["citation_id"]]
    assert citations[0]["claim_ids"] == ["conclusion-1"]


def test_cit_003_validator_rejects_allowlist_version_and_published_conflicts():
    citation = citation_from_chunk(_chunk())
    accepted, warnings = validate_citations(
        [citation], requested_vendor="Cisco", requested_version="V600", allowed_hosts=["support.example.com"]
    )
    assert accepted == []
    assert {"vendor_conflict", "version_conflict"}.issubset(set(warnings[0]["warnings"]))

    unpublished = citation_from_chunk(_chunk(document_status="draft"))
    accepted, warnings = validate_citations([unpublished])
    assert accepted == []
    assert warnings


def test_cit_003_allows_active_official_rag_projection_without_false_warning():
    citation = citation_from_chunk(_chunk(document_status="active"))
    assert citation.validation == "validated_official"
    assert "official_source_not_published" not in citation.warnings


def test_cit_004_refusal_is_deterministic_and_requests_supplemental_context():
    message = refusal_for_missing_evidence(intent="troubleshooting")
    assert message == refusal_for_missing_evidence(intent="troubleshooting")
    assert "设备型号" in message and "软件版本" in message and "命令输出" in message


def test_cit_005_to_006_answer_contract_marks_and_fault_structure():
    contract = answer_contract(intent="troubleshooting", citations=[], grounded=False, no_match=True)
    assert contract["sections"] == ["judgement", "facts", "gaps", "assumptions", "next_steps", "risk", "remediation", "verification"]
    assert {item["type"] for item in contract["answer_marks"]} == {"fact", "inference", "recommendation", "command"}
    assert contract["no_match"] is True


def test_cit_009_warnings_redact_secrets_and_stale_knowledge_is_visible():
    citation = citation_from_chunk(_chunk(source="https://x.invalid/?api_key=secret", metadata={"stale": True}))
    assert "knowledge_stale" in citation.warnings
    assert citation.url is None
    assert "secret" not in repr(citation).lower()
