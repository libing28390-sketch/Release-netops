import sys
from pathlib import Path


SCRIPTS_DIR = str(Path(__file__).resolve().parents[3] / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from knowledge_eval_anchor_review_check import validate_anchor_review


def test_current_anchor_set_is_claimed_as_human_reviewed():
    report = validate_anchor_review()

    assert report["case_count"] == 50
    assert report["status"] == "PASS"
    assert report["review_status"] == "PASS"
    assert report["gold_status"] == "PASS"
    assert report["database_validation"] == "not_run_source_scan_only"
    assert report["missing_review_field_cases"] == []
    assert report["missing_annotation_field_cases"] == []
    # Bare Ruijie IDs are a supported legacy semantic namespace and are now
    # resolved from the official migration source scan.  The frozen dataset
    # is now fully reviewed; this assertion protects the source-scan contract
    # from regressing to an unresolved-document state.
    assert report["unresolved_gold_document_ids"] == []


def test_anchor_review_pass_requires_review_fields_and_resolved_gold_set():
    dataset = {
        "dataset_id": "synthetic-reviewed-anchor",
        "cases": [
            {
                "id": "SYN-001",
                "query": "How do I configure a VLAN?",
                "expected_outcome": "answer",
                "vendor": "Huawei",
                "platform": "huawei_vrp",
                "feature": "vlan",
                "gold_document_ids": ["official-template-official-huawei-vlan-basic"],
                "acceptable_document_ids": [
                    "official-template-official-huawei-vlan-basic",
                    "official-template-official-huawei-vlan-advanced",
                ],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={
            "official-template-official-huawei-vlan-basic",
            "official-template-official-huawei-vlan-advanced",
        },
    )

    assert report["status"] == "PASS"
    assert report["review_status"] == "PASS"
    assert report["gold_status"] == "PASS"
    assert report["records"][0]["gold_policy"] == "required_acceptable_set"
    assert report["records"][0]["missing_review_fields"] == []


def test_guard_case_does_not_require_gold_document_ids_but_still_requires_review():
    dataset = {
        "dataset_id": "synthetic-guard-anchor",
        "cases": [
            {
                "id": "SYN-002",
                "query": "Show me a dangerous command",
                "expected_outcome": "no_match",
                "vendor": "Cisco",
                "platform": "ios",
                "gold_document_ids": [],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(dataset, known_ids=set())

    assert report["status"] == "PASS"
    assert report["records"][0]["gold_policy"] == "not_required_guard_case"


def test_review_fails_when_known_gold_metadata_conflicts_with_explicit_case_annotation():
    dataset = {
        "dataset_id": "synthetic-metadata-mismatch",
        "cases": [
            {
                "id": "SYN-003",
                "query": "Configure a VLAN",
                "expected_outcome": "answer",
                "vendor": "Huawei",
                "platform": "huawei_vrpv8",
                "feature": "vlan",
                "gold_document_ids": ["doc-wrong-vendor"],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={"doc-wrong-vendor"},
        known_metadata={
            "doc-wrong-vendor": {
                "vendor": "Cisco",
                "cli_platform": "cisco_iosxe",
                "feature": "acl",
            }
        },
    )

    assert report["status"] == "FAIL"
    assert report["review_status"] == "PASS"
    assert report["gold_status"] == "FAIL"
    assert report["metadata_mismatch_cases"] == ["SYN-003"]
    assert report["records"][0]["metadata_validation"]["status"] == "mismatch"


def test_answer_review_requires_explicit_feature_annotation():
    dataset = {
        "dataset_id": "synthetic-missing-feature",
        "cases": [
            {
                "id": "SYN-004",
                "query": "Configure a VLAN",
                "expected_outcome": "answer",
                "vendor": "Huawei",
                "platform": "huawei_vrp",
                "gold_document_ids": ["official-template-official-huawei-vlan-basic"],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={"official-template-official-huawei-vlan-basic"},
    )

    assert report["status"] == "FAIL"
    assert report["review_status"] == "PASS"
    assert report["gold_status"] == "FAIL"
    assert report["missing_annotation_field_cases"] == ["SYN-004"]
    assert report["missing_feature_annotation_cases"] == ["SYN-004"]
    assert report["records"][0]["missing_annotation_fields"] == ["feature"]


def test_hsrp_review_inference_preserves_independent_protocol_feature():
    dataset = {
        "dataset_id": "synthetic-hsrp-inference",
        "cases": [
            {
                "id": "SYN-005",
                "query": "Cisco IOS XE HSRP standby 配置",
                "expected_outcome": "answer",
                "vendor": "Cisco",
                "platform": "cisco_iosxe",
                "intent": "hsrp",
                "gold_document_ids": ["official-template-official-cisco-hsrp-basic"],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={"official-template-official-cisco-hsrp-basic"},
    )

    record = report["records"][0]
    assert record["feature"] == "hsrp"
    assert record["feature_source"] == "query_inference"


def test_port_security_review_inference_precedes_generic_mac_diagnostic():
    dataset = {
        "dataset_id": "synthetic-port-security-inference",
        "cases": [
            {
                "id": "SYN-007",
                "query": "Huawei port-security enable limit MAC count",
                "expected_outcome": "answer",
                "vendor": "Huawei",
                "platform": "huawei_vrp",
                "intent": "security",
                "gold_document_ids": ["official-port-security"],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={"official-port-security"},
    )

    record = report["records"][0]
    assert record["feature"] == "port_security"
    assert record["feature_source"] == "query_inference"


def test_review_flags_any_incompatible_member_of_acceptable_set():
    dataset = {
        "dataset_id": "synthetic-partial-metadata-mismatch",
        "cases": [
            {
                "id": "SYN-006",
                "query": "Cisco Nexus BGP",
                "expected_outcome": "answer",
                "vendor": "Cisco",
                "platform": "cisco_nxos",
                "feature": "bgp",
                "gold_document_ids": ["legacy-gold"],
                "acceptable_document_ids": ["valid-nexus-bgp", "wrong-iosxe-bgp"],
                "reviewer": "reviewer@example.test",
                "reviewed_at": "2026-09-03T00:00:00Z",
                "annotation_status": "approved",
            }
        ],
    }

    report = validate_anchor_review(
        dataset,
        known_ids={"valid-nexus-bgp", "wrong-iosxe-bgp"},
        known_metadata={
            "valid-nexus-bgp": {"vendor": "Cisco", "cli_platform": "cisco_nxos", "feature": "bgp"},
            "wrong-iosxe-bgp": {"vendor": "Cisco", "cli_platform": "cisco_iosxe", "feature": "bgp"},
        },
    )

    assert report["status"] == "FAIL"
    assert report["gold_status"] == "FAIL"
    assert report["metadata_mismatch_cases"] == ["SYN-006"]
    assert report["records"][0]["metadata_validation"]["mismatch_document_ids"] == ["wrong-iosxe-bgp"]
