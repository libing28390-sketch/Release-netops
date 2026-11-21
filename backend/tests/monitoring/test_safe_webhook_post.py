from __future__ import annotations

import socket

import httpx
import httpcore
import pytest

from services import notification_service, safe_webhook_post


PUBLIC_IP = "8.8.8.8"


def _resolver(_host: str, _port: int):
    return [PUBLIC_IP]


def test_post_json_uses_mocked_socket_dns_before_mocked_transport(monkeypatch):
    dns_calls = []
    transport_calls = []

    def fake_getaddrinfo(host, port, **kwargs):
        dns_calls.append((host, port, kwargs))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (PUBLIC_IP, port))]

    def handler(request: httpx.Request) -> httpx.Response:
        transport_calls.append(request)
        return httpx.Response(204, request=request)

    monkeypatch.setattr(safe_webhook_post.socket, "getaddrinfo", fake_getaddrinfo)

    ok, body = safe_webhook_post.post_json(
        "https://oapi.dingtalk.com/robot/send?access_token=test",
        {"msgtype": "text"},
        transport=httpx.MockTransport(handler),
    )

    assert (ok, body) == (True, "")
    assert dns_calls == [("oapi.dingtalk.com", 443, {"type": socket.SOCK_STREAM})]
    assert len(transport_calls) == 1


def test_pinned_network_backend_connects_to_checked_ip(monkeypatch):
    connected = []

    class FakeSocket:
        def settimeout(self, _timeout):
            pass

        def setsockopt(self, *_args):
            pass

        def close(self):
            pass

    def fake_create_connection(address, timeout, source_address=None):
        connected.append((address, timeout, source_address))
        return FakeSocket()

    monkeypatch.setattr(safe_webhook_post.socket, "create_connection", fake_create_connection)

    backend = safe_webhook_post._PinnedNetworkBackend((PUBLIC_IP, "1.1.1.1"))
    stream = backend.connect_tcp("open.feishu.cn", 443, timeout=2.0)
    stream.close()

    assert connected == [((PUBLIC_IP, 443), 2.0, None)]


def test_pinned_transport_keeps_origin_host_for_tls_and_http_host_header():
    captured = {}

    class FakePool:
        def handle_request(self, request):
            captured["request"] = request
            return httpcore.Response(204, headers=[], content=b"")

        def close(self):
            pass

    transport = safe_webhook_post._PinnedHTTPTransport((PUBLIC_IP,))
    transport._pool = FakePool()
    response = transport.handle_request(httpx.Request("POST", "https://open.feishu.cn/hook", content=b"{}"))
    response.read()
    transport.close()

    assert captured["request"].url.host == b"open.feishu.cn"
    assert captured["request"].url.port == 443
    assert (b"Host", b"open.feishu.cn") in captured["request"].headers


def test_owned_pinned_transport_closes_when_client_setup_raises(monkeypatch):
    closed = []

    monkeypatch.setattr(
        safe_webhook_post._PinnedHTTPTransport,
        "close",
        lambda _transport: closed.append(True),
    )

    def failing_client_factory(**kwargs):
        assert isinstance(kwargs["transport"], safe_webhook_post._PinnedHTTPTransport)
        raise RuntimeError("client setup failed")

    result = safe_webhook_post.post_json(
        "https://open.feishu.cn/hook",
        {"msg_type": "text"},
        resolver=_resolver,
        client_factory=failing_client_factory,
    )

    assert result == (False, "Webhook request failed")
    assert closed == [True]


def test_post_json_allows_vendor_webhook_hosts_with_mocked_dns_and_transport():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"code": 0}, request=request)

    ok, body = safe_webhook_post.post_json(
        "https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        {"msg_type": "text", "content": {"text": "hello"}},
        resolver=_resolver,
        transport=httpx.MockTransport(handler),
    )

    assert ok is True
    assert body == '{"code":0}'
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].headers["content-type"] == "application/json"
    assert calls[0].url.host == "open.feishu.cn"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.10.10.10",
        "169.254.169.254",
        "::1",
        "fd00::1",
        "fe80::1",
    ],
)
def test_post_json_rejects_private_loopback_link_local_and_metadata_dns(address):
    transport = httpx.MockTransport(
        lambda request: pytest.fail(f"transport must not be called: {request.url}")
    )

    ok, message = safe_webhook_post.post_json(
        "https://oapi.dingtalk.com/robot/send?access_token=test",
        {"msgtype": "text"},
        resolver=lambda _host, _port: [address],
        transport=transport,
    )

    assert ok is False
    assert "non-public" in message


def test_post_json_rejects_redirect_without_following_it():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.com/next"}, request=request)

    ok, message = safe_webhook_post.post_json(
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        {"msgtype": "text"},
        resolver=_resolver,
        transport=httpx.MockTransport(handler),
    )

    assert ok is False
    assert message == "Webhook redirects are forbidden"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://open.feishu.cn/open-apis/bot/v2/hook/test",
        "https://127.0.0.1/open-apis/bot/v2/hook/test",
        "https://open.feishu.cn:8443/open-apis/bot/v2/hook/test",
        "https://user:password@open.feishu.cn/open-apis/bot/v2/hook/test",
    ],
)
def test_post_json_rejects_unsafe_url_shapes(url):
    ok, message = safe_webhook_post.post_json(
        url,
        {"msgtype": "text"},
        resolver=_resolver,
        transport=httpx.MockTransport(lambda request: pytest.fail("transport must not be called")),
    )

    assert ok is False
    assert message


def test_post_json_enforces_timeout_and_body_limits_without_transport_call():
    transport = httpx.MockTransport(lambda request: pytest.fail("transport must not be called"))
    ok_timeout, timeout_message = safe_webhook_post.post_json(
        "https://open.larksuite.com/open-apis/bot/v2/hook/test",
        {"msg_type": "text"},
        timeout=31,
        resolver=_resolver,
        transport=transport,
    )
    ok_body, body_message = safe_webhook_post.post_json(
        "https://oapi.dingtalk.com/robot/send?access_token=test",
        {"text": "x" * safe_webhook_post.MAX_REQUEST_BODY_BYTES},
        resolver=_resolver,
        transport=transport,
    )

    assert (ok_timeout, timeout_message) == (False, "Webhook timeout is outside the safe range")
    assert (ok_body, body_message) == (False, "Webhook request body is too large")


def test_notification_service_uses_safe_webhook_boundary(monkeypatch):
    calls = []

    def fake_post_json(url, payload, timeout=5):
        calls.append((url, payload, timeout))
        return True, "ok"

    monkeypatch.setattr(safe_webhook_post, "post_json", fake_post_json)

    result = notification_service._post_json("https://example.com/hook", {"a": 1}, timeout=9)

    assert result == (True, "ok")
    assert calls == [("https://example.com/hook", {"a": 1}, 9)]
