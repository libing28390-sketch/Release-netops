"""Fail-closed outbound HTTP boundary for CAT-004.

This module is intentionally independent from the document parser.  It only
gets bytes from an already-active Source Registry row after checking URL,
DNS/SSRF, TLS, method, response size/content type and every redirect hop.
Network calls are injectable through ``httpx.MockTransport`` and a resolver
callback so the safety contract is testable without a live vendor site.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit

import httpx

from services.source_registry_service import (
    SourceRegistryError,
    _canonicalize_url,
)


ALLOWED_METHODS = {"GET", "HEAD"}
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/pdf",
    "application/json",
    "application/xml",
}
_SOURCE_NOT_FOUND_HTTP_STATUSES = {404, 410}
_FORBIDDEN_LITERAL_IPS = {
    "0.0.0.0",
    "127.0.0.1",
    "169.254.169.254",  # cloud metadata services
    "100.100.100.200",  # Alibaba metadata service
    "169.254.170.2",  # ECS task metadata
    "::",
    "::1",
    "fd00:ec2::254",
}


class OutboundCollectionError(ValueError):
    """Stable error that never exposes credentials or full response bodies."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class SafeFetchResult:
    content: bytes
    final_url: str
    status_code: int
    content_type: str
    redirect_chain: tuple[str, ...]
    resolved_addresses: tuple[str, ...]
    bytes_read: int
    elapsed_ms: int
    source_etag: str = ""
    source_last_modified: str = ""
    not_modified: bool = False

    def as_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        result = {
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "redirect_chain": list(self.redirect_chain),
            "resolved_addresses": list(self.resolved_addresses),
            "bytes_read": self.bytes_read,
            "elapsed_ms": self.elapsed_ms,
            "source_etag": self.source_etag,
            "source_last_modified": self.source_last_modified,
            "not_modified": self.not_modified,
        }
        if include_content:
            result["content"] = self.content
        return result


@dataclass(frozen=True)
class UrlSecurityDecision:
    """Auditable, redacted decision for one outbound URL target.

    The decision contains only canonical URL, host/path and IP safety facts;
    it deliberately never carries headers, credentials, response bodies or
    resolver error text.  ``safe_fetch`` obtains a fresh decision immediately
    before every connection attempt so the DNS result cannot be reused across
    retries or redirect hops.
    """

    canonical_url: str
    host: str
    port: int
    path: str
    resolved_addresses: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_url": self.canonical_url,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "resolved_addresses": list(self.resolved_addresses),
        }


Resolver = Callable[[str, int], Iterable[Any]]


def _is_forbidden_address(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if lowered in {item.lower() for item in _FORBIDDEN_LITERAL_IPS}:
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return True
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_global
        or getattr(address, "is_site_local", False)
    )


def resolve_public_addresses(host: str, port: int, *, resolver: Resolver | None = None) -> tuple[str, ...]:
    """Resolve immediately before a connection and reject unsafe answers."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise OutboundCollectionError("OUTBOUND_IP_LITERAL_FORBIDDEN", "IP-literal outbound targets are forbidden")
    resolver = resolver or _default_resolver
    try:
        answers = list(resolver(host, port))
    except (socket.gaierror, OSError) as exc:
        raise OutboundCollectionError("OUTBOUND_DNS_RESOLUTION_FAILED", "Source hostname could not be resolved", status_code=502) from exc
    addresses: list[str] = []
    for answer in answers:
        address = _address_from_answer(answer)
        if not address:
            continue
        if _is_forbidden_address(address):
            raise OutboundCollectionError(
                "OUTBOUND_DNS_BLOCKED",
                "Source hostname resolved to a private, loopback, link-local, multicast or metadata address",
                status_code=403,
                details={"address_class": "non_public"},
            )
        addresses.append(address)
    unique = tuple(sorted(set(addresses)))
    if not unique:
        raise OutboundCollectionError("OUTBOUND_DNS_EMPTY", "Source hostname returned no public address", status_code=502)
    return unique


def _default_resolver(host: str, port: int) -> list[Any]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _address_from_answer(answer: Any) -> str:
    if isinstance(answer, str):
        return answer
    if isinstance(answer, tuple):
        # socket.getaddrinfo returns (family, type, proto, canonname, sockaddr)
        if len(answer) >= 5 and isinstance(answer[4], tuple):
            return str(answer[4][0])
        if answer and isinstance(answer[-1], str):
            return str(answer[-1])
    return ""


def _source_policy(source: dict[str, Any]) -> dict[str, Any]:
    policy = source.get("collection_policy")
    if not isinstance(policy, dict):
        raise OutboundCollectionError("OUTBOUND_POLICY_MISSING", "Source collection policy is unavailable", status_code=409)
    return policy


def _host_allowed(source: dict[str, Any], host: str) -> bool:
    expected = str(source.get("allowed_host") or "").strip().lower().rstrip(".")
    candidate = str(host or "").strip().lower().rstrip(".")
    if not expected or not candidate:
        return False
    mode = str(source.get("host_match_mode") or "exact").lower()
    return candidate == expected if mode == "exact" else candidate == expected or candidate.endswith("." + expected)


def _path_allowed(source: dict[str, Any], url: str) -> bool:
    source_path = (urlsplit(str(source.get("canonical_url") or "")).path or "/").rstrip("/") or "/"
    candidate_path = (urlsplit(url).path or "/").rstrip("/") or "/"
    # CAT-001 registers a path prefix.  A redirect may remain within the
    # registered source subtree, but cannot jump to a sibling prefix.
    return candidate_path == source_path or candidate_path.startswith(source_path.rstrip("/") + "/")


def validate_url_security(
    target: str,
    *,
    source: dict[str, Any] | None = None,
    current_url: str | None = None,
    resolver: Resolver | None = None,
    resolve_dns: bool = False,
) -> UrlSecurityDecision:
    """Validate one URL against the immutable outbound security boundary.

    URL parsing/canonicalization is always performed.  When ``source`` is
    provided, host, HTTPS/443 and registered path constraints are also
    enforced, including for relative ``Location`` values.  DNS/SSRF checks
    are opt-in for preflight callers and are mandatory at the connection
    boundary (``safe_fetch`` passes ``resolve_dns=True``).
    """

    base = current_url or (str(source.get("canonical_url") or "") if source else "")
    try:
        canonical, host, port, path = _canonicalize_url(urljoin(base, str(target or "")))
    except SourceRegistryError as exc:
        code = "OUTBOUND_REDIRECT_TARGET_FORBIDDEN" if source else "OUTBOUND_URL_FORBIDDEN"
        raise OutboundCollectionError(code, "Outbound URL failed canonical security checks", status_code=403, details={"reason": exc.code}) from exc

    if source is not None:
        if not _host_allowed(source, host):
            raise OutboundCollectionError("OUTBOUND_REDIRECT_HOST_FORBIDDEN", "Outbound target is outside the registered host allowlist", status_code=403)
        if port != 443 or not canonical.startswith("https://"):
            raise OutboundCollectionError("OUTBOUND_REDIRECT_PROTOCOL_FORBIDDEN", "Outbound target must remain HTTPS on port 443", status_code=403)
        if not _path_allowed(source, canonical):
            raise OutboundCollectionError("OUTBOUND_REDIRECT_PATH_FORBIDDEN", "Outbound target is outside the registered path boundary", status_code=403)

    addresses = resolve_public_addresses(host, 443, resolver=resolver) if resolve_dns else ()
    return UrlSecurityDecision(canonical, host, port, path, tuple(addresses))


def validate_redirect_target(source: dict[str, Any], target: str, *, current_url: str | None = None) -> str:
    """Canonicalize and enforce host/scheme/port/path on every redirect hop."""
    return validate_url_security(target, source=source, current_url=current_url).canonical_url


def _content_type(headers: httpx.Headers) -> str:
    raw = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return raw


def safe_fetch(
    source: dict[str, Any],
    *,
    method: str = "GET",
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
    client_factory: Callable[..., httpx.Client] | None = None,
    conditional_headers: Mapping[str, Any] | None = None,
) -> SafeFetchResult:
    """Fetch one source with bounded bytes, no implicit proxy, and hop gates."""
    if str(source.get("status") or "") != "active" or not bool(source.get("fetch_enabled")):
        raise OutboundCollectionError("OUTBOUND_SOURCE_NOT_ACTIVE", "Only active, fetch-enabled sources may be collected", status_code=409)
    if str(source.get("validation_status") or "") != "valid":
        raise OutboundCollectionError("OUTBOUND_SOURCE_NOT_VALIDATED", "Source must pass validation before collection", status_code=409)
    policy = _source_policy(source)
    method = str(method or "GET").strip().upper()
    allowed_methods = {str(item).upper() for item in policy.get("http_methods") or []}
    if method not in ALLOWED_METHODS or method not in allowed_methods:
        raise OutboundCollectionError("OUTBOUND_METHOD_FORBIDDEN", "Only an allowlisted GET or HEAD method may be used", status_code=403)
    try:
        timeout = float(policy.get("timeout_seconds"))
        max_bytes = int(policy.get("max_bytes"))
        redirect_limit = int(policy.get("redirect_limit"))
        rate_limit = int(policy.get("rate_limit_per_minute"))
    except (TypeError, ValueError) as exc:
        raise OutboundCollectionError("OUTBOUND_POLICY_INVALID", "Source collection limits are invalid", status_code=409) from exc
    if not 1 <= timeout <= 120 or not 1_024 <= max_bytes <= 100_000_000 or not 0 <= redirect_limit <= 10 or rate_limit <= 0:
        raise OutboundCollectionError("OUTBOUND_POLICY_INVALID", "Source collection limits are outside the safe bounds", status_code=409)
    current_url = validate_url_security(source.get("canonical_url") or "", source=source).canonical_url
    redirect_chain: list[str] = [current_url]
    resolved: list[str] = []
    started = time.monotonic()
    retry_policy = policy.get("retry_policy") if isinstance(policy.get("retry_policy"), dict) else {}
    try:
        max_attempts = max(1, min(3, int(retry_policy.get("max_attempts", 1))))
    except (TypeError, ValueError) as exc:
        raise OutboundCollectionError("OUTBOUND_POLICY_INVALID", "Source retry limits are invalid", status_code=409) from exc
    retry_5xx = bool(retry_policy.get("retry_5xx", True))
    allowed_content_types = {
        str(item).split(";", 1)[0].strip().lower()
        for item in (policy.get("content_types") or ALLOWED_CONTENT_TYPES)
    } & ALLOWED_CONTENT_TYPES
    if not allowed_content_types:
        raise OutboundCollectionError("OUTBOUND_POLICY_INVALID", "Source content type allowlist is empty", status_code=409)
    request_headers = {"User-Agent": str(policy.get("user_agent") or "NexoraKnowledgeEngine/2.0")}
    # Conditional validators are server-derived facts from the last source
    # version.  Only the two RFC validators are accepted; arbitrary caller
    # headers would turn this boundary into an SSRF/credential escape hatch.
    for raw_name, raw_value in (conditional_headers or {}).items():
        name = str(raw_name or "").strip().lower()
        value = str(raw_value or "").strip()
        if not value:
            continue
        if name not in {"if-none-match", "if-modified-since"}:
            raise OutboundCollectionError(
                "OUTBOUND_CONDITIONAL_HEADER_FORBIDDEN",
                "Only ETag and Last-Modified conditional validators are allowed",
                status_code=403,
            )
        if len(value) > (512 if name == "if-none-match" else 256) or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise OutboundCollectionError(
                "OUTBOUND_CONDITIONAL_HEADER_INVALID",
                "Conditional validator is invalid",
                status_code=400,
            )
        request_headers["If-None-Match" if name == "if-none-match" else "If-Modified-Since"] = value
    factory = client_factory or httpx.Client
    try:
        with factory(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            verify=True,
            trust_env=False,
            headers=request_headers,
        ) as client:
            hop = 0
            while True:
                response: httpx.Response | None = None
                for attempt in range(max_attempts if retry_5xx else 1):
                    if time.monotonic() - started >= timeout:
                        raise OutboundCollectionError("OUTBOUND_TIMEOUT", "Source request timed out", status_code=504)
                    # Re-resolve immediately before every connection attempt so
                    # DNS rebinding cannot move a previously approved hostname
                    # to a private or metadata address between retries.
                    parts = urlsplit(current_url)
                    decision = validate_url_security(current_url, source=source, resolver=resolver, resolve_dns=True)
                    resolved.extend(decision.resolved_addresses)
                    try:
                        request = client.build_request(method, current_url)
                        response = client.send(request, follow_redirects=False, stream=True)
                    except httpx.TimeoutException as exc:
                        raise OutboundCollectionError("OUTBOUND_TIMEOUT", "Source request timed out", status_code=504) from exc
                    except httpx.TransportError as exc:
                        raise OutboundCollectionError("OUTBOUND_TRANSPORT_FAILED", "Source request transport failed", status_code=502) from exc
                    if response.status_code < 500 or attempt + 1 >= max_attempts:
                        break
                    response.close()
                if response is None:
                    raise OutboundCollectionError("OUTBOUND_EMPTY_RESPONSE", "Source request returned no response", status_code=502)
                try:
                    status = int(response.status_code)
                    if status == 304:
                        # A 304 has no representation bytes.  Preserve the
                        # validators returned by the origin and let the
                        # freshness layer append an observation against the
                        # previous immutable source version.
                        return SafeFetchResult(
                            content=b"",
                            final_url=current_url,
                            status_code=status,
                            content_type=_content_type(response.headers),
                            redirect_chain=tuple(redirect_chain),
                            resolved_addresses=tuple(sorted(set(resolved))),
                            bytes_read=0,
                            elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                            source_etag=str(response.headers.get("etag") or "")[:512],
                            source_last_modified=str(response.headers.get("last-modified") or "")[:256],
                            not_modified=True,
                        )
                    if 300 <= status < 400:
                        location = response.headers.get("location")
                        response.close()
                        if not location:
                            raise OutboundCollectionError("OUTBOUND_REDIRECT_MISSING_LOCATION", "Redirect response did not include a Location header", status_code=502)
                        if hop >= redirect_limit:
                            raise OutboundCollectionError("OUTBOUND_REDIRECT_LIMIT", "Source redirect limit was exceeded", status_code=403)
                        current_url = validate_redirect_target(source, location, current_url=current_url)
                        redirect_chain.append(current_url)
                        hop += 1
                        continue
                    if status in _SOURCE_NOT_FOUND_HTTP_STATUSES:
                        # These statuses are an explicit, bounded signal that
                        # the registered source is absent.  Keep the response
                        # evidence numeric-only: provider bodies, headers and
                        # exception text may contain credentials or other
                        # sensitive material.
                        raise OutboundCollectionError(
                            "OUTBOUND_HTTP_SOURCE_NOT_FOUND",
                            "Source was not found at its registered location",
                            status_code=502,
                            details={"http_status": status},
                        )
                    if 400 <= status < 500:
                        raise OutboundCollectionError("OUTBOUND_HTTP_4XX", "Source returned a client error", status_code=502, details={"http_status": status})
                    if status >= 500:
                        raise OutboundCollectionError("OUTBOUND_HTTP_5XX", "Source returned a server error after bounded retries", status_code=502, details={"http_status": status})
                    content_type = _content_type(response.headers)
                    if content_type not in allowed_content_types:
                        raise OutboundCollectionError("OUTBOUND_CONTENT_TYPE_FORBIDDEN", "Source response content type is not allowlisted", status_code=403, details={"content_type": content_type or "missing"})
                    length_header = response.headers.get("content-length")
                    if length_header:
                        try:
                            declared_length = int(length_header)
                        except ValueError as exc:
                            raise OutboundCollectionError("OUTBOUND_CONTENT_LENGTH_INVALID", "Source content length is invalid", status_code=502) from exc
                        if declared_length < 0:
                            raise OutboundCollectionError("OUTBOUND_CONTENT_LENGTH_INVALID", "Source content length is invalid", status_code=502)
                        if declared_length > max_bytes:
                            raise OutboundCollectionError("OUTBOUND_RESPONSE_TOO_LARGE", "Source response exceeds max_bytes", status_code=413)
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started >= timeout:
                            raise OutboundCollectionError("OUTBOUND_TIMEOUT", "Source response timed out", status_code=504)
                        if len(content) + len(chunk) > max_bytes:
                            raise OutboundCollectionError("OUTBOUND_RESPONSE_TOO_LARGE", "Source response exceeds max_bytes", status_code=413)
                        content.extend(chunk)
                    if method == "HEAD":
                        content = bytearray()
                    return SafeFetchResult(
                        content=bytes(content),
                        final_url=current_url,
                        status_code=status,
                        content_type=content_type,
                        redirect_chain=tuple(redirect_chain),
                        resolved_addresses=tuple(sorted(set(resolved))),
                        bytes_read=len(content),
                        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                        source_etag=str(response.headers.get("etag") or "")[:512],
                        source_last_modified=str(response.headers.get("last-modified") or "")[:256],
                    )
                finally:
                    response.close()
    except OutboundCollectionError:
        raise
    except httpx.TimeoutException as exc:
        raise OutboundCollectionError("OUTBOUND_TIMEOUT", "Source request timed out", status_code=504) from exc
    except httpx.TransportError as exc:
        raise OutboundCollectionError("OUTBOUND_TRANSPORT_FAILED", "Source request transport failed", status_code=502) from exc
