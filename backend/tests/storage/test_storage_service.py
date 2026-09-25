from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from api import storage_providers
from services.storage_service import (
    LocalStorageBackend,
    S3StorageBackend,
    StorageNotFound,
    StorageProviderConfig,
    normalize_object_key,
)


def test_local_backend_put_get_stat_delete_is_atomic(tmp_path):
    backend = LocalStorageBackend(tmp_path / "objects")
    payload = b"encrypted config or recording bytes"

    stored = backend.put_stream("config/2026/09/snap-1.cfg.enc", io.BytesIO(payload), "application/octet-stream")

    assert stored.backend == "local"
    assert stored.size == len(payload)
    assert stored.sha256
    assert backend.stat(stored.object_key).size == len(payload)
    with backend.get_stream(stored.object_key) as handle:
        assert handle.read() == payload

    backend.delete(stored.object_key)
    assert not backend.exists(stored.object_key)
    with pytest.raises(StorageNotFound):
        backend.get_stream(stored.object_key)


@pytest.mark.parametrize("value", ["../escape", "/absolute", "C:/absolute", "", "a/../../b"])
def test_object_keys_reject_traversal(value):
    with pytest.raises(ValueError):
        normalize_object_key(value)


def test_local_backend_does_not_expose_real_path(tmp_path):
    backend = LocalStorageBackend(tmp_path / "objects")
    stored = backend.put_stream("pam/session.cast", b"cast")
    assert stored.object_key == "pam/session.cast"
    assert str(tmp_path) not in stored.object_key


def test_s3_health_check_returns_sanitized_service_error_code(monkeypatch):
    secret_text = "credential must not be returned"

    class FakeClientError(Exception):
        response = {
            "Error": {"Code": "SignatureDoesNotMatch", "Message": secret_text},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

        def __init__(self):
            super().__init__(secret_text)

    class FakeS3Client:
        def list_objects_v2(self, **_kwargs):
            raise FakeClientError()

    backend = S3StorageBackend(
        endpoint_url="http://storage.test:8333",
        bucket="nexora",
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
    )
    monkeypatch.setattr(backend, "_client", lambda: FakeS3Client())

    ok, message = backend.health_check()

    assert not ok
    assert "SignatureDoesNotMatch (HTTP 403)" in message
    assert secret_text not in message
    assert "test-secret-key" not in message


def test_s3_health_check_rejects_provider_controlled_error_code(monkeypatch):
    class FakeClientError(Exception):
        response = {
            "Error": {"Code": "secret://credential-text"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        }

    class FakeS3Client:
        def list_objects_v2(self, **_kwargs):
            raise FakeClientError()

    backend = S3StorageBackend(endpoint_url="http://storage.test:8333", bucket="nexora")
    monkeypatch.setattr(backend, "_client", lambda: FakeS3Client())

    ok, message = backend.health_check()

    assert not ok
    assert message == "S3 storage check failed: HTTP 403"
    assert "credential-text" not in message


def test_storage_provider_test_preserves_sanitized_health_message(monkeypatch):
    expected_message = "S3 storage check failed: AccessDenied (HTTP 403)"
    monkeypatch.setattr(
        storage_providers,
        "_service_for_profile",
        lambda _profile: SimpleNamespace(health_check=lambda: (False, expected_message)),
    )
    profile = StorageProviderConfig(
        id=None,
        name="Test provider",
        backend="s3",
        endpoint_url="http://storage.test:8333",
        bucket="nexora",
        region="us-east-1",
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        force_path_style=True,
        verify_tls=True,
    )

    result = storage_providers._test_profile(profile)

    assert result["ok"] is False
    assert result["message"] == expected_message
    assert "test-secret-key" not in result["message"]
