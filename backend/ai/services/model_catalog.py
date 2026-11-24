"""Read-only, allowlisted provider model catalog discovery."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from ai.security.crypto import ProviderKeyDecryptError, decrypt_api_key
from ai.security.gateway import (
    SecurityBlocked,
    ai_security_gateway,
    deployment_endpoint_allowed,
)
from ai.gateway.llm_gateway import _resolve_approved_endpoint_patterns
from database.core import get_db_connection


_MAX_PAGE_BYTES = 2 * 1024 * 1024
_MAX_CATALOG_ITEMS = 2000
_MAX_CATALOG_PAGES = 30
_GEMINI_BASE_PATH = "/v1beta/openai"
_GEMINI_MODELS_PATH = "/v1beta/models"
_GEMINI_NON_TEXT_NAME = re.compile(r"(?:^|[-_.])(?:tts|live|imagen|veo|imagegen|image-generation)(?:[-_.]|$)", re.I)
_MODEL_CODE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _provider_row(provider_id: str):
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT id, provider_type, base_url, api_key_encrypted, timeout, proxy_url,
                   enabled, approved_endpoint_patterns_json, data_region
            FROM ai_provider WHERE id = ?
            """,
            (provider_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return row


def _normalize_base_url(value: Any) -> tuple[str, Any]:
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048 or any(ord(char) < 33 for char in raw) or "\\" in raw:
        raise HTTPException(status_code=400, detail="Provider catalog endpoint is invalid")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Provider catalog endpoint is invalid") from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="Provider catalog endpoint must be a plain HTTPS base URL")
    normalized = urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return normalized, parsed


def _same_origin(left: Any, right: Any) -> bool:
    try:
        left_parsed = urlsplit(str(left))
        right_parsed = urlsplit(str(right))
        return (
            left_parsed.scheme.lower() == right_parsed.scheme.lower() == "https"
            and (left_parsed.hostname or "").lower() == (right_parsed.hostname or "").lower()
            and left_parsed.port == right_parsed.port
        )
    except ValueError:
        return False


def _provider_endpoint_patterns(raw_patterns: Any, base_url: str, provider_type: str) -> list[str]:
    patterns = _resolve_approved_endpoint_patterns(raw_patterns, base_url, provider_type)
    if not patterns or not any(fnmatchcase(base_url, pattern) for pattern in patterns):
        raise HTTPException(status_code=403, detail="Provider endpoint is not covered by its approved egress allowlist")
    if not deployment_endpoint_allowed(base_url):
        raise HTTPException(status_code=403, detail="Provider endpoint host is not in the deployment allowlist")
    return patterns


def _is_default_base_approval(base_url: str, patterns: list[str]) -> bool:
    return len(patterns) == 1 and str(patterns[0]).rstrip("/") == base_url.rstrip("/")


def _target_allowed(
    target: str,
    base_url: str,
    patterns: list[str],
    *,
    fixed_vendor_kind: str | None = None,
) -> bool:
    """Only allow a known catalog operation on the configured provider origin."""
    if not _same_origin(base_url, target) or not deployment_endpoint_allowed(target):
        return False
    if any(fnmatchcase(target, pattern) for pattern in patterns):
        return True
    base_path = urlsplit(base_url).path.rstrip("/")
    target_path = urlsplit(target).path.rstrip("/")
    if not base_path or target_path == base_path or target_path.startswith(base_path + "/"):
        return True

    # A small number of vendor APIs expose the documented model list on a
    # sibling path rather than below their OpenAI-compatible base. Treat that
    # fixed operation as part of the configured endpoint only when the saved
    # application allowlist is the ordinary exact-base default. A broader or
    # custom allowlist must explicitly cover the sibling itself.
    if not _is_default_base_approval(base_url, patterns):
        return False
    parsed = urlsplit(base_url)
    target_parsed = urlsplit(target)
    host = (parsed.hostname or "").lower()
    if fixed_vendor_kind == "gemini":
        return (
            host == "generativelanguage.googleapis.com"
            and base_path == _GEMINI_BASE_PATH
            and target_parsed.path.rstrip("/") == _GEMINI_MODELS_PATH
        )
    if fixed_vendor_kind == "cohere":
        return host == "api.cohere.ai" and base_path == "/compatibility/v1" and target_path == "/v1/models"
    if fixed_vendor_kind == "dashscope":
        return (
            base_path == "/compatible-mode/v1"
            and target_parsed.path.rstrip("/") == "/api/v1/models"
            and (
                host == "dashscope-us.aliyuncs.com"
                or host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"}
                or host.endswith(".maas.aliyuncs.com")
            )
        )
    return False


def _gemini_base(provider_type: str, base_url: str) -> bool:
    parsed = urlsplit(base_url)
    return (
        provider_type in {"openai", "openai_compatible"}
        and (parsed.hostname or "").lower() == "generativelanguage.googleapis.com"
        and parsed.path.rstrip("/") == _GEMINI_BASE_PATH
    )


def _generic_models_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if path.endswith(("/v1", "/v2", "/v1beta/openai", "/api/v3", "/api/paas/v4")):
        models_path = f"{path}/models"
    else:
        models_path = f"{path}/v1/models"
    return urlunsplit(("https", parsed.netloc, models_path, "", ""))


def _safe_model_code(value: Any, *, gemini: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip()
    if gemini and code.startswith("models/"):
        code = code[len("models/"):]
    if not code or len(code) > 256 or _MODEL_CODE_CONTROL.search(code):
        return None
    return code


def _model_name(value: Any, fallback: str) -> str:
    name = str(value or fallback).strip()
    if not name or len(name) > 256 or any(ord(char) < 32 for char in name):
        return fallback
    return name


def _json_request(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        with client.stream("GET", url, headers=headers, params=params) as response:
            if response.status_code >= 300:
                message = "Provider model catalog request failed"
                if response.status_code in {301, 302, 303, 307, 308}:
                    message = "Provider model catalog endpoint redirected; redirects are blocked"
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "AI_MODEL_CATALOG_UPSTREAM_ERROR",
                        "message": message,
                        "details": {"upstream_status": response.status_code},
                    },
                )
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > _MAX_PAGE_BYTES:
                    raise HTTPException(status_code=502, detail="Provider model catalog response is too large")
                body.extend(chunk)
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Unable to reach the provider model catalog") from None

    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog response") from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog response")
    return data


def _gemini_items(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows = payload.get("models")
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog response")
    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        methods = row.get("supportedGenerationMethods")
        methods = {str(method).strip() for method in methods} if isinstance(methods, list) else set()
        code = _safe_model_code(row.get("name"), gemini=True)
        if not code:
            continue
        if "embedContent" in methods:
            model_type = "embedding"
        elif "generateContent" in methods and not _GEMINI_NON_TEXT_NAME.search(code):
            model_type = "chat"
        else:
            continue
        items.append({
            "model_code": code,
            "name": _model_name(row.get("displayName"), code),
            "model_type": model_type,
            "source": "account",
        })
    return items


def _openai_items(payload: dict[str, Any], *, kind: str = "openai") -> list[dict[str, str]]:
    rows = payload.get("models") if kind in {"cohere", "xai"} else payload.get("data", payload.get("items"))
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog response")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _safe_model_code(row.get("name") if kind == "cohere" else row.get("id"))
        if not code:
            continue
        model_type = "unknown"
        if kind in {"anthropic", "xai"}:
            model_type = "chat"
        elif kind == "cohere":
            endpoints = row.get("endpoints")
            if row.get("is_deprecated") or not isinstance(endpoints, list):
                continue
            if "chat" in endpoints:
                model_type = "chat"
            elif "embed" in endpoints:
                model_type = "embedding"
            else:
                continue
        elif kind == "mistral":
            if row.get("archived"):
                continue
            capabilities = row.get("capabilities")
            if isinstance(capabilities, dict) and capabilities.get("completion_chat") is True:
                model_type = "chat"
        items.append({
            "model_code": code,
            "name": _model_name(row.get("name") or row.get("display_name"), code),
            "model_type": model_type,
            "source": "account",
        })
    return items


def _fetch_pages(
    client: httpx.Client,
    endpoint: str,
    *,
    headers: dict[str, str],
    parser,
    page_token_key: str | None = None,
    initial_params: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    all_items: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    token: str | None = None
    for _ in range(_MAX_CATALOG_PAGES):
        params = dict(initial_params or {})
        if token and page_token_key:
            params[page_token_key] = token
        payload = _json_request(client, endpoint, headers=headers, params=params or None)
        all_items.extend(parser(payload))
        if len(all_items) > _MAX_CATALOG_ITEMS:
            raise HTTPException(status_code=502, detail="Provider model catalog exceeds the supported result limit")
        if page_token_key == "after_id":
            if payload.get("has_more") and not payload.get("last_id"):
                raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog page token")
            next_token = payload.get("last_id") if payload.get("has_more") else None
        else:
            next_token = payload.get("nextPageToken") or payload.get("next_page_token")
        if not next_token or not page_token_key:
            return all_items
        token = str(next_token)
        if not token or token in seen_tokens:
            raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog page token")
        seen_tokens.add(token)
    raise HTTPException(status_code=502, detail="Provider model catalog has too many pages")


def _fetch_domestic_catalog(client, spec, base_url: str, patterns: list[str], headers: dict[str, str]):
    if spec.path is None:
        return [
            {**item, "source": "public"}
            for item in spec.items
            if isinstance(item, dict) and _safe_model_code(item.get("model_code"))
        ]

    from ai.services.domestic_model_catalog import parse_domestic_catalog_page

    target = urlunsplit(("https", urlsplit(base_url).netloc, spec.path, "", ""))
    if not _target_allowed(target, base_url, patterns, fixed_vendor_kind=spec.kind):
        raise HTTPException(status_code=403, detail="Provider catalog endpoint is not covered by its approved egress allowlist")

    result: list[dict[str, str]] = []
    page_number = 1
    while page_number <= _MAX_CATALOG_PAGES:
        params: dict[str, Any] = {}
        if spec.kind == "dashscope":
            params = {"page_no": page_number, "page_size": 100}
        subtype_values = ("chat", "embedding", "reranker") if spec.kind == "siliconflow" else (None,)
        for subtype in subtype_values:
            call_params = dict(params)
            if subtype:
                call_params["sub_type"] = subtype
            payload = _json_request(client, target, headers=headers, params=call_params or None)
            try:
                page_items = parse_domestic_catalog_page(spec.kind, payload)
            except ValueError:
                raise HTTPException(status_code=502, detail="Provider returned an invalid model catalog response") from None
            if subtype:
                # The official endpoint selects each subtype. Its payload may
                # omit a stable type field, so use the documented filter.
                for item in page_items:
                    item["model_type"] = "rerank" if subtype == "reranker" else subtype
            result.extend({**item, "source": "account"} for item in page_items)
            if len(result) > _MAX_CATALOG_ITEMS:
                raise HTTPException(status_code=502, detail="Provider model catalog exceeds the supported result limit")
        if spec.kind != "dashscope":
            return result
        output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
        try:
            total = int(output.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if total and page_number * int(params["page_size"]) >= total:
            return result
        rows = output.get("models") if isinstance(output.get("models"), list) else []
        if not rows or len(rows) < int(params["page_size"]):
            return result
        page_number += 1
    raise HTTPException(status_code=502, detail="Provider model catalog has too many pages")


def _dedupe_and_sort(items: list[dict[str, str]]) -> list[dict[str, str]]:
    by_code: dict[str, dict[str, str]] = {}
    for item in items:
        code = _safe_model_code(item.get("model_code"))
        if not code:
            continue
        model_type = str(item.get("model_type") or "unknown").lower()
        if model_type not in {"chat", "embedding", "rerank", "unknown"}:
            model_type = "unknown"
        source = "public" if item.get("source") == "public" else "account"
        by_code.setdefault(code, {
            "model_code": code,
            "name": _model_name(item.get("name"), code),
            "model_type": model_type,
            "source": source,
        })
    return sorted(by_code.values(), key=lambda item: (item["name"].casefold(), item["model_code"].casefold()))


def discover_provider_model_catalog(provider_id: str, *, user: dict[str, Any]) -> list[dict[str, Any]]:
    row = _provider_row(provider_id)
    provider_type = str(row[1] or "").strip().lower().replace("-", "_")
    base_url, _ = _normalize_base_url(row[2])
    if not bool(row[6]):
        raise HTTPException(status_code=409, detail="Cannot discover models from a disabled provider")

    try:
        ai_security_gateway.assert_egress_allowed(
            provider_type=provider_type,
            provider_id=provider_id,
            data_region=row[8] or "unknown",
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
        )
    except SecurityBlocked as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.reason_code, "message": "Model catalog discovery is blocked by AI egress policy"},
        ) from None

    patterns = _provider_endpoint_patterns(row[7], base_url, provider_type)
    # This helper owns the narrowly enumerated documented domestic endpoints
    # and public compatibility catalogs; it is consulted only after the saved
    # provider destination and current egress policy pass validation.
    from ai.services.domestic_model_catalog import get_domestic_catalog

    domestic = get_domestic_catalog(base_url)
    base = urlsplit(base_url)
    host = (base.hostname or "").lower()
    catalog_kind: str
    endpoint: str
    endpoint_type: str
    if domestic is not None:
        catalog_kind = "domestic"
        endpoint_type = "bearer"
        endpoint = ""
    elif _gemini_base(provider_type, base_url):
        catalog_kind = "gemini"
        native = urlunsplit(("https", urlsplit(base_url).netloc, _GEMINI_MODELS_PATH, "", ""))
        if _target_allowed(native, base_url, patterns, fixed_vendor_kind="gemini"):
            endpoint = native
            endpoint_type = "gemini"
        else:
            endpoint = _generic_models_url(base_url)
            endpoint_type = "bearer"
            catalog_kind = "openai"
    elif provider_type == "anthropic" and host == "api.anthropic.com" and base.path == "/v1":
        catalog_kind = endpoint_type = "anthropic"
        endpoint = urlunsplit(("https", base.netloc, "/v1/models", "", ""))
    elif provider_type == "openai_compatible" and host == "api.x.ai" and base.path == "/v1":
        catalog_kind, endpoint_type = "xai", "bearer"
        endpoint = urlunsplit(("https", base.netloc, "/v1/language-models", "", ""))
    elif provider_type == "openai_compatible" and host == "api.cohere.ai" and base.path == "/compatibility/v1":
        catalog_kind, endpoint_type = "cohere", "bearer"
        endpoint = urlunsplit(("https", base.netloc, "/v1/models", "", ""))
    elif provider_type in {"openai", "openai_compatible", "deepseek", "qwen"}:
        if (
            (host.startswith("bedrock-runtime.") and ".amazonaws.com" in host)
            or "aiplatform.googleapis.com" in host
        ):
            raise HTTPException(status_code=501, detail="This provider does not expose a supported model catalog API")
        catalog_kind = "mistral" if host == "api.mistral.ai" else "openai"
        endpoint_type = "bearer"
        endpoint = _generic_models_url(base_url)
    else:
        raise HTTPException(status_code=501, detail="This provider does not expose a supported model catalog API")

    fixed_vendor_kind = catalog_kind if catalog_kind in {"cohere", "gemini"} else None
    if endpoint and not _target_allowed(
        endpoint,
        base_url,
        patterns,
        fixed_vendor_kind=fixed_vendor_kind,
    ):
        raise HTTPException(status_code=403, detail="Provider catalog endpoint is not covered by its approved egress allowlist")
    if not deployment_endpoint_allowed(base_url) or (endpoint and not deployment_endpoint_allowed(endpoint)):
        raise HTTPException(status_code=403, detail="Provider endpoint host is not in the deployment allowlist")

    if domestic is not None and domestic.path is None:
        result = _fetch_domestic_catalog(None, domestic, base_url, patterns, {})
    else:
        if not row[3]:
            raise HTTPException(status_code=409, detail="Provider API key is not configured")
        try:
            api_key = decrypt_api_key(row[3], provider_id=str(row[0]))
        except ProviderKeyDecryptError:
            raise HTTPException(status_code=503, detail="Provider API key is unavailable") from None
        if not api_key:
            raise HTTPException(status_code=409, detail="Provider API key is not configured")
        if endpoint_type == "gemini":
            headers = {"x-goog-api-key": str(api_key), "Accept": "application/json"}
        elif endpoint_type == "anthropic":
            from ai.providers.anthropic import _ANTHROPIC_VERSION

            headers = {"x-api-key": str(api_key), "anthropic-version": _ANTHROPIC_VERSION, "Accept": "application/json"}
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}

        try:
            timeout_seconds = max(1.0, min(float(row[4] or 30), 30.0))
        except (TypeError, ValueError):
            timeout_seconds = 30.0
        timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0))
        proxy_url = str(row[5] or "").strip() or None
        try:
            with httpx.Client(timeout=timeout, proxy=proxy_url, follow_redirects=False) as client:
                if domestic is not None:
                    result = _fetch_domestic_catalog(client, domestic, base_url, patterns, headers)
                elif catalog_kind == "gemini":
                    result = _fetch_pages(
                        client,
                        endpoint,
                        headers=headers,
                        parser=_gemini_items,
                        page_token_key="pageToken",
                        initial_params={"pageSize": 100},
                    )
                else:
                    page_token_key = {"anthropic": "after_id", "cohere": "page_token"}.get(catalog_kind)
                    result = _fetch_pages(
                        client, endpoint, headers=headers,
                        parser=lambda payload: _openai_items(payload, kind=catalog_kind),
                        page_token_key=page_token_key,
                    )
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError):
            raise HTTPException(status_code=502, detail="Unable to reach the provider model catalog") from None

    items = _dedupe_and_sort(result)
    if len(items) > _MAX_CATALOG_ITEMS:
        raise HTTPException(status_code=502, detail="Provider model catalog exceeds the supported result limit")
    with get_db_connection() as conn:
        registered_rows = conn.execute(
            "SELECT model_code FROM ai_model WHERE provider_id = ?",
            (provider_id,),
        ).fetchall()
    registered = {str(item[0]) for item in registered_rows}
    return [
        {**item, "already_registered": item["model_code"] in registered}
        for item in items
    ]


__all__ = ["discover_provider_model_catalog"]
