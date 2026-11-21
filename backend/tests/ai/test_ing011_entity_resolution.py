from __future__ import annotations

from types import SimpleNamespace

from services.document_entity_resolution import (
    EntityResolutionOutcome,
    _canonical_vendor,
    resolve_document_entities,
)


TENANT = "tenant-a"


def test_chinese_h3c_aliases_are_canonicalized_before_catalog_matching():
    assert _canonical_vendor("华三") == "h3c"
    assert _canonical_vendor("新华三") == "h3c"


def _catalog(*, tenant_id: str = TENANT, is_seed: bool = False) -> dict:
    models = [
        {
            "product_model_id": "cisco:catalyst_9300:c9300:c9300-48p",
            "tenant_id": tenant_id,
            "vendor_id": "cisco",
            "vendor_name": "Cisco",
            "family_code": "catalyst_9300",
            "family_name": "Catalyst 9300",
            "series_code": "c9300",
            "series_name": "Catalyst 9300",
            "model_code": "C9300-48P",
            "display_name": "Catalyst C9300-48P",
            "status": "active",
            "review_status": "approved",
            "software_scope": {
                "os_family": "IOS-XE",
                "os_generation": "iosxe",
                "software_train": "IOS-XE",
                "software_versions": ["17.9.4"],
            },
            "platform_binding_advisory": {"cli_platform": "cisco_ios_xe"},
        },
        {
            "product_model_id": "cisco:catalyst_9300:c9300:c9300-48u",
            "tenant_id": tenant_id,
            "vendor_id": "cisco",
            "vendor_name": "Cisco",
            "family_code": "catalyst_9300",
            "family_name": "Catalyst 9300",
            "series_code": "c9300",
            "series_name": "Catalyst 9300",
            "model_code": "C9300-48U",
            "display_name": "Catalyst C9300-48U",
            "status": "active",
            "review_status": "approved",
            "software_scope": {
                "os_family": "IOS-XE",
                "os_generation": "iosxe",
                "software_train": "IOS-XE",
                "software_versions": ["17.9.4"],
            },
            "platform_binding_advisory": {"cli_platform": "cisco_ios_xe"},
        },
    ]
    return {
        "tenant_id": tenant_id,
        "version_id": "v-test",
        "is_seed": is_seed,
        "models": models,
        "aliases": [
            {
                "tenant_id": tenant_id,
                "product_model_id": models[0]["product_model_id"],
                "alias": "Catalyst C9300-48P",
                "alias_kind": "canonical",
                "status": "active",
            },
            {
                "tenant_id": tenant_id,
                "product_model_id": models[0]["product_model_id"],
                "alias": "C9300",
                "alias_kind": "prefix",
                "status": "active",
            },
            {
                "tenant_id": tenant_id,
                "product_model_id": models[1]["product_model_id"],
                "alias": "C9300",
                "alias_kind": "prefix",
                "status": "active",
            },
        ],
    }


def _metadata(**overrides):
    value = {
        "vendor": "Cisco",
        "product_model": "C9300-48P",
        "os_family": "IOS-XE",
        "software_train": "IOS-XE",
        "software_release": "17.9.4",
    }
    value.update(overrides)
    return value


def test_exact_model_os_and_version_resolve_without_driver_authority():
    result = resolve_document_entities(_metadata(), tenant_id=TENANT, catalog=_catalog())

    assert result.outcome is EntityResolutionOutcome.RESOLVED
    assert result.retrieval_eligible is True
    assert result.product["model_code"] == "C9300-48P"
    assert result.version["normalized"] == "17.9.4"
    assert result.retrieval_filters["cli_platform"] == "cisco_ios_xe"
    assert result.driver_selection_allowed is False


def test_canonical_alias_can_resolve_one_active_model():
    result = resolve_document_entities(
        _metadata(product_model="Catalyst C9300-48P"),
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.RESOLVED
    assert result.product["product_model_id"].endswith("c9300-48p")


def test_prefix_alias_returns_candidates_and_never_first_match():
    result = resolve_document_entities(
        _metadata(product_model="C9300"),
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.AMBIGUOUS
    assert len(result.candidates) == 2
    assert result.retrieval_eligible is False
    assert "product_model" in result.clarification_fields


def test_unknown_model_does_not_infer_from_body_text():
    result = resolve_document_entities(
        {"normalized_content": "Cisco C9300-48P IOS-XE 17.9.4"},
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.UNKNOWN
    assert "ENTITY_PRODUCT_REQUIRED" in {item.code for item in result.issues}
    assert result.product is None


def test_vendor_conflict_fails_closed():
    result = resolve_document_entities(
        _metadata(vendor="Huawei"),
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.CONFLICT
    assert {item.code for item in result.issues} == {"ENTITY_VENDOR_CONFLICT"}
    assert result.retrieval_eligible is False


def test_incompatible_os_is_a_scope_conflict():
    result = resolve_document_entities(
        _metadata(os_family="NX-OS"),
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.CONFLICT
    assert "ENTITY_SCOPE_CONFLICT" in {item.code for item in result.issues}


def test_unreviewed_version_remains_unknown():
    result = resolve_document_entities(
        _metadata(software_release="17.8.1"),
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    assert result.outcome is EntityResolutionOutcome.UNKNOWN
    assert "ENTITY_VERSION_UNVERIFIED" in {item.code for item in result.issues}
    assert result.retrieval_eligible is False


def test_cross_tenant_snapshot_is_rejected_when_tenant_isolation_is_enabled(monkeypatch):
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    result = resolve_document_entities(
        _metadata(),
        tenant_id=TENANT,
        catalog=_catalog(tenant_id="tenant-b"),
    )

    assert result.outcome is EntityResolutionOutcome.CONFLICT
    assert "ENTITY_TENANT_SCOPE_DENIED" in {item.code for item in result.issues}


def test_seed_catalog_is_not_treated_as_active_fact():
    result = resolve_document_entities(
        _metadata(),
        tenant_id=TENANT,
        catalog=_catalog(is_seed=True),
    )

    assert result.outcome is EntityResolutionOutcome.UNKNOWN
    assert "ENTITY_CATALOG_REVIEW_ONLY" in {item.code for item in result.issues}


def test_single_org_resolution_searches_active_historical_snapshots_by_object_identity(monkeypatch):
    from core import tenant_policy
    from services.catalog_version_service import (
        get_active_catalog_snapshots,
        import_catalog_version,
        list_catalog_versions,
        reset_catalog_version_state_for_tests,
    )

    reset_catalog_version_state_for_tests()
    try:
        monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
        owners = [
            {"id": "entity-history-a", "role": "Administrator", "tenant_id": "tenant-history-a"},
            {"id": "entity-history-b", "role": "Administrator", "tenant_id": "tenant-history-b"},
        ]
        for index, owner in enumerate(owners):
            tenant = owner["tenant_id"]
            baseline = list_catalog_versions(owner)["active_version_id"]
            import_catalog_version(
                owner,
                {
                    "version": f"entity-history-v{index + 1}",
                    "models": [{
                        "product_model_id": f"history-model-{index + 1}",
                        "tenant_id": tenant,
                        "vendor_id": "cisco",
                        "vendor_name": "Cisco",
                        "family_code": "catalyst_9300",
                        "family_name": "Catalyst 9300",
                        "series_code": "c9300",
                        "series_name": "Catalyst 9300",
                        "model_code": "HISTORY-C9300",
                        "display_name": "Shared Historical C9300",
                        "status": "active",
                        "review_status": "approved",
                        "software_scope": {
                            "os_family": "IOS-XE",
                            "software_train": "IOS-XE",
                            "software_versions": ["17.9.4"],
                        },
                        "platform_binding_advisory": {"cli_platform": "cisco_ios_xe"},
                    }, {
                        "product_model_id": f"draft-model-{index + 1}",
                        "tenant_id": tenant,
                        "vendor_id": "cisco",
                        "vendor_name": "Cisco",
                        "family_code": "catalyst_9300",
                        "family_name": "Catalyst 9300",
                        "series_code": "c9300",
                        "series_name": "Catalyst 9300",
                        "model_code": "HISTORY-C9300-DRAFT",
                        "display_name": "Shared Historical C9300 Draft",
                        "status": "draft",
                    }],
                    "aliases": [{
                        "id": f"history-alias-{index + 1}",
                        "tenant_id": tenant,
                        "product_model_id": f"history-model-{index + 1}",
                        "alias": "Shared Historical C9300",
                        "alias_kind": "canonical",
                        "status": "active",
                    }, {
                        "id": f"draft-alias-{index + 1}",
                        "tenant_id": tenant,
                        "product_model_id": f"draft-model-{index + 1}",
                        "alias": "Draft-only historical C9300",
                        "alias_kind": "canonical",
                        "status": "active",
                    }],
                },
                expected_active_version_id=baseline,
                confirm=True,
            )

        snapshots = {
            item["tenant_id"]: item
            for item in get_active_catalog_snapshots(tenant_id=None)
            if item["tenant_id"] in {"tenant-history-a", "tenant-history-b"}
        }
        monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
        result = resolve_document_entities(
            _metadata(product_model="Shared Historical C9300"),
            tenant_id=None,
        )

        assert result.outcome is EntityResolutionOutcome.AMBIGUOUS
        assert result.retrieval_eligible is False
        assert {(item["tenant_id"], item["product_model_id"]) for item in result.candidates} == {
            ("tenant-history-a", "history-model-1"),
            ("tenant-history-b", "history-model-2"),
        }
        for candidate in result.candidates:
            snapshot = snapshots[candidate["tenant_id"]]
            assert candidate["catalog_version_id"] == snapshot["version_id"]
            assert candidate["catalog_content_hash"] == snapshot["content_hash"]
        assert result.metadata_hash
    finally:
        reset_catalog_version_state_for_tests()


def test_upstream_quarantine_short_circuits_resolution():
    result = resolve_document_entities(
        tenant_id=TENANT,
        catalog=_catalog(),
        metadata_result=SimpleNamespace(
            entity_resolution_allowed=False,
            metadata=_metadata(),
        ),
    )

    assert result.outcome is EntityResolutionOutcome.QUARANTINED
    assert result.decision.value == "quarantine"


def test_secret_input_is_redacted_to_stable_issue():
    result = resolve_document_entities(
        {"product_model": "C9300-48P", "api_key": "do-not-leak"},
        tenant_id=TENANT,
        catalog=_catalog(),
    )

    serialized = str(result.to_dict())
    assert result.outcome is EntityResolutionOutcome.CONFLICT
    assert "ENTITY_METADATA_SECRET_FORBIDDEN" in serialized
    assert "do-not-leak" not in serialized


def test_catalog_dependency_failure_is_recoverable_and_redacted():
    def unavailable(_tenant):
        raise RuntimeError("secret database password=do-not-leak")

    result = resolve_document_entities(
        _metadata(),
        tenant_id=TENANT,
        catalog_loader=unavailable,
    )

    serialized = str(result.to_dict())
    assert result.outcome is EntityResolutionOutcome.DEPENDENCY_UNAVAILABLE
    assert "ENTITY_CATALOG_UNAVAILABLE" in serialized
    assert "do-not-leak" not in serialized
