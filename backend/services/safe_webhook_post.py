"""Fail-closed HTTP POST boundary for notification webhooks.

Webhook URLs are user/configuration supplied and therefore must not be passed
directly to a URL opener.  This module validates the URL, resolves the host
immediately before the request, rejects non-public addresses, disables
redirects, and applies bounded request/response sizes and timeouts.

The HTTP client and resolver are injectable so the boundary can be tested
without making a network request.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx
import httpcore


MAX_URL_BYTES = 4096
MAX_REQUEST_BODY_BYTES = 256 * 1024
MAX_RESPONSE_BODY_BYTES = 64 * 1024
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0

Resolver = Callable[[str, int], Iterable[Any]]
ClientFactory = Callable[..., httpx.Client]


class SafeWebhookPostError(ValueError):
    """Internal validation error with a stable, non-sensitive message."""


class _PinnedNetworkBackend(httpcore.SyncBackend):
    """Connect to validated IPs while httpcore retains the original host.

    ``httpcore`` passes the origin hostname to ``start_tls`` after the TCP
    connection is established.  Replacing only the TCP destination therefore
    keeps TLS SNI/certificate validation and the HTTP Host header bound to the
    user supplied hostname, while avoiding a second hostname DNS lookup.
    """

    def __init__(self, addresses: Iterable[str]):
        self._addresses = tuple(addresses)
        self._next_address = 0

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if not self._addresses:
            raise OSError("No pinned webhook address")
        address = self._addresses[self._next_address % len(self._addresses)]
        self._next_address += 1
        return super().connect_tcp(
            address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _PinnedResponseStream(httpx.SyncByteStream):
    def __init__(self, stream):
        self._stream = stream

    def __iter__(self):
        yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class _PinnedHTTPTransport(httpx.BaseTransport):
    """Small httpx transport adapter backed by a pinned httpcore pool."""

    def __init__(self, addresses: Iterable[str], port: int = 443):
        ssl_context = httpx.create_ssl_context(verify=True, trust_env=False)
        self._port = port
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            network_backend=_PinnedNetworkBackend(addresses),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=self._port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = self._pool.handle_request(core_request)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_PinnedResponseStream(core_response.stream),
            extensions=core_response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


def _invalid(message: str) -> tuple[bool, str]:
    return False, message


def _canonicalize_url(value: Any) -> tuple[str, str, int]:
    raw = str(value or "").strip()
    if (
        not raw
        or len(raw) > MAX_URL_BYTES
        or any(ord(char) < 32 or ord(char) == 127 for char in raw)
    ):
        raise SafeWebhookPostError("Webhook URL is invalid")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise SafeWebhookPostError("Webhook URL is invalid") from exc

    if parsed.scheme.lower() != "https":
        raise SafeWebhookPostError("Webhook URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise SafeWebhookPostError("Webhook URL contains forbidden components")
    if not host:
        raise SafeWebhookPostError("Webhook URL host is missing")
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise SafeWebhookPostError("Webhook URL host is invalid") from exc
    if not host or port not in (None, 443):
        raise SafeWebhookPostError("Webhook URL port is forbidden")

    # IP literals bypass the DNS check and make policy/audit less predictable.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SafeWebhookPostError("Webhook URL IP literals are forbidden")

    canonical = urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    return canonical, host, 443


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


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
        and not getattr(address, "is_site_local", False)
    )


def _default_resolver(host: str, port: int) -> list[Any]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _resolve_public_addresses(host: str, port: int, resolver: Resolver | None) -> tuple[str, ...]:
    try:
        answers = list((resolver or _default_resolver)(host, port))
    except (OSError, socket.gaierror) as exc:
        raise SafeWebhookPostError("Webhook hostname could not be resolved") from exc

    addresses: list[str] = []
    for answer in answers:
        address = _address_from_answer(answer)
        if not address:
            continue
        if not _is_public_address(address):
            raise SafeWebhookPostError("Webhook hostname resolved to a non-public address")
        addresses.append(address)
    unique = tuple(sorted(set(addresses)))
    if not unique:
        raise SafeWebhookPostError("Webhook hostname has no public address")
    return unique


def post_json(
    url: str,
    payload: dict,
    timeout: float = 5,
    *,
    resolver: Resolver | None = None,
    transport: httpx.BaseTransport | None = None,
    client_factory: ClientFactory | None = None,
) -> tuple[bool, str]:
    """POST one bounded JSON payload to a public HTTPS webhook.

    The default path performs a real outbound request only after all checks;
    tests should provide both ``resolver`` and ``transport``.
    """

    try:
        canonical_url, host, port = _canonicalize_url(url)
        timeout_seconds = float(timeout)
        if not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise SafeWebhookPostError("Webhook timeout is outside the safe range")
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_REQUEST_BODY_BYTES:
            raise SafeWebhookPostError("Webhook request body is too large")
        resolved_addresses = _resolve_public_addresses(host, port, resolver)
    except (SafeWebhookPostError, TypeError, ValueError, UnicodeError) as exc:
        return _invalid(str(exc) or "Webhook request is invalid")

    owned_transport = transport is None
    request_transport = transport or _PinnedHTTPTransport(resolved_addresses, port=port)
    factory = client_factory or httpx.Client
    response: httpx.Response | None = None
    try:
        with factory(
            transport=request_transport,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            trust_env=False,
            headers={"Content-Type": "application/json"},
        ) as client:
            request = client.build_request("POST", canonical_url, content=data)
            response = client.send(request, follow_redirects=False, stream=True)
            status = int(response.status_code)
            if 300 <= status < 400:
                return _invalid("Webhook redirects are forbidden")

            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BODY_BYTES:
                    return _invalid("Webhook response is too large")
                body.extend(chunk)
            if status >= 400:
                return False, f"HTTP {status}"
            return True, bytes(body).decode("utf-8", errors="replace")
    except (httpx.TimeoutException, httpcore.TimeoutException):
        return _invalid("Webhook request timed out")
    except (httpx.TransportError, httpcore.NetworkError):
        return _invalid("Webhook request transport failed")
    except (OSError, ValueError):
        return _invalid("Webhook request failed")
    except Exception:
        return _invalid("Webhook request failed")
    finally:
        if response is not None:
            response.close()
        if owned_transport:
            request_transport.close()
