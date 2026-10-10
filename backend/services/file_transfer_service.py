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
import time
import zipfile
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
    archive_name: str | None = None,
) -> dict[str, Any]:
    """Upload one readable ZIP archive containing the whole backup batch.

    ``items`` are expected to contain decoded configuration bytes in ``data``
    when called by the configuration backup API.  The local snapshot files can
    remain encrypted; only the in-memory decoded bytes are written to the
    remote archive.  Reading ``local_path`` remains as a compatibility fallback
    for older callers that already provide plaintext files.
    """

    normalized_protocol = normalize_transfer_protocol(protocol)
    if not str(server_ip or "").strip():
        return {"status": "skipped", "uploaded": 0, "total": 0, "details": ["文件服务器未配置"]}

    clean_prefix = str(path_prefix or "").strip("/").replace("\\", "/")
    label = TRANSFER_PROTOCOL_LABELS[normalized_protocol]
    details: list[str] = []
    used_names: set[str] = set()
    archive_buffer = io.BytesIO()
    file_count = 0
    skipped_count = 0

    def _as_bytes(item: dict[str, Any]) -> bytes | None:
        value = item.get("data")
        if value is None:
            local_path = str(item.get("local_path") or "")
            if not local_path:
                return None
            try:
                value = Path(local_path).read_bytes()
            except OSError:
                return None
        if isinstance(value, str):
            return value.encode("utf-8")
        if isinstance(value, (bytearray, memoryview)):
            return bytes(value)
        return value if isinstance(value, bytes) else None

    def _unique_entry_name(raw_name: str) -> str:
        normalized_name = normalize_remote_path(raw_name)
        candidate = normalized_name
        counter = 2
        while candidate in used_names:
            stem, suffix = posixpath.splitext(normalized_name)
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1
        used_names.add(candidate)
        return candidate

    try:
        with zipfile.ZipFile(archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in items:
                hostname = str(item.get("hostname") or "unknown")
                raw_name = item.get("archive_name") or item.get("remote_name")
                data = _as_bytes(item)
                if not raw_name or data is None:
                    skipped_count += 1
                    details.append(f"[{hostname}] 已跳过：配置归档内容无效")
                    continue
                try:
                    entry_name = _unique_entry_name(str(raw_name))
                except FileTransferError as exc:
                    skipped_count += 1
                    details.append(f"[{hostname}] 已跳过：{exc}")
                    continue
                archive.writestr(entry_name, data)
                file_count += 1

            if summary_log and summary_log.strip():
                archive.writestr(_unique_entry_name("backup_summary.txt"), summary_log.encode("utf-8"))
    except Exception as exc:
        logger.warning("Could not build configuration archive: %s", exc)
        return {
            "status": "failed",
            "uploaded": 0,
            "total": 1,
            "file_count": 0,
            "skipped": len(items),
            "details": details + [f"批量归档失败: {exc}"],
            "server": f"{server_ip}:{server_port or default_transfer_port(normalized_protocol)}",
            "protocol": normalized_protocol,
        }

    if file_count == 0:
        return {
            "status": "failed",
            "uploaded": 0,
            "total": 1,
            "file_count": 0,
            "skipped": skipped_count,
            "details": details + ["批量归档失败：没有可上传的有效配置文件"],
            "server": f"{server_ip}:{server_port or default_transfer_port(normalized_protocol)}",
            "protocol": normalized_protocol,
        }

    raw_archive_name = str(archive_name or f"config_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip").strip()
    try:
        clean_archive_name = normalize_remote_path(raw_archive_name)
    except FileTransferError as exc:
        return {
            "status": "failed",
            "uploaded": 0,
            "total": 1,
            "file_count": file_count,
            "skipped": skipped_count,
            "details": details + [f"批量归档失败：{exc}"],
            "server": f"{server_ip}:{server_port or default_transfer_port(normalized_protocol)}",
            "protocol": normalized_protocol,
        }
    if not clean_archive_name.lower().endswith(".zip"):
        clean_archive_name += ".zip"
    target_remote_path = f"{clean_prefix}/{clean_archive_name}" if clean_prefix else clean_archive_name

    ok, msg = upload_bytes(
        protocol=normalized_protocol,
        server_ip=server_ip,
        data=archive_buffer.getvalue(),
        remote_filename=target_remote_path,
        server_port=server_port,
        username=username,
        password=password,
    )
    if ok:
        status = "partial" if skipped_count else "success"
        details.append(f"[批次归档] {label} 上传成功: {target_remote_path}（{file_count} 个配置文件）")
        uploaded_count = 1
    else:
        status = "failed"
        details.append(f"[批次归档] {label} 上传失败: {msg}")
        uploaded_count = 0

    return {
        "status": status,
        "uploaded": uploaded_count,
        "total": 1,
        "file_count": file_count,
        "skipped": skipped_count,
        "archive_name": clean_archive_name,
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
