from __future__ import annotations

import gzip
import io
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import storage as storage_api
from core import rbac
from services import config_snapshot_storage
from services.storage_service import StorageError, StorageNotFound


def test_s3_snapshot_key_uses_date_vendor_and_safe_readable_segments():
    key = config_snapshot_storage.object_key_for_snapshot(
        "snap-1",
        datetime(2026, 9, 28, 12, 34, 56, tzinfo=timezone.utc),
        vendor="H3C/Comware",
        hostname="SW 01",
        trigger="scheduled-backup",
        encrypted=False,
    )

    assert key == "2026/09/28/H3C_Comware/SW_01_123456_scheduled-backup_snap-1.cfg"


def test_startup_snapshot_key_keeps_startup_suffix():
    key = config_snapshot_storage.object_key_for_snapshot(
        "snap-2",
        datetime(2026, 9, 28, 12, 34, 56, tzinfo=timezone.utc),
        "startup",
        vendor="Cisco",
        hostname="edge-01",
        trigger="manual",
        encrypted=False,
    )

    assert key.endswith("/Cisco/edge-01_123456_manual_snap-2_startup.cfg")


def test_s3_config_content_is_plain_cfg_and_legacy_gzip_remains_readable():
    content = "hostname edge-01\ninterface GigabitEthernet1/0/1\n"

    assert config_snapshot_storage.serialize_s3_config_content(content) == content.encode("utf-8")
    assert config_snapshot_storage.deserialize_config_bytes(gzip.compress(content.encode("utf-8"))) == content


def _content_client(monkeypatch, *, payload: bytes):
    current_user = {"role": "Viewer"}
    accessed_keys: list[str] = []
    profile = SimpleNamespace(backend="s3")

    def get_stream(object_key: str):
        accessed_keys.append(object_key)
        return io.BytesIO(payload)

    monkeypatch.setattr(rbac, "_get_current_user", lambda _request: current_user)
    monkeypatch.setattr(storage_api, "get_storage_provider_config", lambda _provider_id: profile)
    monkeypatch.setattr(
        storage_api,
        "_service_for_profile",
        lambda _profile: SimpleNamespace(get_stream=get_stream),
    )
    app = FastAPI()
    app.include_router(storage_api.router, prefix="/api")
    return TestClient(app), current_user, accessed_keys


def test_config_content_api_requires_admin_and_returns_non_cacheable_cfg(monkeypatch):
    content = "hostname edge-01\n"
    client, current_user, accessed_keys = _content_client(monkeypatch, payload=content.encode("utf-8"))
    query = {
        "provider_id": "storage-profile-1",
        "object_key": "config/2026/09/28/Cisco/edge-01.cfg",
        "download": "true",
    }

    denied = client.get("/api/storage/objects/content", params=query)
    assert denied.status_code == 403
    assert accessed_keys == []

    current_user["role"] = "Administrator"
    response = client.get("/api/storage/objects/content", params=query)

    assert response.status_code == 200
    assert response.text == content
    assert response.headers["content-disposition"] == 'attachment; filename="edge-01.cfg"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert accessed_keys == [query["object_key"]]


def test_config_content_api_rejects_traversal_and_non_cfg_objects(monkeypatch):
    client, current_user, accessed_keys = _content_client(monkeypatch, payload=b"configuration")
    current_user["role"] = "Administrator"

    traversal = client.get(
        "/api/storage/objects/content",
        params={"provider_id": "storage-profile-1", "object_key": "../private.cfg"},
    )
    non_config = client.get(
        "/api/storage/objects/content",
        params={"provider_id": "storage-profile-1", "object_key": "pam/session.cast"},
    )

    assert traversal.status_code == 422
    assert non_config.status_code == 422
    assert accessed_keys == []


def test_config_content_api_hides_storage_error_details(monkeypatch):
    client, current_user, _accessed_keys = _content_client(monkeypatch, payload=b"")
    current_user["role"] = "Administrator"
    monkeypatch.setattr(
        storage_api,
        "_service_for_profile",
        lambda _profile: SimpleNamespace(
            get_stream=lambda _key: (_ for _ in ()).throw(StorageError("secret provider response"))
        ),
    )

    response = client.get(
        "/api/storage/objects/content",
        params={"provider_id": "storage-profile-1", "object_key": "config/edge-01.cfg"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Configuration object is unavailable"}
    assert "secret provider response" not in response.text


def test_config_content_api_maps_missing_objects_to_404(monkeypatch):
    client, current_user, _accessed_keys = _content_client(monkeypatch, payload=b"")
    current_user["role"] = "Administrator"
    monkeypatch.setattr(
        storage_api,
        "_service_for_profile",
        lambda _profile: SimpleNamespace(
            get_stream=lambda _key: (_ for _ in ()).throw(StorageNotFound("secret/object/key.cfg"))
        ),
    )

    response = client.get(
        "/api/storage/objects/content",
        params={"provider_id": "storage-profile-1", "object_key": "config/missing.cfg"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Configuration object not found"}
    assert "secret/object/key.cfg" not in response.text
