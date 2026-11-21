from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ai.services import natural_query as natural_query_module


def test_natural_query_marks_cmdb_context_as_internal(monkeypatch):
    service = natural_query_module.NaturalQueryService()
    monkeypatch.setattr(
        service,
        "search_devices",
        lambda filters, tenant_id=None: [
            {
                "id": "device-1",
                "hostname": "core-1",
                "ip_address": "10.0.0.1",
                "platform": "h3c_comware",
                "vendor": "H3C",
                "model": "S6850",
                "version": "7.1",
                "role": "core",
                "site": "DC-1",
                "device_category": "switch",
                "status": "online",
            }
        ],
    )
    calls: list[dict] = []

    async def fake_chat(**kwargs):
        calls.append(kwargs)
        return {"content": "当前有 1 台设备", "request_id": "ai_req_test"}

    monkeypatch.setattr(natural_query_module.llm_gateway, "chat", fake_chat)

    result = asyncio.run(
        service.execute_query(
            "有多少台设备",
            {},
            user_id="admin",
            tenant_id="tenant-default",
        )
    )

    assert result["matched_count"] == 1
    assert calls[0]["data_classification"] == "INTERNAL"


def test_natural_query_device_search_includes_historical_tenant_labels(isolated_db):
    from database import get_db_connection

    connection = get_db_connection()
    try:
        connection.executemany(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id, vendor, status) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("natural-history-a", "history-a", "203.0.113.40", "tenant-history-a", "Huawei", "online"),
                ("natural-history-b", "history-b", "203.0.113.41", "tenant-history-b", "Huawei", "online"),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    results = natural_query_module.NaturalQueryService().search_devices(
        {}, tenant_id="tenant-history-a",
    )

    assert {item["id"] for item in results} >= {"natural-history-a", "natural-history-b"}


def test_reviewed_static_alias_does_not_hide_historical_v2_candidates(monkeypatch):
    from ai.services import product_resolver as product_resolver_module

    historical_a = {
        "tenant_id": "tenant-history-a",
        "product_model_id": "model-s6850",
        "product_model": "S6850",
        "catalog_version_id": "catalog-v1",
        "catalog_content_hash": "hash-v1",
        "cli_platform": "h3c_comware",
    }
    historical_b = {
        **historical_a,
        "tenant_id": "tenant-history-b",
        "catalog_version_id": "catalog-v2",
        "catalog_content_hash": "hash-v2",
    }
    v2_resolution = SimpleNamespace(
        catalog_ready=True,
        retrieval_filters={"vendor": "H3C", "product_model": "S6850"},
        metadata={"vendor": "H3C", "product_model": "S6850"},
        candidates=[historical_a, dict(historical_a), historical_b],
        platform_candidates=["h3c_comware"],
        ambiguous=True,
        outcome=SimpleNamespace(value="ambiguous"),
        retrieval_eligible=False,
        driver_selection_allowed=False,
    )
    resolver_tenants = []

    def resolve_v2(_metadata, *, tenant_id=None):
        resolver_tenants.append(tenant_id)
        return v2_resolution

    monkeypatch.setattr(
        product_resolver_module,
        "resolve_document_entities",
        resolve_v2,
    )

    resolver = product_resolver_module.ProductResolver()
    first = resolver.resolve_query("H3C S6850 Comware VLAN配置", metadata={"vendor": "H3C"})
    second = resolver.resolve_query("H3C S6850 Comware VLAN配置", metadata={"vendor": "H3C"})

    def identity(item):
        return (
            item.get("tenant_id"),
            item.get("catalog_version_id"),
            item.get("catalog_content_hash"),
            item.get("product_model_id") or item.get("product_model"),
        )

    first_identities = [identity(item) for item in first.candidates]
    assert resolver_tenants == [None, None]
    assert ("tenant-history-a", "catalog-v1", "hash-v1", "model-s6850") in first_identities
    assert ("tenant-history-b", "catalog-v2", "hash-v2", "model-s6850") in first_identities
    assert len(first_identities) == len(set(first_identities))
    assert len(first_identities) <= product_resolver_module.MAX_RESOLUTION_CANDIDATES
    assert first_identities == [identity(item) for item in second.candidates]
    assert any(item.get("match_method") == "exact" for item in first.candidates)
    assert first.ambiguous is True
    assert first.driver_selection_allowed is False
