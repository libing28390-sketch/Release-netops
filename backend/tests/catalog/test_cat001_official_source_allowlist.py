from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.md"
VENDOR_SCOPE = ROOT / "docs" / "knowledge-engine" / "governance" / "vendor-scope.yaml"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _entries(data: dict):
    for vendor in data["vendor_entries"]:
        for host_entry in vendor["official_hosts"]:
            for url in host_entry["source_urls"]:
                yield vendor, host_entry, url


def test_cat001_freezes_exact_two_vendor_scope_and_versions():
    data = _load()
    assert data["task_id"] == "CAT-001"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["policy"]["default_deny"] is True
    assert {item["vendor"] for item in data["vendor_entries"]} == {"Huawei", "Cisco"}
    assert len(data["vendor_entries"]) == 2
    for item in data["vendor_entries"]:
        assert item["primary_version"]
        assert item["compatibility_version"]
        assert item["platform_code"]


def test_cat001_every_registered_url_matches_exact_https_host_and_path():
    data = _load()
    for vendor, host_entry, url in _entries(data):
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.port in (None, 443)
        assert parsed.username is None and parsed.password is None
        assert parsed.fragment == ""
        assert parsed.query == ""
        assert parsed.hostname == host_entry["host"]
        assert any(parsed.path.startswith(prefix) for prefix in host_entry["path_prefixes"])
        assert "*" not in host_entry["host"]
        assert vendor["source_authority"]


def test_cat001_policy_is_fail_closed_and_redirects_revalidate():
    data = _load()
    policy = data["policy"]
    assert policy["schemes"] == ["https"]
    assert policy["ports"] == [443]
    assert policy["exact_host_match"] is True
    assert policy["wildcard_hosts"] == "forbidden"
    assert policy["userinfo"] == "forbidden"
    assert policy["fragments"] == "forbidden"
    assert policy["redirect_policy"]["revalidate_every_hop"] is True
    assert policy["redirect_policy"]["path_must_remain_registered"] is True
    assert data["acceptance"]
    assert data["source_record_contract"]["secrets_forbidden"]


def test_cat001_matches_reviewed_gov008_scope_without_widening_hosts():
    data = _load()
    vendor_scope = yaml.safe_load(VENDOR_SCOPE.read_text(encoding="utf-8"))
    frozen = {(item["vendor"], item["product_family"], item["primary_version"], item["compatibility_version"]) for item in data["vendor_entries"]}
    reviewed = {(item["vendor"], item["product_family"], item["primary_version"], item["compatibility_version"]) for item in vendor_scope["devices"]}
    assert frozen == reviewed
    assert data["vendor_entries"][0]["forbidden_hosts"]
    assert data["vendor_entries"][1]["forbidden_hosts"]


def test_cat001_report_and_rollback_markers_are_present():
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("CAT-001", "Huawei", "Cisco", "HTTPS", "default-deny", "exact", "redirect", "DB-008", "CAT-003", "CAT-004", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker
