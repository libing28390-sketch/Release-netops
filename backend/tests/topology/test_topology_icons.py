from __future__ import annotations

import io
import struct
from types import SimpleNamespace
import uuid
import zlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import api.users as users_api
from api.topology_icons import router as topology_icons_router
from database import get_db_connection
from database.migrations import discover_migrations
from services import topology_icon_service
from services.storage_service import StorageError, StorageObject
from services.topology_icon_service import (
    TopologyIconError,
    create_topology_icon,
    get_topology_icon_content,
    list_topology_icons,
    set_topology_device_icon,
    set_topology_icon_default,
    validate_topology_icon_upload,
)


def _png(width: int = 32, height: int = 32) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big") + kind + data
            + (zlib.crc32(kind + data) & 0xFFFFFFFF).to_bytes(4, "big")
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw_pixels = b"".join(b"\x00" + bytes((25, 92, 175, 255)) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw_pixels)) + chunk(b"IEND", b"")


_SAFE_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="shell"><stop offset="0" stop-color="#fff"/></linearGradient></defs>
<path d="M8 12h48v40H8z" fill="url(#shell)"/>
</svg>"""


class _MemoryStorage:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_stream(self, key, stream, content_type=None):
        content = stream.read()
        self.objects[key] = (content, str(content_type or ""))
        import hashlib

        return StorageObject(
            backend="local",
            bucket=None,
            object_key=key,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type=content_type,
        )

    def get_stream(self, key):
        return io.BytesIO(self.objects[key][0])

    def delete(self, key):
        self.objects.pop(key, None)


def _use_memory_storage(monkeypatch):
    storage = _MemoryStorage()
    provider = SimpleNamespace(source="environment", backend="local", bucket="", id=None)
    monkeypatch.setattr(topology_icon_service, "effective_storage_provider", lambda: provider)
    monkeypatch.setattr(topology_icon_service, "build_storage_service", lambda **_kwargs: storage)
    return storage


def _insert_device(device_id: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, role) VALUES (?, ?, ?)",
            (device_id, device_id, "access"),
        )
        conn.commit()
    finally:
        conn.close()


def _create_icon(device_type: str, name: str = "默认 A", content: bytes = _png()) -> dict:
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    return create_topology_icon(
        device_type=device_type,
        name=name,
        filename="icon.png" if is_png else "icon.svg",
        content_type="image/png" if is_png else "image/svg+xml",
        content=content,
        actor_id="icon-test-user",
    )


def test_s3_endpoint_error_identifies_storage_settings(monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    provider = SimpleNamespace(source="database", backend="s3", id="icon-storage")

    def unreachable(*_args):
        raise StorageError("S3 upload failed") from EndpointConnectionError(endpoint_url="https://storage.invalid")

    monkeypatch.setattr(topology_icon_service, "effective_storage_provider", lambda: provider)
    monkeypatch.setattr(topology_icon_service, "build_storage_service", lambda **_kwargs: SimpleNamespace(put_stream=unreachable))

    with pytest.raises(TopologyIconError, match="Check the endpoint in Storage Settings") as error:
        _create_icon("switch")

    assert error.value.status_code == 503


def test_m0326_topology_icon_schema_is_registered_and_repeatable(isolated_db):
    from database.migrations import m0326_topology_device_icons

    versions = {migration.VERSION: migration.NAME for migration in discover_migrations()}
    assert versions[326] == "topology_device_icons"

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        m0326_topology_device_icons.upgrade(cursor, use_pg=True)
        conn.commit()
        m0326_topology_device_icons.upgrade(cursor, use_pg=True)
        conn.commit()
        tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name IN (
                      'topology_device_icons',
                      'topology_device_icon_defaults',
                      'topology_device_icon_overrides'
                  )
                """
            ).fetchall()
        }
    finally:
        conn.close()

    assert tables == {
        "topology_device_icons",
        "topology_device_icon_defaults",
        "topology_device_icon_overrides",
    }


def test_validates_static_svg_and_png_and_rejects_active_svg_content():
    svg = validate_topology_icon_upload(
        device_type="firewall",
        name="Firewall B",
        filename="firewall.svg",
        content_type="image/svg+xml",
        content=_SAFE_SVG,
    )
    png = validate_topology_icon_upload(
        device_type="switch",
        name="Switch C",
        filename="switch.png",
        content_type="image/png",
        content=_png(48, 32),
    )
    assert svg.content_type == "image/svg+xml"
    assert png.content_type == "image/png"
    assert len(svg.sha256) == 64

    unsafe_svg = _SAFE_SVG.replace(b"<path", b"<script>alert(1)</script><path")
    try:
        validate_topology_icon_upload(
            device_type="firewall",
            name="Unsafe",
            filename="unsafe.svg",
            content_type="image/svg+xml",
            content=unsafe_svg,
        )
    except TopologyIconError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("script elements must be rejected")

    external_svg = _SAFE_SVG.replace(b"url(#shell)", b"url(https://example.com/icon.svg#shell)")
    try:
        validate_topology_icon_upload(
            device_type="firewall",
            name="External",
            filename="external.svg",
            content_type="image/svg+xml",
            content=external_svg,
        )
    except TopologyIconError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("external SVG references must be rejected")

    try:
        validate_topology_icon_upload(
            device_type="firewall",
            name="Encoded DTD",
            filename="encoded.svg",
            content_type="image/svg+xml",
            content="<?xml version='1.0' encoding='UTF-16'?><!DOCTYPE svg [<!ENTITY x 'unsafe'>]>".encode("utf-16"),
        )
    except TopologyIconError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("non-UTF-8 SVG content must be rejected before XML parsing")

    try:
        validate_topology_icon_upload(
            device_type="switch",
            name="Truncated PNG",
            filename="truncated.png",
            content_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + bytes(17),
        )
    except TopologyIconError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("PNG files must include valid image data and an IEND chunk")


def test_icon_catalog_type_defaults_and_device_overrides(isolated_db, monkeypatch):
    storage = _use_memory_storage(monkeypatch)
    operator_id = str(uuid.uuid4())
    first_switch = _create_icon("switch", "Switch C")
    second_switch = _create_icon("switch", "Switch D", _SAFE_SVG)
    firewall_icon = _create_icon("firewall", "Firewall B")
    _insert_device("icon-test-switch")

    set_topology_icon_default(device_type="switch", icon_id=first_switch["id"], actor_id=operator_id)
    set_topology_device_icon(
        device_id="icon-test-switch",
        device_type="switch",
        icon_id=second_switch["id"],
        actor_id=operator_id,
    )

    catalog = list_topology_icons()
    assert [icon["name"] for icon in catalog["icons"] if icon["device_type"] == "switch"] == ["Switch C", "Switch D"]
    assert catalog["type_defaults"]["switch"] == first_switch["id"]
    assert catalog["device_overrides"]["icon-test-switch"] == {
        "device_type": "switch",
        "icon_id": second_switch["id"],
    }
    assert catalog["icons"][0]["content_url"].startswith("/api/topology/icons/")
    assert get_topology_icon_content(second_switch["id"]) == (_SAFE_SVG, "image/svg+xml")
    object_key = f"topology/device-icons/{second_switch['id']}/original.svg"
    storage.objects[object_key] = (b"X" + _SAFE_SVG[1:], "image/svg+xml")
    with pytest.raises(TopologyIconError, match="integrity") as tampered:
        get_topology_icon_content(second_switch["id"])
    assert tampered.value.status_code == 503

    try:
        set_topology_icon_default(device_type="switch", icon_id=firewall_icon["id"], actor_id=operator_id)
    except TopologyIconError as error:
        assert error.status_code == 422
    else:
        raise AssertionError("icons cannot be assigned across device types")

    try:
        set_topology_device_icon(
            device_id="missing-device",
            device_type="switch",
            icon_id=second_switch["id"],
            actor_id=operator_id,
        )
    except TopologyIconError as error:
        assert error.status_code == 404
    else:
        raise AssertionError("device overrides must target an existing device")

    set_topology_device_icon(
        device_id="icon-test-switch", device_type="switch", icon_id=None, actor_id=operator_id,
    )
    set_topology_icon_default(device_type="switch", icon_id=None, actor_id=operator_id)
    catalog = list_topology_icons()
    assert "switch" not in catalog["type_defaults"]
    assert "icon-test-switch" not in catalog["device_overrides"]
    assert len(storage.objects) == 3


def test_catalog_requires_viewer_and_reports_manage_capability(isolated_db, make_user, monkeypatch):
    from fastapi.testclient import TestClient

    storage = _use_memory_storage(monkeypatch)
    viewer = make_user("topology-icons-viewer", role="Viewer")
    operator = make_user("topology-icons-operator", role="Operator")
    users_by_token = {"viewer-token": viewer, "operator-token": operator}
    monkeypatch.setattr(users_api, "validate_session_token", lambda token: users_by_token.get(token))

    app = FastAPI()
    app.include_router(topology_icons_router, prefix="/api")
    client = TestClient(app)

    assert client.get("/api/topology/icons").status_code == 401
    viewer_response = client.get(
        "/api/topology/icons", headers={"Authorization": "Bearer viewer-token"},
    )
    assert viewer_response.status_code == 200
    assert viewer_response.json()["can_manage"] is False

    operator_response = client.get(
        "/api/topology/icons", headers={"Authorization": "Bearer operator-token"},
    )
    assert operator_response.status_code == 200
    assert operator_response.json()["can_manage"] is True

    denied_upload = client.post(
        "/api/topology/icons",
        headers={"Authorization": "Bearer viewer-token"},
        data={"device_type": "switch", "name": "Switch"},
        files={"file": ("switch.png", _png(), "image/png")},
    )
    assert denied_upload.status_code == 403

    uploaded = client.post(
        "/api/topology/icons",
        headers={"Authorization": "Bearer operator-token"},
        data={"device_type": "switch", "name": "Switch C"},
        files={"file": ("switch.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    icon = uploaded.json()
    downloaded = client.get(icon["content_url"], headers={"Authorization": "Bearer viewer-token"})
    assert downloaded.status_code == 200
    assert downloaded.content == _png()
    assert downloaded.headers["X-Content-Type-Options"] == "nosniff"
