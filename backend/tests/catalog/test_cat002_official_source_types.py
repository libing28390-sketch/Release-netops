from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-002-OFFICIAL-SOURCE-TYPES.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-002-OFFICIAL-SOURCE-TYPES.md"
CAT001 = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"
CAT001_EXTENSIONS = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST-EXTENSIONS.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_cat002_freezes_six_explicit_source_types():
    data = _load(CONTRACT)
    assert data["task_id"] == "CAT-002"
    assert data["priority"] == "P0"
    assert data["status"] == "reviewed_for_knowledge_backfill"
    assert [item["code"] for item in data["source_types"]] == [
        "official_url",
        "product_page",
        "configuration_guide",
        "command_reference",
        "troubleshooting_guide",
        "release_note",
    ]
    assert all(item["required_fields"] for item in data["source_types"])
    assert all(item["parser_policy"] for item in data["source_types"])


def test_cat002_type_specific_evidence_and_fail_closed_rules_are_explicit():
    data = _load(CONTRACT)
    by_code = {item["code"]: item for item in data["source_types"]}
    assert "product_name" in by_code["product_page"]["content_expectations"]
    assert "command_context" in by_code["configuration_guide"]["content_expectations"]
    assert "syntax" in by_code["command_reference"]["content_expectations"]
    assert "known_issues" in by_code["release_note"]["content_expectations"]
    assert data["classification"]["unknown_type_behavior"] == "reject_before_fetch_or_index"
    assert data["classification"]["no_model_inference"] is True
    assert data["provenance"]["version_scope"]["unknown_version"] == "quarantine"


def test_cat002_examples_stay_inside_cat001_registered_host_and_paths():
    data = _load(CONTRACT)
    cat001 = _load(CAT001)
    cat001_extensions = _load(CAT001_EXTENSIONS)
    allowed = {}
    for allowlist in (cat001, cat001_extensions):
        for vendor in allowlist["vendor_entries"]:
            allowed.setdefault(vendor["vendor"], []).extend(
                (entry["host"], tuple(entry["path_prefixes"]))
                for entry in vendor["official_hosts"]
            )
    for vendor_name, typed_examples in data["first_batch_examples"].items():
        assert vendor_name in allowed
        for urls in typed_examples.values():
            for url in urls:
                parsed = urlparse(url)
                assert parsed.scheme == "https"
                assert parsed.hostname
                assert parsed.username is None and parsed.password is None
                assert parsed.fragment == ""
                assert parsed.port in (None, 443)
                assert any(host == parsed.hostname and any(parsed.path.startswith(prefix) for prefix in prefixes) for host, prefixes in allowed[vendor_name])


def test_cat002_source_type_never_becomes_authorization_or_write_permission():
    data = _load(CONTRACT)
    assert data["provenance"]["trust_and_authority"]["source_type_not_authorization"] is True
    assert data["provenance"]["trust_and_authority"]["source_type_not_device_write_permission"] is True
    assert data["source_types"][0]["allowed_for_direct_chunking"] is False
    assert data["rollback"]["runtime"]


def test_cat002_report_has_taxonomy_version_security_and_v1_markers():
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("CAT-002", "official_url", "product_page", "configuration_guide", "command_reference", "release_note", "version", "DB-008", "CAT-003", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
