import asyncio
import threading

from starlette.requests import Request
from starlette.responses import Response

from core.context import request_id_var, user_var
from main import add_request_id_and_log


def _request(path, token=None):
    headers = [(b"x-request-id", b"req_execution_test")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({"type": "http", "method": "GET", "path": path, "headers": headers})


def test_request_logging_auth_does_not_block_other_requests(monkeypatch):
    from api import users

    validating = threading.Event()
    finish_validation = threading.Event()
    contexts = []
    auth_threads = []
    validation_count = 0

    def validate(_token):
        nonlocal validation_count
        validation_count += 1
        auth_threads.append(threading.get_ident())
        validating.set()
        assert finish_validation.wait(timeout=3)
        return {"username": "test_operator"}

    monkeypatch.setattr(users, "validate_session_token", validate)

    async def handler(request):
        if request.url.path == "/api/devices":
            from core.rbac import _get_current_user

            assert _get_current_user(request) == {"username": "test_operator"}
        contexts.append((request.url.path, user_var.get(), request_id_var.get()))
        return Response(status_code=204)

    async def scenario():
        loop_thread = threading.get_ident()
        authenticated = asyncio.create_task(
            add_request_id_and_log(_request("/api/devices", "test-only-session"), handler)
        )
        try:
            assert await asyncio.to_thread(validating.wait, 2)
            assert not authenticated.done()
            lightweight = await asyncio.wait_for(
                add_request_id_and_log(_request("/api/health/live"), handler), timeout=1,
            )
            assert lightweight.status_code == 204
            assert auth_threads == [auth_threads[0]]
            assert auth_threads[0] != loop_thread
        finally:
            finish_validation.set()
        response = await authenticated
        assert response.headers["X-Request-ID"] == "req_execution_test"

    asyncio.run(scenario())
    assert contexts == [
        ("/api/health/live", "anonymous", "req_execution_test"),
        ("/api/devices", "test_operator", "req_execution_test"),
    ]
    assert validation_count == 1


def test_request_logging_keeps_anonymous_context_when_lookup_fails(monkeypatch):
    from api import users

    def validate(_token):
        raise RuntimeError("synthetic lookup failure")

    monkeypatch.setattr(users, "validate_session_token", validate)
    contexts = []

    async def handler(_request):
        contexts.append(user_var.get())
        return Response(status_code=401)

    response = asyncio.run(
        add_request_id_and_log(_request("/api/devices", "test-only-session"), handler)
    )
    assert response.status_code == 401
    assert contexts == ["anonymous"]
