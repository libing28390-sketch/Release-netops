from __future__ import annotations

import asyncio

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
