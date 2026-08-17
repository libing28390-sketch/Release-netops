from __future__ import annotations

import pytest

from api.knowledge_ingestion import OfficialSeedBatchRequest, api_import_official_seed_batch, router
from services.official_seed_batch_service import (
    MAX_SEED_ITEMS,
    OfficialSeedBatchError,
    collect_official_seed_batch,
    rate_limiter,
)


USER = {"id": "seed-operator", "username": "seed-operator", "tenant_id": "tenant-seed", "role": "Administrator"}
URL_A = "https://www.cisco.com/c/en/us/products/switches/catalyst-9300-series-switches/index.html"
URL_B = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html"


def _item(url: str, **overrides):
    value = {
        "url": url,
        "source_kind": "product_page",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "catalog-reviewer",
    }
    value.update(overrides)
    return value


@pytest.fixture(autouse=True)
def reset_limiter():
    rate_limiter.reset_for_tests()
    yield
    rate_limiter.reset_for_tests()


def test_ing022_preflights_all_items_and_applies_tenant_host_spacing():
    calls: list[dict] = []
    waits: list[float] = []

    def importer(user, payload):
        calls.append(payload)
        return {
            "success": True,
            "replayed": False,
            "continuation_required": True,
            "job": {"id": f"job-{len(calls)}", "execution_state": "running", "phase": "fetched", "progress_percent": 0},
            "source": {"id": f"source-{len(calls)}"},
            "version": {"id": f"version-{len(calls)}"},
        }

    result = collect_official_seed_batch(
        USER,
        [_item(URL_A), _item(URL_B)],
        rate_limit_per_minute=30,
        request_id="seed-req-001",
        importer=importer,
        sleeper=waits.append,
    )

    assert result["item_count"] == 2
    assert result["succeeded_count"] == 2
    assert result["failed_count"] == 0
    assert len(calls) == 2
    assert calls[0]["request_id"] == "seed-req-001:item:1"
    assert calls[1]["request_id"] == "seed-req-001:item:2"
    assert waits and waits[0] == pytest.approx(2.0, abs=0.001)
    assert "raw" not in str(result).lower()


def test_ing022_invalid_seed_fails_before_any_importer_call():
    called = False

    def importer(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}

    with pytest.raises(OfficialSeedBatchError) as invalid:
        collect_official_seed_batch(
            USER,
            [_item("https://www.cisco.com/unsupported/private")],
            importer=importer,
            sleeper=lambda _seconds: None,
        )
    assert invalid.value.code == "SEED_PREFLIGHT_FAILED"
    assert called is False
    assert "unsupported/private" not in str(invalid.value)


def test_ing022_bounds_batch_size_rate_and_duplicate_canonical_urls():
    with pytest.raises(OfficialSeedBatchError) as size:
        collect_official_seed_batch(USER, [_item(URL_A)] * (MAX_SEED_ITEMS + 1))
    assert size.value.code == "SEED_BATCH_SIZE_INVALID"

    with pytest.raises(OfficialSeedBatchError) as rate:
        collect_official_seed_batch(USER, [_item(URL_A)], rate_limit_per_minute=31)
    assert rate.value.code == "SEED_RATE_LIMIT_INVALID"

    with pytest.raises(OfficialSeedBatchError) as duplicate:
        collect_official_seed_batch(USER, [_item(URL_A), _item(f"{URL_A}#fragment")])
    assert duplicate.value.code in {"SEED_DUPLICATE_URL", "SEED_PREFLIGHT_FAILED"}


def test_ing022_runtime_errors_are_bounded_per_item_and_batch_continues():
    calls = 0

    def importer(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider secret raw body must not escape")
        return {"success": True, "job": {}, "source": {}, "version": {}, "replayed": False}

    result = collect_official_seed_batch(
        USER,
        [_item(URL_A), _item(URL_B)],
        rate_limit_per_minute=30,
        importer=importer,
        sleeper=lambda _seconds: None,
    )
    assert result["failed_count"] == 1
    assert result["succeeded_count"] == 1
    assert result["items"][0]["error"]["code"] == "SEED_IMPORT_FAILED"
    assert "provider secret" not in str(result)


def test_ing022_api_contract_and_handler_return_bounded_batch(monkeypatch):
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert ("/knowledge-v2/ingestion/official-seed-batch", ("POST",)) in paths
    payload = OfficialSeedBatchRequest(items=[_item(URL_A)], rate_limit_per_minute=30, request_id="api-seed-001")
    monkeypatch.setattr(
        "api.knowledge_ingestion.collect_official_seed_batch",
        lambda user, items, **kwargs: {
            "batch_id": "batch-001",
            "tenant_id": user["tenant_id"],
            "item_count": len(items),
            "succeeded_count": 1,
            "failed_count": 0,
            "rate_limit_per_minute": kwargs["rate_limit_per_minute"],
            "elapsed_ms": 1,
            "items": [{"index": 0, "url": URL_A, "success": True, "job": {}, "error": None}],
        },
    )
    response = type("ResponseStub", (), {"status_code": 200})()
    result = api_import_official_seed_batch(response=response, payload=payload, user=USER)
    assert response.status_code == 202
    assert result["success"] is True
    assert result["data"]["tenant_id"] == "tenant-seed"
