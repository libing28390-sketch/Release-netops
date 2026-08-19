"""Unified file-transfer service for configuration archive offloading.

Configuration collection remains an SSH/CLI responsibility.  This module is
only responsible for copying already-created local backup files to an archive
server.  SFTP is the secure default for new callers, while the legacy TFTP
wrapper remains available for existing installations and older devices.
"""

from __future__ import annotations

import ftplib
import io
import logging
import posixpath
from pathlib import Path
from typing import Any

from services import tftp_service

logger = logging.getLogger(__name__)

SUPPORTED_TRANSFER_PROTOCOLS = ("sftp", "ftp", "tftp")
DEFAULT_TRANSFER_PROTOCOL = "tftp"
DEFAULT_TRANSFER_PORTS = {
    "sftp": 22,
    "ftp": 21,
    "tftp": 69,
}
TRANSFER_PROTOCOL_LABELS = {
    "sftp": "SFTP",
    "ftp": "FTP",
    "tftp": "TFTP",
}


class FileTransferError(Exception):
    """Raised when a file archive transfer cannot be completed."""


def normalize_transfer_protocol(value: object, *, default: str = DEFAULT_TRANSFER_PROTOCOL) -> str:
    """Return a supported protocol name while preserving legacy TFTP calls."""

    normalized_default = str(default or DEFAULT_TRANSFER_PROTOCOL).strip().lower()
    if normalized_default not in SUPPORTED_TRANSFER_PROTOCOLS:
        normalized_default = DEFAULT_TRANSFER_PROTOCOL

    normalized = str(value or "").strip().lower()
    aliases = {
        "ssh": "sftp",
        "sftp/ssh": "sftp",
        "file transfer": "ftp",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_TRANSFER_PROTOCOLS else normalized_default


def transfer_protocol_label(protocol: object) -> str:
    normalized = normalize_transfer_protocol(protocol)
    return TRANSFER_PROTOCOL_LABELS[normalized]


def default_transfer_port(protocol: object) -> int:
    normalized = normalize_transfer_protocol(protocol)
    return DEFAULT_TRANSFER_PORTS[normalized]


def normalize_remote_path(remote_filename: str) -> str:
    """Normalize a remote path and reject traversal outside the archive root."""

    raw = str(remote_filename or "").strip().replace("\\", "/")
    parts = [part for part in raw.lstrip("/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise FileTransferError("目标文件路径无效")
    return "/".join(parts)


def _validate_transfer_credentials(protocol: str, username: str, password: str) -> None:
    if protocol == "tftp":
        return
    if not str(username or "").strip():
        raise FileTransferError(f"{TRANSFER_PROTOCOL_LABELS[protocol]} 需要用户名")
    if not str(password or ""):
        raise FileTransferError(f"{TRANSFER_PROTOCOL_LABELS[protocol]} 需要密码")


def _ensure_sftp_parent_directories(sftp, remote_path: str) -> None:
    parent = posixpath.dirname(remote_path)
    if not parent:
        return

    current = ""
    for part in parent.split("/"):
        if not part:
            continue
        current = posixpath.join(current, part) if current else part
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def _upload_bytes_to_sftp(
    server_ip: str,
    data: bytes,
    remote_path: str,
    server_port: int,
    username: str,
    password: str,
    timeout: float,
) -> tuple[bool, str]:
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - dependency is part of the runtime image
        return False, f"SFTP 客户端依赖未安装: {exc}"

    client = paramiko.SSHClient()
    # Archive servers are configured explicitly by the operator.  Keep the
    # first-use workflow usable for internal servers without requiring a
    # pre-populated known_hosts file; credentials are still mandatory.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    sftp = None
    try:
        client.connect(
            hostname=server_ip.strip(),
            port=int(server_port),
            username=str(username).strip(),
            password=str(password),
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        sftp = client.open_sftp()
        _ensure_sftp_parent_directories(sftp, remote_path)
        sftp.putfo(io.BytesIO(data), remote_path)
        return True, f"成功上传 {len(data)} 字节到 sftp://{server_ip}:{server_port}/{remote_path}"
    except Exception as exc:
        logger.warning("SFTP upload to %s:%s failed: %s", server_ip, server_port, exc)
        return False, f"SFTP 上传失败: {exc}"
    finally:
        if sftp is not None:
            sftp.close()
        client.close()


def _upload_bytes_to_ftp(
    server_ip: str,
    data: bytes,
    remote_path: str,
    server_port: int,
    username: str,
    password: str,
    timeout: float,
) -> tuple[bool, str]:
    ftp = ftplib.FTP()
    try:
        ftp.connect(server_ip.strip(), int(server_port), timeout=timeout)
        ftp.login(str(username).strip(), str(password))
        ftp.set_pasv(True)
        ftp.storbinary(f"STOR {remote_path}", io.BytesIO(data))
        return True, f"成功上传 {len(data)} 字节到 ftp://{server_ip}:{server_port}/{remote_path}"
    except Exception as exc:
        logger.warning("FTP upload to %s:%s failed: %s", server_ip, server_port, exc)
        return False, f"FTP 上传失败: {exc}"
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def upload_bytes(
    *,
    protocol: str = DEFAULT_TRANSFER_PROTOCOL,
    server_ip: str,
    data: bytes,
    remote_filename: str,
    server_port: int | None = None,
    username: str = "",
    password: str = "",
    timeout: float = 10.0,
    retries: int = 3,
) -> tuple[bool, str]:
    """Upload bytes using SFTP, FTP, or the legacy TFTP implementation."""

    if not str(server_ip or "").strip():
        return False, "文件服务器地址未指定"

    normalized_protocol = normalize_transfer_protocol(protocol)
    port = int(server_port or default_transfer_port(normalized_protocol))
    try:
        remote_path = normalize_remote_path(remote_filename)
        _validate_transfer_credentials(normalized_protocol, username, password)
    except FileTransferError as exc:
        return False, str(exc)

    if normalized_protocol == "tftp":
        return tftp_service.upload_bytes_to_tftp(
            server_ip=server_ip,
            data=data,
            remote_filename=remote_path,
            server_port=port,
            timeout=timeout,
            retries=retries,
        )
    if normalized_protocol == "sftp":
        return _upload_bytes_to_sftp(
            server_ip,
            data,
            remote_path,
            port,
            username,
            password,
            timeout,
        )
    return _upload_bytes_to_ftp(
        server_ip,
        data,
        remote_path,
        port,
        username,
        password,
        timeout,
    )


def upload_file(
    *,
    protocol: str = DEFAULT_TRANSFER_PROTOCOL,
    server_ip: str,
    local_file_path: str,
    remote_filename: str,
    server_port: int | None = None,
    username: str = "",
    password: str = "",
    timeout: float = 10.0,
    retries: int = 3,
) -> tuple[bool, str]:
    normalized_protocol = normalize_transfer_protocol(protocol)
    if normalized_protocol == "tftp":
        # Keep the established TFTP implementation (and its retry semantics)
        # as the compatibility path for existing installations.
        return tftp_service.upload_file_to_tftp(
            server_ip=server_ip,
            local_file_path=local_file_path,
            remote_filename=remote_filename,
            server_port=int(server_port or default_transfer_port(normalized_protocol)),
            timeout=timeout,
            retries=retries,
        )

    path = Path(local_file_path)
    if not path.exists():
        return False, f"本地文件不存在: {local_file_path}"
    try:
        data = path.read_bytes()
    except Exception as exc:
        return False, f"读取本地文件失败: {exc}"

    return upload_bytes(
        protocol=normalized_protocol,
        server_ip=server_ip,
        data=data,
        remote_filename=remote_filename,
        server_port=server_port,
        username=username,
        password=password,
        timeout=timeout,
        retries=retries,
    )


def batch_upload_configs(
    *,
    protocol: str = DEFAULT_TRANSFER_PROTOCOL,
    server_ip: str,
    items: list[dict[str, Any]],
    server_port: int | None = None,
    username: str = "",
    password: str = "",
    path_prefix: str = "backups",
    summary_log: str = "",
) -> dict[str, Any]:
    """Upload backup files and an optional batch summary using one protocol."""

    normalized_protocol = normalize_transfer_protocol(protocol)
    if not str(server_ip or "").strip():
        return {"status": "skipped", "uploaded": 0, "total": 0, "details": ["文件服务器未配置"]}

    if normalized_protocol == "tftp":
        # Preserve the legacy batch implementation so existing TFTP servers
        # and callers keep exactly the same behavior during migration.
        return tftp_service.batch_upload_configs_to_tftp(
            server_ip=server_ip,
            items=items,
            server_port=int(server_port or default_transfer_port(normalized_protocol)),
            path_prefix=path_prefix,
            summary_log=summary_log,
        )

    clean_prefix = str(path_prefix or "").strip("/").replace("\\", "/")
    uploaded_count = 0
    total_count = len(items) + (1 if summary_log else 0)
    details: list[str] = []
    label = TRANSFER_PROTOCOL_LABELS[normalized_protocol]

    for item in items:
        local_path = item.get("local_path", "")
        remote_name = item.get("remote_name", "")
        hostname = item.get("hostname", "unknown")
        if not local_path or not remote_name:
            continue

        target_remote_path = f"{clean_prefix}/{remote_name}" if clean_prefix else remote_name
        ok, msg = upload_file(
            protocol=normalized_protocol,
            server_ip=server_ip,
            local_file_path=local_path,
            remote_filename=target_remote_path,
            server_port=server_port,
            username=username,
            password=password,
        )
        if ok:
            uploaded_count += 1
            details.append(f"[{hostname}] {label} 上传成功: {target_remote_path}")
        else:
            details.append(f"[{hostname}] {label} 上传失败: {msg}")

    if summary_log and summary_log.strip():
        timestamp_str = __import__("time").strftime("%Y%m%d_%H%M%S")
        log_remote_name = f"backup_summary_{timestamp_str}.log"
        target_log_path = f"{clean_prefix}/{log_remote_name}" if clean_prefix else log_remote_name
        ok, msg = upload_bytes(
            protocol=normalized_protocol,
            server_ip=server_ip,
            data=summary_log.encode("utf-8"),
            remote_filename=target_log_path,
            server_port=server_port,
            username=username,
            password=password,
        )
        if ok:
            uploaded_count += 1
            details.append(f"[批次摘要] {label} 上传成功: {target_log_path}")
        else:
            details.append(f"[批次摘要] {label} 上传失败: {msg}")

    status = "success" if uploaded_count == total_count and total_count > 0 else ("partial" if uploaded_count > 0 else "failed")
    return {
        "status": status,
        "uploaded": uploaded_count,
        "total": total_count,
        "details": details,
        "server": f"{server_ip}:{server_port or default_transfer_port(normalized_protocol)}",
        "protocol": normalized_protocol,
    }


# Backward-compatible names used by older callers and tests.
def upload_bytes_to_tftp(**kwargs) -> tuple[bool, str]:
    return upload_bytes(protocol="tftp", **kwargs)


def upload_file_to_tftp(**kwargs) -> tuple[bool, str]:
    return upload_file(protocol="tftp", **kwargs)


def batch_upload_configs_to_tftp(**kwargs) -> dict[str, Any]:
    return batch_upload_configs(protocol="tftp", **kwargs)
