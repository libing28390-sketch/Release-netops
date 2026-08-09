from __future__ import annotations

import copy

import pytest

from services.catalog_version_service import (
    CatalogVersionError,
    import_catalog_version,
    list_catalog_versions,
    preview_catalog_version,
    reset_catalog_version_state_for_tests,
    rollback_catalog_version,
)
from services.product_catalog_service import list_product_aliases, list_product_catalog


DEFAULT_USER = {"id": "cat015-maintainer", "role": "Administrator", "tenant_id": "tenant-default-reviewed"}


@pytest.fixture(autouse=True)
def reset_version_registry():
    reset_catalog_version_state_for_tests()
    yield
    reset_catalog_version_state_for_tests()


def _bundle(user: dict, version: str = "2026.08.09-rc1") -> dict:
    models = copy.deepcopy(list_product_catalog(user)["items"])
    aliases = [
        {
            "id": item["id"],
            "tenant_id": item["tenant_id"],
            "product_model_id": item["product_model_id"],
            "alias": item["alias"],
            "alias_kind": item["alias_kind"],
            "status": item.get("seed_status") or "draft",
        }
        for item in list_product_aliases(user)["items"]
    ]
    return {"version": version, "models": models, "aliases": aliases}


def test_cat015_preview_is_deterministic_and_does_not_activate_candidate():
    bundle = _bundle(DEFAULT_USER)
    bundle["models"][0]["display_name"] += " Release Candidate"
    baseline = list_catalog_versions(DEFAULT_USER)["active_version_id"]
    preview = preview_catalog_version(DEFAULT_USER, bundle)
    assert preview["dry_run"] is True
    assert preview["valid"] is True
    assert preview["can_import"] is True
    assert preview["baseline"]["version_id"] == baseline
    assert preview["diff"]["counts"]["model"]["changed"] == 1
    assert list_catalog_versions(DEFAULT_USER)["active_version_id"] == baseline


def test_cat015_import_switches_active_snapshot_and_rollback_restores_seed():
    bundle = _bundle(DEFAULT_USER)
    original = list_product_catalog(DEFAULT_USER)["items"][0]["display_name"]
    bundle["models"][0]["display_name"] = original + " Imported"
    baseline = list_catalog_versions(DEFAULT_USER)["active_version_id"]
    audit_events: list[tuple[str, dict]] = []
    imported = import_catalog_version(
        DEFAULT_USER,
        bundle,
        expected_active_version_id=baseline,
        confirm=True,
        audit_writer=lambda operation, details: audit_events.append((operation, details)) or "audit-writer-1",
    )
    assert imported["imported"] is True
    assert audit_events[0][0] == "import"
    assert "secret" not in str(audit_events[0][1]).lower()
    assert list_product_catalog(DEFAULT_USER)["items"][0]["display_name"] == original + " Imported"
    rolled_back = rollback_catalog_version(
        DEFAULT_USER,
        baseline,
        expected_active_version_id=imported["active_version_id"],
        confirm=True,
        audit_writer=lambda operation, details: audit_events.append((operation, details)) or "audit-writer-2",
    )
    assert rolled_back["rolled_back"] is True
    assert list_product_catalog(DEFAULT_USER)["items"][0]["display_name"] == original
    history = list_catalog_versions(DEFAULT_USER)
    assert history["active_version_id"] == baseline
    assert len(history["audit_events"]) == 2


def test_cat015_import_requires_confirmation_and_optimistic_baseline():
    bundle = _bundle(DEFAULT_USER)
    with pytest.raises(CatalogVersionError) as unconfirmed:
        import_catalog_version(DEFAULT_USER, bundle, confirm=False)
    assert unconfirmed.value.code == "IMPORT_CONFIRMATION_REQUIRED"
    with pytest.raises(CatalogVersionError) as stale:
        import_catalog_version(DEFAULT_USER, bundle, expected_active_version_id="seed:stale", confirm=True)
    assert stale.value.code == "STALE_ACTIVE_VERSION"


def test_cat015_preview_and_import_fail_closed_for_secret_duplicate_and_cross_tenant_data():
    bundle = _bundle(DEFAULT_USER)
    bundle["models"][0]["metadata_secret"] = "do-not-accept"
    invalid = preview_catalog_version(DEFAULT_USER, bundle)
    assert invalid["valid"] is False
    assert invalid["validation"]["errors"][0]["code"] == "SECRET_FIELD_FORBIDDEN"

    duplicate = _bundle(DEFAULT_USER, "2026.08.09-duplicate")
    duplicate["models"].append(copy.deepcopy(duplicate["models"][0]))
    with pytest.raises(CatalogVersionError) as duplicate_error:
        import_catalog_version(DEFAULT_USER, duplicate, confirm=True)
    assert duplicate_error.value.code == "MODEL_DUPLICATE"

    cross_tenant = _bundle(DEFAULT_USER, "2026.08.09-cross-tenant")
    cross_tenant["models"][0]["tenant_id"] = "tenant-other"
    with pytest.raises(CatalogVersionError) as tenant_error:
        import_catalog_version(DEFAULT_USER, cross_tenant, confirm=True)
    assert tenant_error.value.code == "TENANT_SCOPE_DENIED"


def test_cat015_api_contract_and_permission_profile_are_explicit():
    from core.rbac import RECOMMENDED_ROLE_PROFILES, permission_catalog
    from api.knowledge_catalog import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge-v2/catalog/versions") and "GET" in methods for path, methods in paths)
    assert any(path.endswith("/versions/preview") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/versions/import") and "POST" in methods for path, methods in paths)
    assert any(path.endswith("/versions/{version_id}/rollback") and "POST" in methods for path, methods in paths)
    assert set(permission_catalog()["knowledge_catalog"]) >= {"import", "rollback"}
    assert "import" not in RECOMMENDED_ROLE_PROFILES["Platform Viewer"]["knowledge_catalog"]
    assert set(RECOMMENDED_ROLE_PROFILES["Platform Maintainer"]["knowledge_catalog"]) >= {"import", "rollback"}
