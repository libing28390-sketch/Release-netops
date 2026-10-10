"""
tftp_service.py - Lightweight pure-Python TFTP client (RFC 1350) for config and log offloading.

Supports sending WRQ, transmitting 512-byte DATA blocks, waiting for ACKs, and handling timeouts/retries.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# TFTP Opcodes
OP_RRQ = 1
OP_WRQ = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5

DEFAULT_BLOCK_SIZE = 512
DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 3


class TFTPClientError(Exception):
    """Base exception for TFTP transfer failures."""


def upload_bytes_to_tftp(
    server_ip: str,
    data: bytes,
    remote_filename: str,
    server_port: int = 69,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> tuple[bool, str]:
    """Upload raw bytes to a remote TFTP server using WRQ octet mode.

    Returns:
        tuple[bool, str]: (success, message)
    """
    if not server_ip or not server_ip.strip():
        return False, "TFTP 服务器 IP 未指定"
    if not remote_filename or not remote_filename.strip():
        return False, "目标文件名未指定"

    # Normalize filename for remote TFTP root
    clean_filename = remote_filename.strip().replace("\\", "/")
    if clean_filename.startswith("/"):
        clean_filename = clean_filename.lstrip("/")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    try:
        # Build WRQ packet: Opcode 2 (2 bytes) + filename + 0x00 + 'octet' + 0x00
        wrq_packet = struct.pack("!H", OP_WRQ) + clean_filename.encode("utf-8") + b"\x00octet\x00"

        # Send initial WRQ to the server port (usually 69)
        server_addr = (server_ip.strip(), int(server_port))
        tid_addr = None

        # Step 1: Send WRQ and wait for ACK block 0
        ack_received = False
        for attempt in range(retries):
            try:
                sock.sendto(wrq_packet, server_addr)
                resp, addr = sock.recvfrom(1024)
                if len(resp) >= 4:
                    opcode, block = struct.unpack("!HH", resp[:4])
                    if opcode == OP_ACK and block == 0:
                        tid_addr = addr  # Server chose a dynamic TID port
                        ack_received = True
                        break
                    elif opcode == OP_ERROR:
                        err_code = block
                        err_msg = resp[4:].decode("utf-8", errors="replace").rstrip("\x00")
                        return False, f"TFTP 服务端返回错误 (Code {err_code}): {err_msg}"
            except (socket.timeout, TimeoutError):
                logger.warning("TFTP WRQ to %s:%s timed out (attempt %d/%d)", server_ip, server_port, attempt + 1, retries)
            except Exception as exc:
                return False, f"TFTP 连接失败: {exc}"

        if not ack_received or not tid_addr:
            return False, f"TFTP 服务器 {server_ip}:{server_port} 无响应 (超时未收到 ACK 0)"

        # Step 2: Transmit DATA blocks
        total_len = len(data)
        num_blocks = (total_len // DEFAULT_BLOCK_SIZE) + 1
        offset = 0
        block_num = 1

        while offset <= total_len:
            chunk = data[offset : offset + DEFAULT_BLOCK_SIZE]
            data_packet = struct.pack("!HH", OP_DATA, block_num & 0xFFFF) + chunk

            block_acked = False
            for attempt in range(retries):
                try:
                    sock.sendto(data_packet, tid_addr)
                    resp, addr = sock.recvfrom(1024)
                    if len(resp) >= 4 and addr[0] == tid_addr[0]:
                        opcode, ack_block = struct.unpack("!HH", resp[:4])
                        if opcode == OP_ACK and ack_block == (block_num & 0xFFFF):
                            block_acked = True
                            break
                        elif opcode == OP_ERROR:
                            err_code = ack_block
                            err_msg = resp[4:].decode("utf-8", errors="replace").rstrip("\x00")
                            return False, f"TFTP 数据传输错误 (Block {block_num}): {err_msg}"
                except (socket.timeout, TimeoutError):
                    logger.warning("TFTP Block %d timed out (attempt %d/%d)", block_num, attempt + 1, retries)
                except Exception as exc:
                    return False, f"TFTP 传输中断 (Block {block_num}): {exc}"

            if not block_acked:
                return False, f"TFTP Block {block_num} 确认失败，已超过最大重试次数"

            offset += len(chunk)
            block_num += 1

            # A transfer is finished when the block is less than 512 bytes (including a final 0-byte block)
            if len(chunk) < DEFAULT_BLOCK_SIZE:
                break

        return True, f"成功上传 {len(data)} 字节到 tftp://{server_ip}:{server_port}/{clean_filename}"

    finally:
        sock.close()


def upload_file_to_tftp(
    server_ip: str,
    local_file_path: str,
    remote_filename: str,
    server_port: int = 69,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> tuple[bool, str]:
    """Read a local file and upload its contents to a TFTP server."""
    path = Path(local_file_path)
    if not path.exists():
        return False, f"本地文件不存在: {local_file_path}"

    try:
        data = path.read_bytes()
    except Exception as exc:
        return False, f"读取本地文件失败: {exc}"

    return upload_bytes_to_tftp(
        server_ip=server_ip,
        data=data,
        remote_filename=remote_filename,
        server_port=server_port,
        timeout=timeout,
        retries=retries,
    )


def batch_upload_configs_to_tftp(
    server_ip: str,
    items: list[dict[str, Any]],
    server_port: int = 69,
    path_prefix: str = "backups",
    summary_log: str = "",
) -> dict[str, Any]:
    """Upload a batch of backed-up configuration files and optional summary log to TFTP.

    Args:
        server_ip: Target TFTP server IP.
        items: List of dicts containing {'local_path': str, 'remote_name': str, 'hostname': str}.
        server_port: TFTP UDP port (default 69).
        path_prefix: Subfolder prefix on the remote server (e.g. 'backups/202608').
        summary_log: Plaintext content of the batch summary log file.

    Returns:
        dict with {status: 'success'|'partial'|'failed', uploaded: int, total: int, details: list[str]}
    """
    if not server_ip:
        return {"status": "skipped", "uploaded": 0, "total": 0, "details": ["TFTP server IP not configured"]}

    clean_prefix = (path_prefix or "").strip("/").replace("\\", "/")
    uploaded_count = 0
    total_count = len(items) + (1 if summary_log else 0)
    details: list[str] = []

    for item in items:
        local_path = item.get("local_path", "")
        remote_name = item.get("remote_name", "")
        hostname = item.get("hostname", "unknown")

        if not local_path or not remote_name:
            continue

        target_remote_path = f"{clean_prefix}/{remote_name}" if clean_prefix else remote_name
        ok, msg = upload_file_to_tftp(
            server_ip=server_ip,
            local_file_path=local_path,
            remote_filename=target_remote_path,
            server_port=server_port,
        )

        if ok:
            uploaded_count += 1
            details.append(f"[{hostname}] 上传成功: {target_remote_path}")
        else:
            details.append(f"[{hostname}] 上传失败: {msg}")

    # Upload batch summary log if provided
    if summary_log and summary_log.strip():
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        log_remote_name = f"backup_summary_{timestamp_str}.log"
        target_log_path = f"{clean_prefix}/{log_remote_name}" if clean_prefix else log_remote_name
        ok, msg = upload_bytes_to_tftp(
            server_ip=server_ip,
            data=summary_log.encode("utf-8"),
            remote_filename=target_log_path,
            server_port=server_port,
        )
        if ok:
            uploaded_count += 1
            details.append(f"[Summary Log] 上传成功: {target_log_path}")
        else:
            details.append(f"[Summary Log] 上传失败: {msg}")

    status = "success" if uploaded_count == total_count and total_count > 0 else ("partial" if uploaded_count > 0 else "failed")
    return {
        "status": status,
        "uploaded": uploaded_count,
        "total": total_count,
        "details": details,
        "server": f"{server_ip}:{server_port}",
    }
