from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from api import pam as pam_api
from api import pam_web
from api import system
from database import get_db_connection
from schemas.web import WebAccessProfileInput, WebSessionCreateInput, WebSessionExchangeInput, WebSessionStatusInput
from services.pam_web_service import replace_asset_web_profiles


def _seed_asset(asset_id: str = "asset-bmc-1") -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO physical_assets
                   (id, asset_type, hostname, management_ip, created_at, updated_at)
               VALUES (?, 'server', 'srv-bmc-01', '192.0.2.10', ?, ?)""",
            (asset_id, now, now),
        )
        replace_asset_web_profiles(
            conn,
            asset_id,
            [WebAccessProfileInput(
                id="web-bmc-1", profile_name="iDRAC", scheme="https",
                port=8443, path="/login", enabled=True,
            )],
        )
        conn.commit()


def test_web_profile_validation_normalizes_path_and_rejects_bad_port():
    profile = WebAccessProfileInput(profile_name="BMC", scheme="http", port="8080", path="ui")
    assert profile.path == "/ui"
    assert profile.port == 8080
    with pytest.raises(ValueError):
        WebAccessProfileInput(profile_name="bad", scheme="https", port=70000, path="/")


def test_server_asset_web_session_is_credential_free_and_single_use(isolated_db, monkeypatch):
    _seed_asset()
    monkeypatch.setattr(
        pam_web,
        "_authenticated_requester",
        lambda request: {
            "id": "user-1", "username": "alice", "role": "Operator",
            "tenant_id": "tenant-default",
        },
    )

    created = pam_web.create_web_session(
        WebSessionCreateInput(
            asset_id="asset-bmc-1",
            web_profile_id="web-bmc-1",
            access_level="admin",
            reason="BMC inspection",
        ),
        request=None,
    )
    assert created["access_level"] == "admin"
    assert "target_url" not in created
    assert "password" not in repr(created).lower()

    exchanged = pam_web.exchange_web_session(
        WebSessionExchangeInput(session_token=created["session_token"], agent_id="agent-1")
    )
    legacy_exchange = asyncio.run(system.exchange_token(created["session_token"]))
    assert legacy_exchange["success"] is False
    assert exchanged["target_url"] == "https://192.0.2.10:8443/login"
    assert exchanged["asset_type"] == "server"
    assert "password" not in repr(exchanged).lower()

    with pytest.raises(HTTPException) as repeated:
        pam_web.exchange_web_session(
            WebSessionExchangeInput(session_token=created["session_token"], agent_id="agent-1")
        )
    assert repeated.value.status_code == 409

    active = pam_web.update_web_session_status(
        created["session_id"],
        WebSessionStatusInput(
            callback_token=exchanged["callback_token"], agent_id="agent-1",
            status="active", recording_status="recording",
        ),
    )
    assert active["status"] == "active"
    closed = pam_web.update_web_session_status(
        created["session_id"],
        WebSessionStatusInput(
            callback_token=exchanged["callback_token"], agent_id="agent-1",
            status="closed", reason="user_closed", recording_status="pending_upload",
        ),
    )
    assert closed["status"] == "closed"

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT device_id, session_kind, access_level, status, recording_status FROM pam_sessions WHERE id = ?",
            (created["session_id"],),
        ).fetchone()
    assert row["device_id"] == ""
    assert row["session_kind"] == "device_web"
    assert row["access_level"] == "admin"
    assert row["status"] == "closed"
    assert row["recording_status"] == "pending_upload"

    with pytest.raises(HTTPException) as reopen:
        pam_web.update_web_session_status(
            created["session_id"],
            WebSessionStatusInput(
                callback_token=exchanged["callback_token"], agent_id="agent-1",
                status="active", recording_status="recording",
            ),
        )
    assert reopen.value.status_code == 409


def test_web_recording_upload_is_callback_bound_and_path_safe(isolated_db, monkeypatch, tmp_path):
    _seed_asset()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        pam_web,
        "_authenticated_requester",
        lambda request: {
            "id": "user-1", "username": "alice", "role": "Operator",
            "tenant_id": "tenant-default",
        },
    )
    created = pam_web.create_web_session(
        WebSessionCreateInput(asset_id="asset-bmc-1", web_profile_id="web-bmc-1"),
        request=None,
    )
    exchanged = pam_web.exchange_web_session(
        WebSessionExchangeInput(session_token=created["session_token"], agent_id="agent-1")
    )
    pam_web.update_web_session_status(
        created["session_id"],
        WebSessionStatusInput(
            callback_token=exchanged["callback_token"], agent_id="agent-1",
            status="closed", reason="window_closed", recording_status="uploading",
        ),
    )

    upload = UploadFile(file=io.BytesIO(b"GIF89a-test-recording"), filename="../../device.gif")
    result = asyncio.run(
        pam_web.upload_web_recording(
            created["session_id"],
            callback_token=exchanged["callback_token"],
            agent_id="agent-1",
            file=upload,
        )
    )
    assert result["success"] is True
    assert result["recording_status"] == "uploaded"
    assert result["size"] == len(b"GIF89a-test-recording")
    recording_path = tmp_path / "data" / "pam_recordings" / f"{created['session_id']}.gif"
    assert recording_path.is_file()
    assert recording_path.read_bytes() == b"GIF89a-test-recording"

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT recording_path, recording_status FROM pam_sessions WHERE id = ?",
            (created["session_id"],),
        ).fetchone()
    assert row["recording_status"] == "uploaded"
    assert Path(row["recording_path"]) == Path("data") / "pam_recordings" / f"{created['session_id']}.gif"

    listed = pam_api.list_sessions(user={"tenant_id": "tenant-default"}, page=1, page_size=20)
    listed_item = next(item for item in listed["items"] if item["id"] == created["session_id"])
    assert listed_item["session_kind"] == "device_web"
    assert listed_item["recording_status"] == "uploaded"

    bad_callback_upload = UploadFile(file=io.BytesIO(b"GIF89a"), filename="recording.gif")
    with pytest.raises(HTTPException) as bad_callback:
        asyncio.run(
            pam_web.upload_web_recording(
                created["session_id"],
                callback_token="wrong-token",
                agent_id="agent-1",
                file=bad_callback_upload,
            )
        )
    assert bad_callback.value.status_code == 401

    unsupported = UploadFile(file=io.BytesIO(b"secret"), filename="recording.txt")
    with pytest.raises(HTTPException) as bad_format:
        asyncio.run(
            pam_web.upload_web_recording(
                created["session_id"],
                callback_token=exchanged["callback_token"],
                agent_id="agent-1",
                file=unsupported,
            )
        )
    assert bad_format.value.status_code == 415

    monkeypatch.setattr(pam_web, "MAX_RECORDING_BYTES", 4)
    too_large = UploadFile(file=io.BytesIO(b"12345"), filename="recording.gif")
    with pytest.raises(HTTPException) as oversized:
        asyncio.run(
            pam_web.upload_web_recording(
                created["session_id"],
                callback_token=exchanged["callback_token"],
                agent_id="agent-1",
                file=too_large,
            )
        )
    assert oversized.value.status_code == 413
