"""API-001 ASGI probe for the canonical and compatibility KB boundaries."""

from __future__ import annotations

import asyncio
import json

from httpx import ASGITransport, AsyncClient

from main import app


async def _probe() -> dict[str, object]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api001.local") as client:
        canonical = await client.get("/api/v2/kb")
        compatibility = await client.get("/api/knowledge-v2")
        request_id = "api001-probe-request"
        canonical_with_request_id = await client.get("/api/v2/kb", headers={"X-Request-ID": request_id})
    canonical_body = canonical.json()
    compatibility_body = compatibility.json()
    return {
        "canonical_status": canonical.status_code,
        "compatibility_status": compatibility.status_code,
        "canonical_contract": canonical_body.get("contract"),
        "compatibility_contract": compatibility_body.get("contract"),
        "canonical_header": canonical.headers.get("x-api-version"),
        "request_id_preserved": canonical_with_request_id.headers.get("x-request-id") == request_id,
        "same_manifest": canonical_body == compatibility_body,
        "v1_route_untouched": "/api/v1/ai" in str(canonical_body.get("v1_ai_prefix")),
    }


if __name__ == "__main__":
    result = asyncio.run(_probe())
    result["pass"] = all(
        [
            result["canonical_status"] == 200,
            result["compatibility_status"] == 200,
            result["canonical_contract"] == "nxa.kb.v2",
            result["compatibility_contract"] == "nxa.kb.v2",
            result["canonical_header"] == "nxa.kb.v2",
            result["request_id_preserved"],
            result["same_manifest"],
            result["v1_route_untouched"],
        ]
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
