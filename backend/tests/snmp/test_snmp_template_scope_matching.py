from __future__ import annotations

import json

import pytest
import database

from services.monitoring_compiler import variant_matches_device
from services.snmp_metric_profile_service import (
    create_model_metric_profile,
    invalidate_metric_profile_cache,
    profile_scope_match,
    resolve_metric_profile_candidate,
)


def _metric(oid: str) -> dict[str, str]:
    return {"mode": "direct_percent", "oid": oid}


def test_profile_scope_matches_vendor_platform_model_and_version() -> None:
    profile = {
        "vendor": "H3C",
        "model": "S6800",
        "model_pattern": "S6800-*",
        "platforms": ["h3c_comware_v7"],
        "software_version_scope": ["Comware V7"],
    }
    assert profile_scope_match(
        profile,
        {"vendor": "H3C", "platform": "h3c_comware_v7", "model": "S6800-54QT", "version": "7.1.070"},
    )["matched"]
    assert not profile_scope_match(
        profile,
        {"vendor": "H3C", "platform": "h3c_comware_v5", "model": "S6800-54QT", "version": "5.20"},
    )["matched"]


def test_candidate_resolver_prefers_specific_scope_and_reports_ties(monkeypatch: pytest.MonkeyPatch) -> None:
    profiles = {
        "p-default": {
            "profile_id": "p-default", "profile_vendor": "H3C", "profile_model": "S6800",
            "model_pattern": "S6800-*", "platforms": [], "software_versions": [], "metrics": {"cpu": _metric("1.3.6.1.1")},
            "configured": True, "interface_configured": False,
        },
        "p-v7": {
            "profile_id": "p-v7", "profile_vendor": "H3C", "profile_model": "S6800",
            "model_pattern": "S6800-*", "platforms": ["h3c_comware_v7"], "software_versions": ["Comware V7"], "metrics": {"cpu": _metric("1.3.6.1.2")},
            "configured": True, "interface_configured": False,
        },
        "p-v7-duplicate": {
            "profile_id": "p-v7-duplicate", "profile_vendor": "H3C", "profile_model": "S6800",
            "model_pattern": "S6800-*", "platforms": ["h3c_comware_v7"], "software_versions": ["Comware V7"], "metrics": {"cpu": _metric("1.3.6.1.3")},
            "configured": True, "interface_configured": False,
        },
    }
    monkeypatch.setattr("services.snmp_metric_profile_service._load_profile_cache", lambda: profiles)
    selected = resolve_metric_profile_candidate({"vendor": "H3C", "platform": "h3c_comware_v7", "model": "S6800-54QT", "version": "7.1.070"})
    assert selected["status"] == "ambiguous"
    assert {item["profile_id"] for item in selected["candidates"][:2]} == {"p-v7", "p-v7-duplicate"}


def test_create_profile_persists_scope_fields(isolated_db) -> None:
    connection = database.get_db_connection()
    try:
        profile = create_model_metric_profile(
            connection,
            {
                "vendor": "H3C",
                "model": "S6800",
                "platforms": ["h3c_comware_v7", "h3c_comware_v9"],
                "model_pattern": "S6800-*",
                "software_version_scope": ["Comware V7", "Comware V9"],
                "min_version": "7.0",
                "max_version": "9.9",
                "excluded_versions": ["7.1.001"],
                "scope_priority": 20,
                "metric_definitions": {"cpu": _metric("1.3.6.1.4.1.25506.2.6.1.1.1.1.6")},
            },
            updated_by="test",
        )
        connection.commit()
        row = connection.execute(
            "SELECT platform_key, platform_scope_json, model_pattern, software_version_scope_json, min_version, max_version, excluded_versions_json, scope_priority FROM snmp_metric_profiles WHERE id = ?",
            (profile["id"],),
        ).fetchone()
        assert row[0] == "h3c_comware_v7"
        assert json.loads(row[1]) == ["h3c_comware_v7", "h3c_comware_v9"]
        assert row[2] == "S6800-*"
        assert json.loads(row[3]) == ["Comware V7", "Comware V9"]
        assert row[4] == "7.0"
        assert row[5] == "9.9"
        assert row[6] == '["7.1.001"]'
        assert row[7] == 20
    finally:
        invalidate_metric_profile_cache()
        connection.close()


def test_monitoring_variant_scope_rejects_wrong_h3c_generation() -> None:
    variant = {
        "supported_platforms": ["h3c_comware_v7", "h3c_comware_v9"],
        "supported_models": ["S6800", "S10500"],
        "supported_version_scope": ["Comware V7", "Comware V9"],
    }
    assert variant_matches_device(variant, {"platform": "h3c_comware_v7", "model": "S6800-54QT", "version": "7.1.070"})
    assert not variant_matches_device(variant, {"platform": "h3c_comware_v5", "model": "S10500", "version": "5.20"})
