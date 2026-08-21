"""MIG-011 / MIG-012 / MIG-013 Feature Flag and Staged Rollout Tests."""

from __future__ import annotations

import pytest
from ai.services.feature_flag_service import feature_flag_service


@pytest.fixture(autouse=True)
def clean_overrides():
    feature_flag_service.clear_runtime_overrides()
    yield
    feature_flag_service.clear_runtime_overrides()


def test_mig011_global_disabled_routes_all_to_v1():
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", False)

    # Admin user
    enabled, reason, _ = feature_flag_service.evaluate_v2_access({
        "user_id": "admin-1",
        "roles": ["admin"],
        "tenant_id": "tenant-1",
    })
    assert enabled is False
    assert reason == "global_disabled"

    # Regular user
    enabled, reason, _ = feature_flag_service.evaluate_v2_access({
        "user_id": "user-1",
        "roles": ["operator"],
        "tenant_id": "tenant-1",
    })
    assert enabled is False
    assert reason == "global_disabled"


def test_mig011_admin_and_pilot_roles_bypass_to_v2():
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", True)
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ROLLOUT_PERCENT", 0)

    # Admin role
    enabled, reason, meta = feature_flag_service.evaluate_v2_access({
        "user_id": "admin-1",
        "roles": ["admin"],
        "tenant_id": "tenant-1",
    })
    assert enabled is True
    assert reason == "pilot_role_match"
    assert "admin" in meta["matched_roles"]

    # Knowledge Admin role
    enabled, reason, meta = feature_flag_service.evaluate_v2_access({
        "user_id": "kb-admin-1",
        "roles": ["knowledge_admin"],
        "tenant_id": "tenant-1",
    })
    assert enabled is True
    assert reason == "pilot_role_match"

    # Regular user with 0% rollout -> routes to V1
    enabled, reason, _ = feature_flag_service.evaluate_v2_access({
        "user_id": "user-1",
        "roles": ["operator"],
        "tenant_id": "tenant-1",
    })
    assert enabled is False
    assert reason == "rollout_percent_zero"


def test_mig012_pilot_users_and_sites_whitelisting():
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", True)
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ROLLOUT_PERCENT", 0)
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_PILOT_USERS", ["pilot-engineer-a", "pilot-engineer-b"])
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED_SITES", ["site-shanghai-dc1"])

    # Whitelisted pilot user
    enabled, reason, meta = feature_flag_service.evaluate_v2_access({
        "user_id": "pilot-engineer-a",
        "roles": ["operator"],
        "tenant_id": "tenant-1",
    })
    assert enabled is True
    assert reason == "pilot_user_whitelist"
    assert meta["user_id"] == "pilot-engineer-a"

    # Whitelisted site
    enabled, reason, meta = feature_flag_service.evaluate_v2_access({
        "user_id": "engineer-random",
        "roles": ["operator"],
        "site_ids": ["site-shanghai-dc1"],
        "tenant_id": "tenant-1",
    })
    assert enabled is True
    assert reason == "pilot_site_whitelist"
    assert "site-shanghai-dc1" in meta["matched_sites"]

    # Non-whitelisted user and site
    enabled, reason, _ = feature_flag_service.evaluate_v2_access({
        "user_id": "engineer-random",
        "roles": ["operator"],
        "site_ids": ["site-beijing-dc2"],
        "tenant_id": "tenant-1",
    })
    assert enabled is False


def test_mig012_percentage_rollout_deterministic_hashing():
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", True)
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ROLLOUT_PERCENT", 50)
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_PILOT_ROLES", [])

    hits = 0
    total = 200
    for i in range(total):
        uid = f"user-test-{i}"
        enabled, _, _ = feature_flag_service.evaluate_v2_access({
            "user_id": uid,
            "roles": ["operator"],
            "tenant_id": "tenant-1",
        })
        # Test determinism: same user call twice yields same result
        enabled2, _, _ = feature_flag_service.evaluate_v2_access({
            "user_id": uid,
            "roles": ["operator"],
            "tenant_id": "tenant-1",
        })
        assert enabled == enabled2
        if enabled:
            hits += 1

    # At 50% rollout, distribution should be around 50% (+/- 15% across 200 samples)
    ratio = hits / total
    assert 0.35 <= ratio <= 0.65


def test_mig013_hot_switching_and_emergency_fallback():
    # Start enabled for admin
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", True)
    ctx = {"user_id": "admin-1", "roles": ["admin"], "tenant_id": "tenant-1"}
    assert feature_flag_service.is_v2_enabled(ctx) is True

    # Emergency cutover: disable globally in runtime
    feature_flag_service.set_runtime_override("KNOWLEDGE_V2_ENABLED", False)
    assert feature_flag_service.is_v2_enabled(ctx) is False

    # Request-level override takes precedence when debugging
    assert feature_flag_service.is_v2_enabled(ctx, request_override=True) is True
    assert feature_flag_service.is_v2_enabled(ctx, request_override=False) is False
