import re
import time
from typing import Any, Dict, List


# 尽量覆盖实验环境与老设备常见的 SSH 算法组合。
# 注意：这里做的是“尽可能兼容”，不是突破底层库本身不支持的算法实现边界。
LEGACY_KEX_ALGORITHMS: List[str] = [
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group-exchange-sha1",
    "diffie-hellman-group1-sha1",
]

LEGACY_HOST_KEY_ALGORITHMS: List[str] = [
    "ssh-rsa",
]

LEGACY_CIPHERS: List[str] = [
    "aes128-ctr",
    "aes192-ctr",
    "aes256-ctr",
    "aes128-cbc",
    "aes192-cbc",
    "aes256-cbc",
    "3des-cbc",
]

LEGACY_MAC_ALGORITHMS: List[str] = [
    "hmac-sha2-256",
    "hmac-sha2-512",
    "hmac-sha1",
    "hmac-sha1-96",
]

LEGACY_SSH_ERROR_CODE = "legacy_ssh_algorithms"
SSH_AUTH_ERROR_CODE = "ssh_authentication_failed"
SSH_TIMEOUT_ERROR_CODE = "ssh_transport_timeout"
SSH_TRANSPORT_ERROR_CODE = "ssh_transport_unreachable"

PAGING_PROMPT_RE = re.compile(
    r"(?:----\s*More\s*----|--\s*More\s*--|--More--|<---\s*More\s*--->|Press\s+any\s+key\s+to\s+continue)",
    re.IGNORECASE,
)


def build_netmiko_compatibility_kwargs() -> Dict[str, Any]:
    """
    Netmiko/Paramiko 兼容老设备的连接参数。

    - disabled_algorithms={} 告诉 Paramiko 不禁用任何算法，
      从而保留 diffie-hellman-group14-sha1、ssh-rsa 等 legacy 算法
    - use_keys/allow_agent 关闭本地 SSH agent 干扰
    - disable_sha2_fix 打开旧 Cisco/旧 Paramiko 兼容路径
    - conn_timeout: 增加 SSH 连接/协商超时时间以防止慢速设备超时 (R2.7)
    """
    return {
        "disabled_algorithms": {},
        "use_keys": False,
        "allow_agent": False,
        "disable_sha2_fix": True,
        "conn_timeout": 20,
    }


def contains_paging_prompt(output: str) -> bool:
    """Return whether CLI output is paused at a vendor paging prompt."""
    return bool(PAGING_PROMPT_RE.search(output or ""))


def drain_paged_output(conn: Any, output: str, *, read_timeout: int = 30, max_pages: int = 200) -> str:
    """
    Continue reading a Netmiko channel when output stops at a paging prompt.

    Some devices reject pagination-disable commands for low-privilege accounts.
    In that case long show/display output can stop at prompts such as
    ``---- More ----``. Sending a space is the least invasive cross-vendor
    response and keeps read-only automation on normal credentials.
    """
    pending = contains_paging_prompt(output)
    if not pending:
        return output

    collected = PAGING_PROMPT_RE.sub("", output or "")
    per_read_timeout = max(1, min(int(read_timeout or 30), 10))
    for _ in range(max_pages):
        if not pending:
            break
        try:
            conn.write_channel(" ")
            chunk = conn.read_channel_timing(read_timeout=per_read_timeout)
        except AttributeError:
            break
        except Exception:
            chunk = ""
        if not chunk:
            time.sleep(0.1)
            try:
                chunk = conn.read_channel_timing(read_timeout=1)
            except Exception:
                chunk = ""
        if not chunk:
            break
        pending = contains_paging_prompt(chunk)
        collected += PAGING_PROMPT_RE.sub("", chunk)
    return collected


def build_system_ssh_open_cmd() -> List[str]:
    """为 OpenSSH/system transport 生成兼容老设备的额外参数。
    
    使用直接覆盖（=）而非追加（+=），因为现代OpenSSH可能在编译时禁用了legacy算法。
    优先列出legacy算法以确保兼容性。
    """
    # 现代算法用作fallback（若设备支持）
    modern_kex = [
        "curve25519-sha256",
        "curve25519-sha256@libssh.org",
        "ecdh-sha2-nistp256",
        "ecdh-sha2-nistp384",
        "ecdh-sha2-nistp521",
        "diffie-hellman-group-exchange-sha256",
    ]
    
    modern_host_keys = [
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "rsa-sha2-512",
        "rsa-sha2-256",
    ]
    
    modern_ciphers = [
        "aes128-gcm@openssh.com",
        "aes256-gcm@openssh.com",
        "aes128-ctr",
        "aes256-ctr",
    ]
    
    modern_macs = [
        "umac-64-etm@openssh.com",
        "umac-128-etm@openssh.com",
        "hmac-sha2-256-etm@openssh.com",
        "hmac-sha2-512-etm@openssh.com",
        "hmac-sha2-256",
        "hmac-sha2-512",
    ]
    
    return [
        "-o", f"KexAlgorithms={','.join(LEGACY_KEX_ALGORITHMS + modern_kex)}",
        "-o", f"HostKeyAlgorithms={','.join(LEGACY_HOST_KEY_ALGORITHMS + modern_host_keys)}",
        "-o", f"PubkeyAcceptedAlgorithms={','.join(LEGACY_HOST_KEY_ALGORITHMS + modern_host_keys)}",
        "-o", f"Ciphers={','.join(LEGACY_CIPHERS + modern_ciphers)}",
        "-o", f"MACs={','.join(LEGACY_MAC_ALGORITHMS + modern_macs)}",
    ]


def is_legacy_ssh_negotiation_error(error_text: str) -> bool:
    """判断是否为旧设备 SSH 算法协商失败。"""
    normalized = (error_text or "").lower()
    indicators = [
        "no matching key exchange method",
        "no matching host key type",
        "no matching cipher found",
        "no matching mac found",
        "incompatible ssh peer",
        "kexalgorithm",
        "hostkeyalgorithms",
        "pubkeyacceptedalgorithms",
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group1-sha1",
        "ssh-rsa",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_legacy_ssh_guidance(error_text: str) -> str:
    """为旧设备 SSH 协商失败生成可读提示。"""
    if not is_legacy_ssh_negotiation_error(error_text):
        return error_text

    return (
        "设备 SSH 算法较旧，平台已自动尝试兼容常见的 legacy KEX、ssh-rsa、旧 cipher 和 MAC。"
        " 如果仍然失败，通常说明该设备镜像过旧，或底层 SSH 库与设备支持集合仍无交集。"
        " 建议优先核对设备 SSH 配置、升级镜像，或临时放宽客户端算法策略后再重试。"
    )


def is_ssh_authentication_error(error_text: str) -> bool:
    """判断是否为 SSH 认证失败。"""
    normalized = (error_text or "").lower()
    indicators = [
        "authentication to device failed",
        "authentication failed",
        "all authentication methods failed",
        "auth_password",
        "permission denied",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_ssh_authentication_guidance(error_text: str) -> str:
    """为 SSH 认证失败生成可读提示。"""
    if not is_ssh_authentication_error(error_text):
        return error_text

    return (
        "设备已可达，SSH 协商也已经开始，但认证被设备拒绝。"
        " 这通常不是算法兼容问题，而是用户名或密码错误，或者设备 AAA、VTY、login local 配置不接受当前账号。"
        " 建议先用同一组账号在终端手工 SSH 登录验证，再检查设备本地用户、AAA 策略和 VTY 配置。"
    )


def is_ssh_timeout_error(error_text: str) -> bool:
    normalized = (error_text or "").lower()
    indicators = [
        "timed-out reading channel",
        "connection timed out",
        "tcp connection to device failed",
        "no existing session",
        "timed out",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_ssh_timeout_guidance(error_text: str) -> str:
    if not is_ssh_timeout_error(error_text):
        return error_text

    return (
        "设备管理端口看起来可达，但 SSH 会话在建立或读取阶段超时。"
        " 这通常意味着设备 CPU 忙、VTY/AAA 响应慢、管理平面被限速，或者中间防火墙对 SSH 流量做了会话拦截。"
        " 建议先确认设备负载、VTY 空闲会话、ACL/防火墙策略，再重试 SSH 登录。"
    )


def is_ssh_transport_error(error_text: str) -> bool:
    normalized = (error_text or "").lower()
    indicators = [
        "connection refused",
        "actively refused",
        "unable to connect",
        "network is unreachable",
        "no route to host",
        "connection reset by peer",
        "error reading ssh protocol banner",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_ssh_transport_guidance(error_text: str) -> str:
    if not is_ssh_transport_error(error_text):
        return error_text

    return (
        "设备 IP 可能可达，但 SSH 传输层没有正常建立。"
        " 常见原因是 22 端口未开放、VTY 没启用 SSH、ACL/防火墙拦截，或目标主机直接拒绝连接。"
        " 建议先核对管理端口开放状态、设备 SSH 配置和中间安全策略。"
    )


def get_ssh_error_code(error_text: str) -> str | None:
    """返回已识别的 SSH 错误分类。"""
    if is_legacy_ssh_negotiation_error(error_text):
        return LEGACY_SSH_ERROR_CODE
    if is_ssh_authentication_error(error_text):
        return SSH_AUTH_ERROR_CODE
    if is_ssh_timeout_error(error_text):
        return SSH_TIMEOUT_ERROR_CODE
    if is_ssh_transport_error(error_text):
        return SSH_TRANSPORT_ERROR_CODE
    return None


def build_ssh_error_guidance(error_text: str) -> str:
    """根据 SSH 错误类型生成统一用户提示。"""
    error_code = get_ssh_error_code(error_text)
    if error_code == LEGACY_SSH_ERROR_CODE:
        return build_legacy_ssh_guidance(error_text)
    if error_code == SSH_AUTH_ERROR_CODE:
        return build_ssh_authentication_guidance(error_text)
    if error_code == SSH_TIMEOUT_ERROR_CODE:
        return build_ssh_timeout_guidance(error_text)
    if error_code == SSH_TRANSPORT_ERROR_CODE:
        return build_ssh_transport_guidance(error_text)
    return error_text


def is_ssh_port_open(ip: str, port: int = 22, timeout: float = 1.0) -> bool:
    """快速检查设备的 SSH 端口（通常是22端口）是否处于开放/监听状态。
    
    使用轻量级 TCP socket 连接，在 1 秒内超时失败，避免 Paramiko 的超长重试阻塞。
    """
    import socket
    if not ip or ip == '0.0.0.0':
        return False
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False

