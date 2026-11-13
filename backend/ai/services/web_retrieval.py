"""Provider-agnostic, read-only web retrieval for Copilot.

The assistant should not need one bespoke tool for weather, news, prices, or
other public questions.  This service exposes one generic search-and-read
capability.  Search results and page text are untrusted data: they are
bounded, sanitized, passed through the normal AI security gateway, and never
treated as instructions.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit, urlunsplit

from ai.security.classification import classify_text, request_policy_findings
from ai.security.dlp import scan
from ai.security.sanitizer import sanitize_text
from core.config import settings
from services.safe_outbound_http import (
    OutboundCollectionError,
    _canonicalize_external_url,
    safe_fetch_url,
)


logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_HARD_DLP_CATEGORIES = frozenset({
    "credential",
    "snmp_community",
    "radius_or_tacacs_key",
    "private_key",
    "jwt",
    "cookie",
})
_BARE_SECRET_RE = re.compile(
    r"(?i)(?:\b(?:bearer|basic|authorization)\s+[A-Za-z0-9._~+/=-]{16,}|"
    r"\b(?:sk|ghp|github_pat|xoxb|xoxp)[_-][A-Za-z0-9._-]{16,})"
)
_BLOCKED_QUERY_CATEGORIES = frozenset({
    *_HARD_DLP_CATEGORIES,
    "change_command",
    "full_configuration_or_topology",
    "full_cmdb",
    "full_logs",
    "full_sessions",
    "prompt_injection",
    "hidden_instruction",
    "ip_address",
    "mac_address",
    "email",
    "phone",
    "serial_number",
    "site_name",
    "business_name",
})
_PRIVATE_SCOPE_RE = re.compile(
    r"(?i)(?:\btenant[-_:]?[a-z0-9][a-z0-9_-]{1,80}\b|"
    r"\b(?:cmdb|asset inventory|device inventory|internal topology)\b|"
    r"租户(?:数据|信息|资产)?|内网(?:设备|资产|拓扑)|专属资产)"
)
_WEB_QUERY_RE = re.compile(
    r"(?i)(?:天气|气象|实时|最新|今日|今天|明天|新闻|股价|股票价格|汇率|价格|报价|行情|趋势|金价|黄金|网上|网页|官网|官方发布|互联网|外网|在线查询|实时数据|"
    r"weather|forecast|real[- ]?time|latest|today|tomorrow|news|stock price|exchange rate|price trend|market price|gold price|search online|look up)"
)
_NETWORK_QUERY_RE = re.compile(
    r"(?i)(?:网络(?:设备|资产|拓扑|配置|运维|故障)?|交换机|路由器|防火墙|网络设备|设备资产|设备配置|拓扑|"
    r"\b(?:ip|mac|vlan|bgp|ospf|snmp|cmdb|ipam)\b|端口|接口|遥测|告警|配置|命令|厂商|"
    r"cisco|huawei|h3c|juniper|router|switch|firewall|topology|network|interface|firmware|routing|protocol)"
)
_DATE_ONLY_RE = re.compile(
    r"(?i)^\s*(?:请问|告诉我)?\s*(?:今天|今日|现在)?\s*(?:几号|日期|星期几|周几|几点|时间)(?:呢|吗)?\s*[?？。.!！]*\s*$"
)
_URL_RE = re.compile(r"(?i)https://[^\s<>\"']{4,4096}")


def web_query_requested(
    message: str,
    *,
    intent: str = "general_qa",
    allow_knowledge_fallback: bool = False,
) -> bool:
    """Return whether one public question needs fresh web evidence.

    The detector is intentionally conservative.  Internal asset, alarm,
    topology, and configuration intents keep using their tenant-scoped data
    path.  A user can still force a public lookup with an explicit URL or a
    current-information phrase.
    """

    normalized_intent = str(intent or "general_qa").strip().lower()
    if normalized_intent not in {"general_qa", "knowledge"}:
        return False
    text = str(message or "").strip()
    if not text:
        return False
    if normalized_intent == "knowledge" and allow_knowledge_fallback:
        return True
    if _DATE_ONLY_RE.fullmatch(text):
        return False
    return bool(_URL_RE.search(text) or _WEB_QUERY_RE.search(text))


def is_network_related_query(message: str, *, intent: str = "general_qa") -> bool:
    """Classify whether the answer should retain Nexora network context.

    Intent parsing is useful for routing, but it is not a sufficient answer
    scope boundary: a public question can be misclassified as ``knowledge``
    and a generic network concept can be classified as ``general_qa``.  This
    lexical guard is deliberately small and only decides presentation and
    context labeling; the existing intent-specific security gates remain the
    authority for tenant data access.
    """

    normalized_intent = str(intent or "").strip().lower()
    if normalized_intent in {
        "device_search",
        "ip_location",
        "mac_location",
        "asset_analysis",
        "alarm_search",
        "config_search",
        "troubleshooting",
    }:
        return True
    return bool(_NETWORK_QUERY_RE.search(str(message or "")))


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[: max(1, int(limit))]


def _hard_dlp_detected(value: Any) -> bool:
    return bool(_BARE_SECRET_RE.search(str(value or ""))) or any(
        item.category in _HARD_DLP_CATEGORIES
        for item in scan(value, identifiers_blocked=False)
    )


def _web_query_block_code(value: str, *, tenant_id: str | None = None) -> str | None:
    """Return a stable block code before a query can reach the public web.

    The web capability is generic, so its boundary must reject sensitive
    request classes centrally instead of relying on one tool per topic.  A
    public vendor/product question remains allowed; device identifiers,
    tenant scope, credentials, full configuration, and write requests do not.
    """

    if _hard_dlp_detected(value):
        return "AI_SECURITY_DLP_FAILED"
    if _PRIVATE_SCOPE_RE.search(value):
        return "AI_SECURITY_SCOPE_DENIED"
    if any(item.category in _BLOCKED_QUERY_CATEGORIES for item in classify_text(value)):
        return "AI_SECURITY_DLP_FAILED"
    request_findings = request_policy_findings(
        [{"role": "user", "content": value}],
        tenant_id=tenant_id,
    )
    if request_findings:
        return "AI_SECURITY_SENSITIVE_DATA"
    return None


def _safe_external_text(value: Any, *, limit: int) -> str:
    """Return page text after masking or rejecting credential material."""

    sanitized = sanitize_text(_bounded_text(value, limit))
    if _hard_dlp_detected(sanitized):
        return ""
    return sanitized


def _configured_page_hosts() -> tuple[str, ...]:
    raw = str(getattr(settings, "AI_WEB_ALLOWED_HOSTS", "") or "")
    return tuple(
        item.strip().lower().rstrip(".")
        for item in raw.split(",")
        if item.strip()
    )


def _search_endpoint() -> tuple[str, str]:
    raw = str(getattr(settings, "AI_WEB_SEARCH_ENDPOINT", _DEFAULT_SEARCH_ENDPOINT) or _DEFAULT_SEARCH_ENDPOINT).strip()
    try:
        parsed = urlsplit(raw)
        host = str(parsed.hostname or "").strip().rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise OutboundCollectionError("WEB_SEARCH_ENDPOINT_INVALID", "Web search endpoint is invalid", status_code=503) from exc
    if parsed.scheme.lower() != "https" or not host or parsed.username is not None or parsed.password is not None or parsed.fragment or port not in (None, 443):
        raise OutboundCollectionError("WEB_SEARCH_ENDPOINT_INVALID", "Web search endpoint is invalid", status_code=503)
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OutboundCollectionError("WEB_SEARCH_ENDPOINT_INVALID", "Web search endpoint is invalid", status_code=503) from exc
    path = parsed.path or "/"
    return urlunsplit(("https", host, path, "", "")), host


class _SearchResultParser(HTMLParser):
    """Small dependency-free parser for DuckDuckGo-compatible result HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._current: dict[str, Any] | None = None
        self._capture: tuple[str, str] | None = None

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        raw = next((value for key, value in attrs if key == "class"), "") or ""
        return {item.strip() for item in raw.split() if item.strip()}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        attributes = dict(attrs)
        if tag == "a" and "result__a" in classes:
            self._flush()
            self._current = {
                "href": str(attributes.get("href") or ""),
                "title": [],
                "snippet": [],
            }
            self._capture = ("title", "a")
        elif self._current is not None and "result__snippet" in classes:
            self._capture = ("snippet", tag)

    def handle_data(self, data: str) -> None:
        if self._current is None or self._capture is None:
            return
        self._current[self._capture[0]].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None and tag == self._capture[1]:
            self._capture = None

    def _flush(self) -> None:
        if self._current is None:
            return
        self.items.append({
            "href": _clean_text(self._current.get("href")),
            "title": _clean_text(self._current.get("title")),
            "snippet": _clean_text(self._current.get("snippet")),
        })
        self._current = None
        self._capture = None

    def close(self) -> None:
        super().close()
        self._flush()


class _PageTextParser(HTMLParser):
    """Extract readable text while dropping active HTML content."""

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
    _BREAK_TAGS = frozenset({"br", "div", "li", "p", "h1", "h2", "h3", "h4", "tr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in self._BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        del data


def _clean_text(value: Any) -> str:
    text = unescape("".join(value) if isinstance(value, list) else str(value or ""))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def _unwrap_result_url(value: str) -> str | None:
    raw = unescape(str(value or "").strip())
    if raw.startswith("//"):
        raw = "https:" + raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    # DuckDuckGo result links normally wrap the destination in ``uddg``.
    if parsed.path.rstrip("/").endswith("/l") or parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            raw = unquote(target)
            try:
                parsed = urlsplit(raw)
            except ValueError:
                return None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        return None
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))[:4096]


def _citation_url(value: str) -> str | None:
    try:
        canonical, _host, _port, _path = _canonicalize_external_url(value)
        parsed = urlsplit(canonical)
        host = str(parsed.hostname or "").strip().rstrip(".").lower()
        if not host:
            return None
        return urlunsplit(("https", host, parsed.path or "/", "", ""))[:2048]
    except (OutboundCollectionError, ValueError):
        return None


def _parse_search_results(content: bytes, *, limit: int) -> list[dict[str, str]]:
    parser = _SearchResultParser()
    parser.feed(content[:2_000_000].decode("utf-8", errors="replace"))
    parser.close()
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.items:
        url = _unwrap_result_url(item.get("href", ""))
        title = _safe_external_text(item.get("title"), limit=256)
        snippet = _safe_external_text(item.get("snippet"), limit=800)
        if not url or not title or url in seen:
            continue
        seen.add(url)
        results.append({"url": url, "title": title, "snippet": snippet})
        if len(results) >= limit:
            break
    return results


def _extract_page_text(content: bytes, content_type: str, *, limit: int) -> str:
    if str(content_type or "").lower() == "text/html":
        parser = _PageTextParser()
        parser.feed(content[:5_000_000].decode("utf-8", errors="replace"))
        parser.close()
        return _safe_external_text(_clean_text(parser.parts), limit=limit)
    return _safe_external_text(content[:5_000_000].decode("utf-8", errors="replace"), limit=limit)


def _fetch_search_results(query: str) -> list[dict[str, str]]:
    endpoint, host = _search_endpoint()
    target = f"{endpoint}{'&' if '?' in endpoint else '?'}q={quote_plus(query)}"
    result = safe_fetch_url(
        target,
        allowed_hosts=(host,),
        timeout_seconds=float(getattr(settings, "AI_WEB_TIMEOUT_SECONDS", 8.0) or 8.0),
        max_bytes=min(int(getattr(settings, "AI_WEB_MAX_RESPONSE_BYTES", 1_000_000) or 1_000_000), 5_000_000),
        allowed_content_types=("text/html", "text/plain"),
        user_agent=str(getattr(settings, "AI_WEB_USER_AGENT", "NexoraAIWeb/1.0") or "NexoraAIWeb/1.0"),
        proxy_url=str(getattr(settings, "AI_OUTBOUND_PROXY_URL", "") or "").strip() or None,
    )
    return _parse_search_results(
        result.content,
        limit=max(1, min(int(getattr(settings, "AI_WEB_MAX_RESULTS", 5) or 5), 10)),
    )


def _fetch_page(url: str) -> tuple[str, str] | None:
    try:
        result = safe_fetch_url(
            url,
            allowed_hosts=_configured_page_hosts(),
            timeout_seconds=float(getattr(settings, "AI_WEB_TIMEOUT_SECONDS", 8.0) or 8.0),
            max_bytes=min(int(getattr(settings, "AI_WEB_MAX_RESPONSE_BYTES", 1_000_000) or 1_000_000), 5_000_000),
            allowed_content_types=("text/html", "text/plain", "application/json", "application/xml", "text/xml"),
            user_agent=str(getattr(settings, "AI_WEB_USER_AGENT", "NexoraAIWeb/1.0") or "NexoraAIWeb/1.0"),
            proxy_url=str(getattr(settings, "AI_OUTBOUND_PROXY_URL", "") or "").strip() or None,
        )
    except OutboundCollectionError:
        return None
    text = _extract_page_text(
        result.content,
        result.content_type,
        limit=max(500, min(int(getattr(settings, "AI_WEB_MAX_PAGE_CHARS", 6000) or 6000), 12_000)),
    )
    return (text, result.content_type) if text else None


def _citation(item: dict[str, str], index: int, fetched_at: str) -> dict[str, Any] | None:
    url = _citation_url(item.get("url", ""))
    if not url:
        return None
    citation_id = "web_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return {
        "citation_id": citation_id,
        "document": item.get("title") or f"公开网页来源 {index}",
        "document_id": None,
        "section": "联网检索",
        "url": url,
        "source_type": "web_search",
        "status": "live",
        "trust": "external_unverified",
        "validation": "public_web",
        "updated_at": fetched_at,
        "warnings": ["external_content_unverified", "page_instructions_untrusted"],
    }


class WebRetrievalService:
    """One generic search/read capability shared by all public questions."""

    async def retrieve(self, query: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        if not bool(getattr(settings, "AI_WEB_SEARCH_ENABLED", True)):
            return {"status": "disabled", "provider": "generic_web", "items": [], "citations": []}
        raw_query = _bounded_text(query, 512)
        if not raw_query:
            return {"status": "no_query", "provider": "generic_web", "items": [], "citations": []}
        block_code = _web_query_block_code(raw_query, tenant_id=tenant_id)
        if block_code:
            return {
                "status": "blocked",
                "provider": "generic_web",
                "error_code": block_code,
                "items": [],
                "citations": [],
            }
        safe_query = sanitize_text(raw_query)
        try:
            search_items = await asyncio.to_thread(_fetch_search_results, safe_query)
        except OutboundCollectionError as exc:
            logger.info("Web search unavailable code=%s", exc.code)
            return {
                "status": "unavailable",
                "provider": "generic_web",
                "error_code": exc.code,
                "items": [],
                "citations": [],
            }
        except Exception:
            logger.info("Web search failed code=WEB_SEARCH_FAILED")
            return {
                "status": "unavailable",
                "provider": "generic_web",
                "error_code": "WEB_SEARCH_FAILED",
                "items": [],
                "citations": [],
            }

        if not search_items:
            return {"status": "no_results", "provider": "generic_web", "items": [], "citations": []}

        page_limit = max(0, min(int(getattr(settings, "AI_WEB_MAX_PAGE_FETCHES", 3) or 3), len(search_items), 5))
        page_results: list[dict[str, str]] = []
        for item in search_items[:page_limit]:
            fetched = await asyncio.to_thread(_fetch_page, item["url"])
            if fetched:
                item = {**item, "content": fetched[0]}
            page_results.append(item)

        fetched_at = datetime.now(timezone.utc).isoformat()
        citations = [
            citation
            for index, item in enumerate(page_results, start=1)
            if (citation := _citation(item, index, fetched_at)) is not None
        ]
        context_items = [
            {
                "source": index,
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "content": item.get("content", ""),
                "untrusted_data": True,
            }
            for index, item in enumerate(page_results, start=1)
        ]
        return {
            "status": "ok",
            "provider": "generic_web",
            "items": context_items,
            "citations": citations,
        }


web_retrieval_service = WebRetrievalService()


__all__ = [
    "WebRetrievalService",
    "is_network_related_query",
    "web_query_requested",
    "web_retrieval_service",
]
