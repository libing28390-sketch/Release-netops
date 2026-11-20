from __future__ import annotations

import asyncio

import httpx

from api.knowledge_response import paginate_items, stable_error_payload
from main import app


def test_pagination_is_bounded_sorted_and_has_stable_metadata():
    rows, meta = paginate_items(
        [{"id": "b", "name": "Beta"}, {"id": "a", "name": "Alpha"}, {"id": "c", "name": "Gamma"}],
        page=2,
        page_size=2,
        sort_by="name",
        sort_order="asc",
        allowed_sort_fields={"name"},
    )
    assert [item["id"] for item in rows] == ["c"]
    assert meta.model_dump() == {"page": 2, "page_size": 2, "total": 3, "total_pages": 2, "sort_by": "name", "sort_order": "asc"}


def test_stable_error_payload_has_code_message_and_request_id():
    payload = stable_error_payload(403, "denied", request_id="req-api004")
    assert payload == {
        "success": False,
        "error": {"code": "PERMISSION_DENIED", "message": "denied", "request_id": "req-api004"},
        "detail": "denied",
    }


def test_unknown_knowledge_route_returns_normalized_error_and_request_id():
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/knowledge/not-a-resource", headers={"X-Request-ID": "req-api004-http"})

    response = asyncio.run(run())
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert body["error"]["request_id"] == "req-api004-http"
    assert response.headers["X-Request-ID"] == "req-api004-http"
