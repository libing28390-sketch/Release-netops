"""Tests for the pure Python TFTP client service."""

from __future__ import annotations

import os
import socket
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from services.tftp_service import (
    OP_ACK,
    OP_DATA,
    OP_ERROR,
    OP_RRQ,
    OP_WRQ,
    batch_upload_configs_to_tftp,
    upload_bytes_to_tftp,
    upload_file_to_tftp,
)
from services.file_transfer_service import (
    batch_upload_configs,
    normalize_remote_path,
    upload_bytes,
)


def test_tftp_opcodes_defined():
    """Verify standard RFC 1350 binary opcodes."""
    assert OP_RRQ == 1
    assert OP_WRQ == 2
    assert OP_DATA == 3
    assert OP_ACK == 4
    assert OP_ERROR == 5


def test_upload_bytes_to_tftp_success():
    """Simulate a standard TFTP server socket exchange and test upload_bytes_to_tftp."""
    mock_socket = MagicMock()
    # Server responds to WRQ with ACK 0, then responds to DATA 1 with ACK 1
    mock_socket.recvfrom.side_effect = [
        (b"\x00\x04\x00\x00", ("192.168.1.100", 54321)),  # ACK block 0 from ephemeral port
        (b"\x00\x04\x00\x01", ("192.168.1.100", 54321)),  # ACK block 1
    ]

    with patch("socket.socket", return_value=mock_socket):
        success, msg = upload_bytes_to_tftp(
            server_ip="192.168.1.100",
            data=b"sysname SW-Core-01\nvlan 10\n",
            remote_filename="sw-core-01.cfg",
            timeout=2.0,
            retries=1,
        )

    assert success is True
    assert "成功上传" in msg
    assert mock_socket.sendto.call_count >= 2


def test_upload_bytes_to_tftp_server_error():
    """Test TFTP server returning an ERROR packet."""
    mock_socket = MagicMock()
    # Server responds to WRQ with ERROR (Disk full / code 3)
    mock_socket.recvfrom.return_value = (
        b"\x00\x05\x00\x03Disk full or allocation exceeded\x00",
        ("192.168.1.100", 54321),
    )

    with patch("socket.socket", return_value=mock_socket):
        success, msg = upload_bytes_to_tftp(
            server_ip="192.168.1.100",
            data=b"sysname SW-Core-01\n",
            remote_filename="sw-core-01.cfg",
            timeout=2.0,
            retries=1,
        )

    assert success is False
    assert "Disk full" in msg or "错误" in msg


def test_batch_upload_configs_to_tftp():
    """Test batch uploading of multiple device configs plus summary log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f1 = os.path.join(tmpdir, "sw1.cfg")
        f2 = os.path.join(tmpdir, "sw2.cfg")
        with open(f1, "w", encoding="utf-8") as f:
            f.write("sysname SW1\n")
        with open(f2, "w", encoding="utf-8") as f:
            f.write("sysname SW2\n")

        items = [
            {"local_path": f1, "remote_name": "sw1.cfg", "hostname": "SW1"},
            {"local_path": f2, "remote_name": "sw2.cfg", "hostname": "SW2"},
        ]

        with patch("services.tftp_service.upload_file_to_tftp") as mock_upload:
            mock_upload.return_value = (True, "OK")
            with patch("services.tftp_service.upload_bytes_to_tftp") as mock_bytes_upload:
                mock_bytes_upload.return_value = (True, "Summary log uploaded")
                res = batch_upload_configs_to_tftp(
                    server_ip="10.0.0.5",
                    items=items,
                    path_prefix="nexora_backups",
                    summary_log="Batch summary test log",
                )

        assert res["status"] == "success"
        assert res["total"] == 3  # 2 config files + 1 summary log
        assert res["uploaded"] == 3
        assert len(res["details"]) == 3
        assert mock_upload.call_count == 2
        assert mock_bytes_upload.call_count == 1


def test_archive_path_rejects_traversal():
    with pytest.raises(Exception, match="路径无效"):
        normalize_remote_path("backups/../outside.cfg")


def test_sftp_archive_upload_uses_password_auth(monkeypatch):
    import paramiko

    client = MagicMock()
    sftp = MagicMock()
    client.open_sftp.return_value = sftp
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)

    success, message = upload_bytes(
        protocol="sftp",
        server_ip="192.0.2.10",
        server_port=22,
        username="netops",
        password="secret",
        data=b"sysname SW1\n",
        remote_filename="backups/SW1.cfg",
    )

    assert success is True
    assert "sftp://192.0.2.10:22" in message
    client.connect.assert_called_once()
    assert client.connect.call_args.kwargs["username"] == "netops"
    assert client.connect.call_args.kwargs["password"] == "secret"
    sftp.putfo.assert_called_once()


def test_ftp_archive_upload_uses_authenticated_storbinary(monkeypatch):
    import ftplib

    ftp = MagicMock()
    monkeypatch.setattr(ftplib, "FTP", lambda: ftp)

    success, message = upload_bytes(
        protocol="ftp",
        server_ip="192.0.2.11",
        server_port=21,
        username="netftp",
        password="secret",
        data=b"sysname SW1\n",
        remote_filename="backups/SW1.cfg",
    )

    assert success is True
    assert "ftp://192.0.2.11:21" in message
    ftp.login.assert_called_once_with("netftp", "secret")
    ftp.storbinary.assert_called_once()


def test_sftp_batch_passes_one_protocol_to_each_file(monkeypatch, tmp_path):
    config = tmp_path / "SW1.cfg"
    config.write_text("sysname SW1\n", encoding="utf-8")
    calls = []

    def fake_upload_file(**kwargs):
        calls.append(kwargs)
        return True, "ok"

    monkeypatch.setattr("services.file_transfer_service.upload_file", fake_upload_file)
    result = batch_upload_configs(
        protocol="sftp",
        server_ip="192.0.2.12",
        server_port=22,
        username="netops",
        password="secret",
        items=[{"local_path": str(config), "remote_name": "SW1.cfg", "hostname": "SW1"}],
    )

    assert result["status"] == "success"
    assert calls and calls[0]["protocol"] == "sftp"


@pytest.mark.anyio
async def test_tftp_api_endpoints(monkeypatch, tmp_path):
    """Test TFTP API endpoints: settings, test connection, sync snapshot and sync batch."""
    import sqlite3
    from api.configs import (
        TFTPTestPayload,
        TFTPSettingsPayload,
        TFTPSyncSnapshotPayload,
        TFTPSyncBatchPayload,
        get_tftp_settings,
        save_tftp_settings,
        test_tftp_connectivity,
        sync_snapshot_to_tftp,
        sync_batch_to_tftp,
    )

    db_file = str(tmp_path / "test_tftp_api.db")

    def _get_conn():
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        return conn

    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE global_vars (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE config_snapshots (
            id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            file_path TEXT NOT NULL,
            config_type TEXT NOT NULL DEFAULT 'running',
            task_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE config_backup_runs (
            id TEXT PRIMARY KEY,
            tftp_status TEXT NOT NULL DEFAULT 'none',
            tftp_server TEXT NOT NULL DEFAULT '',
            tftp_log TEXT NOT NULL DEFAULT '',
            tftp_uploaded_count INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute("INSERT INTO config_backup_runs (id) VALUES ('run-01')")

    # Create dummy local cfg file
    backup_root = str(tmp_path / "backups_root")
    os.makedirs(os.path.join(backup_root, "Huawei"), exist_ok=True)
    cfg_file = os.path.join(backup_root, "Huawei", "SW-01.cfg")
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write("sysname SW-01\n")

    conn.execute(
        "INSERT INTO config_snapshots (id, hostname, file_path, config_type, task_id) VALUES ('snap-01', 'SW-01', 'Huawei/SW-01.cfg', 'running', 'run-01')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("api.configs.get_db_connection", _get_conn)
    monkeypatch.setattr("api.configs.BACKUP_ROOT", backup_root)

    # 1. Test settings GET & PUT
    save_res = save_tftp_settings(
        TFTPSettingsPayload(enabled=True, server_ip="192.168.1.200", server_port=69, path_prefix="net_backups")
    )
    assert save_res["success"] is True

    get_res = get_tftp_settings()
    assert get_res["success"] is True
    assert get_res["data"]["server_ip"] == "192.168.1.200"

    # 2. Test connectivity probe
    with patch("services.tftp_service.upload_bytes_to_tftp", return_value=(True, "Probe ACK received")):
        probe_res = await test_tftp_connectivity(
            TFTPTestPayload(server_ip="192.168.1.200", server_port=69, path_prefix="net_backups")
        )
        assert probe_res["success"] is True
        assert "探测成功" in probe_res["message"]

    # 3. Test sync single snapshot
    with patch("services.tftp_service.upload_file_to_tftp", return_value=(True, "Uploaded")):
        sync_res = await sync_snapshot_to_tftp(
            TFTPSyncSnapshotPayload(snapshot_id="snap-01", server_ip="192.168.1.200")
        )
        assert sync_res["success"] is True
        assert "SW-01" in sync_res["message"]

    # 4. Test sync batch
    with patch("services.tftp_service.batch_upload_configs_to_tftp", return_value={"status": "success", "uploaded": 1, "total": 1, "details": ["SW-01 OK"]}):
        batch_res = await sync_batch_to_tftp(
            TFTPSyncBatchPayload(run_id="run-01", server_ip="192.168.1.200")
        )
        assert batch_res["success"] is True
        assert batch_res["uploaded"] == 1

    check_conn = _get_conn()
    run_row = check_conn.execute("SELECT * FROM config_backup_runs WHERE id = 'run-01'").fetchone()
    assert run_row["tftp_status"] == "success"
    assert run_row["tftp_server"] == "192.168.1.200"
    assert run_row["tftp_uploaded_count"] == 1
    check_conn.close()
