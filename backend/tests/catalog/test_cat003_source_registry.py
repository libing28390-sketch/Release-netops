from __future__ import annotations

import hashlib

import pytest


def _internal_payload(url: str = "https://kb.internal.example/docs/network") -> dict:
    return {
        "source_type": "internal",
        "source_kind": "internal",
        "canonical_url": url,
        "name": "Internal network guide",
        "trust_level": "reviewed",
        "metadata": {"owner": "network-team"},
    }


def test_cat003_create_validate_enable_disable_and_tenant_scope(isolated_db, make_user):
    from services.source_registry_service import (
        SourceRegistryError,
        create_source,
        disable_source,
        enable_source,
        get_source,
        validate_source,
    )

    operator = make_user("cat003-operator", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload(), operator)
    assert source["status"] == "draft"
    assert source["fetch_enabled"] is False
    validation = validate_source(source["id"], operator)
    assert validation["valid"] is True
    enabled = enable_source(source["id"], operator)
    assert enabled["status"] == "active"
    assert enabled["fetch_enabled"] is True
    disabled = disable_source(source["id"], operator, reason="maintenance")
    assert disabled["status"] == "disabled"
    assert disabled["fetch_enabled"] is False
    assert get_source(source["id"], operator)["status"] == "disabled"

    other_tenant = make_user("cat003-other", role="Administrator", tenant_id="tenant-other")
    with pytest.raises(SourceRegistryError) as denied:
        get_source(source["id"], other_tenant)
    assert denied.value.code == "SOURCE_NOT_FOUND"


def test_cat003_official_validation_fails_closed_until_catalog_review(isolated_db, make_user):
    from services.source_registry_service import SourceRegistryError, create_source, enable_source, validate_source

    operator = make_user("cat003-reviewer", role="Administrator", tenant_id="tenant-default")
    source = create_source(
        {
            "source_type": "command_reference",
            "canonical_url": "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html",
            "metadata": {
                "vendor": "Cisco",
                "product_family": "Catalyst 9300",
                "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
                "terms_review_status": "approved",
            },
        },
        operator,
    )
    result = validate_source(source["id"], operator)
    assert result["valid"] is True
    assert enable_source(source["id"], operator)["status"] == "active"

    bad = create_source(
        {
            "source_type": "official_product",
            "canonical_url": "https://www.cisco.com/unsupported/path",
            "metadata": {
                "vendor": "Cisco",
                "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
                "terms_review_status": "approved",
            },
        },
        operator,
    )
    failed = validate_source(bad["id"], operator)
    assert failed["valid"] is False
    with pytest.raises(SourceRegistryError) as exc:
        enable_source(bad["id"], operator)
    assert exc.value.code == "SOURCE_VALIDATION_FAILED"


def test_cat003_policy_change_requires_revalidation_and_source_version_is_append_only(isolated_db, make_user):
    from services.source_registry_service import (
        SourceRegistryError,
        create_source,
        enable_source,
        list_source_versions,
        record_source_version,
        update_source,
    )

    operator = make_user("cat003-version", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload("https://kb.internal.example/docs/versioned"), operator)
    enable_source(source["id"], operator)
    payload = b"version-one"
    version = record_source_version(
        source["id"],
        {
            "content": payload,
            "parser_name": "plain-text",
            "parser_version": "1.0.0",
            "status": "verified",
        },
        operator,
    )
    assert version["content_hash"] == hashlib.sha256(payload).hexdigest()
    duplicate = record_source_version(
        source["id"],
        {
            "content_hash": version["content_hash"],
            "byte_size": len(payload),
            "parser_name": "plain-text",
            "parser_version": "1.0.0",
        },
        operator,
    )
    assert duplicate["deduplicated"] is True
    assert len(list_source_versions(source["id"], operator)) == 1

    changed = update_source(source["id"], {"collection_policy": {"timeout_seconds": 20}}, operator)
    assert changed["status"] == "disabled"
    assert changed["validation_status"] == "unvalidated"
    with pytest.raises(SourceRegistryError) as blocked:
        record_source_version(source["id"], {"content": "x", "parser_name": "p", "parser_version": "1"}, operator)
    assert blocked.value.code == "SOURCE_NOT_ACTIVE"


def test_cat003_api_contract_exposes_crud_lifecycle_validation_and_versions():
    from api.knowledge_sources import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge/sources") and "GET" in methods for path, methods in paths)
    assert any(path.endswith("/knowledge/sources/{source_id}") and "PATCH" in methods for path, methods in paths)
    assert any(path.endswith("/{source_id}/validate") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/{source_id}/enable") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/{source_id}/disable") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/{source_id}/versions") and "POST" in methods for path, methods in paths)


def test_kui015_source_refresh_status_is_bounded_and_tenant_scoped(isolated_db, make_user):
    from services.source_registry_service import (
        create_source,
        enable_source,
        get_source_refresh_status,
        record_source_refresh_observation,
        SourceRegistryError,
    )

    operator = make_user("kui015-status", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload("https://kb.internal.example/docs/kui015"), operator)
    enable_source(source["id"], operator)
    record_source_refresh_observation(
        source["id"],
        {
            "request_method": "GET",
            "http_status": 200,
            "outcome": "unchanged",
            "content_hash": "",
            "error": {},
            "metadata": {"worker": "test"},
        },
        operator,
    )
    status = get_source_refresh_status(source["id"], operator)
    assert status["freshness_status"] == "healthy"
    assert status["observation_count"] == 1
    assert status["counts"]["unchanged"] == 1
    assert "body" not in str(status).lower()
    other = make_user("kui015-other", role="Administrator", tenant_id="tenant-kui015-other")
    with pytest.raises(SourceRegistryError) as denied:
        get_source_refresh_status(source["id"], other)
    assert denied.value.code == "SOURCE_NOT_FOUND"

    from api.knowledge_sources import router
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/{source_id}/refresh-status") and "GET" in methods for path, methods in paths)
