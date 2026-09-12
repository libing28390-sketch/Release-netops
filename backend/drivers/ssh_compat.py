import re
import shutil
import subprocess
import time
from functools import lru_cache
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
    "ssh-dss",
]

LEGACY_CIPHERS: List[str] = [
    "aes128-ctr",
    "aes192-ctr",
    "aes256-ctr",
    "aes128-cbc",
    "aes192-cbc",
    "aes256-cbc",
    "3des-cbc",
    "blowfish-cbc",
    "cast128-cbc",
    "arcfour256",
    "arcfour128",
    "arcfour",
]

LEGACY_MAC_ALGORITHMS: List[str] = [
    "hmac-sha2-256-etm@openssh.com",
    "hmac-sha2-512-etm@openssh.com",
    "hmac-sha1-etm@openssh.com",
    "hmac-md5-etm@openssh.com",
    "hmac-sha2-256",
    "hmac-sha2-512",
    "hmac-sha1",
    "hmac-md5",
    "hmac-sha1-96",
    "hmac-md5-96",
]

# Algorithm names are transport capabilities, not vendor capabilities.  Keep
# the policy here so Netmiko, Scrapli and AsyncSSH do not grow separate
# vendor-specific legacy branches.
MODERN_KEX_ALGORITHMS: List[str] = [
    "curve25519-sha256",
    "curve25519-sha256@libssh.org",
    "ecdh-sha2-nistp256",
    "ecdh-sha2-nistp384",
    "ecdh-sha2-nistp521",
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group16-sha512",
    "diffie-hellman-group18-sha512",
    "diffie-hellman-group14-sha256",
]

MODERN_HOST_KEY_ALGORITHMS: List[str] = [
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
]

MODERN_CIPHERS: List[str] = [
    "chacha20-poly1305@openssh.com",
    "aes128-gcm@openssh.com",
    "aes256-gcm@openssh.com",
    "aes128-ctr",
    "aes192-ctr",
    "aes256-ctr",
]

MODERN_MAC_ALGORITHMS: List[str] = [
    "umac-128-etm@openssh.com",
    "umac-64-etm@openssh.com",
    "hmac-sha2-256-etm@openssh.com",
    "hmac-sha2-512-etm@openssh.com",
    "hmac-sha2-256",
    "hmac-sha2-512",
]

# These are the minimum legacy algorithms needed by the devices in the
# supplied capture and by many older Cisco/Huawei/H3C/Juniper releases.  They
# remain available in the normal ``auto`` profile, but are appended after the
# modern defaults for system OpenSSH and are not used to disable modern
# choices.
SAFE_LEGACY_KEX_ALGORITHMS: List[str] = [
    "diffie-hellman-group14-sha1",
    "diffie-hellman-group-exchange-sha1",
]
SAFE_LEGACY_HOST_KEY_ALGORITHMS: List[str] = ["ssh-rsa"]
SAFE_LEGACY_CIPHERS: List[str] = [
    "aes128-cbc",
    "aes192-cbc",
    "aes256-cbc",
]
SAFE_LEGACY_MAC_ALGORITHMS: List[str] = [
    "hmac-sha1-etm@openssh.com",
    "hmac-sha1",
]

# Algorithms below this line are only enabled by the explicit
# ``legacy_break_glass`` profile.  In particular, group1 is a 1024-bit DH
# group, ssh-dss is obsolete DSA/SHA-1, and MD5/RC4/DES/Blowfish/CBC-3DES are
# not acceptable defaults for a management plane.
SSH_ALGORITHM_PROFILE_AUTO = "auto"
SSH_ALGORITHM_PROFILE_MODERN = "modern"
SSH_ALGORITHM_PROFILE_LEGACY = "legacy_compat"
SSH_ALGORITHM_PROFILE_BREAK_GLASS = "legacy_break_glass"


def normalize_ssh_algorithm_profile(profile: object = None) -> str:
    """Normalize a device's optional SSH algorithm profile.

    Unknown or missing values fail closed to ``auto``.  The profile is kept
    independent of vendor/platform so the same policy works for Cisco,
    Huawei, H3C, Ruijie, Juniper and other network drivers.
    """

    value = str(profile or "").strip().lower().replace("-", "_")
    aliases = {
        "": SSH_ALGORITHM_PROFILE_AUTO,
        "default": SSH_ALGORITHM_PROFILE_AUTO,
        "auto": SSH_ALGORITHM_PROFILE_AUTO,
        "modern": SSH_ALGORITHM_PROFILE_MODERN,
        "strict": SSH_ALGORITHM_PROFILE_MODERN,
        "legacy": SSH_ALGORITHM_PROFILE_LEGACY,
        "compat": SSH_ALGORITHM_PROFILE_LEGACY,
        "legacy_compat": SSH_ALGORITHM_PROFILE_LEGACY,
        "break_glass": SSH_ALGORITHM_PROFILE_BREAK_GLASS,
        "legacy_all": SSH_ALGORITHM_PROFILE_BREAK_GLASS,
        "legacy_break_glass": SSH_ALGORITHM_PROFILE_BREAK_GLASS,
    }
    return aliases.get(value, SSH_ALGORITHM_PROFILE_AUTO)


def _dedupe(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def get_ssh_algorithm_lists(profile: object = None) -> Dict[str, List[str]]:
    """Return ordered algorithm proposals for a transport profile.

    ``auto`` is modern-first plus the safe legacy subset required by the
    attached captures.  ``legacy_break_glass`` adds every legacy name already
    understood by the project for devices that have no safer common option.
    """

    normalized = normalize_ssh_algorithm_profile(profile)
    lists = {
        "kex": list(MODERN_KEX_ALGORITHMS),
        "host_key": list(MODERN_HOST_KEY_ALGORITHMS),
        "cipher": list(MODERN_CIPHERS),
        "mac": list(MODERN_MAC_ALGORITHMS),
    }
    if normalized in {SSH_ALGORITHM_PROFILE_AUTO, SSH_ALGORITHM_PROFILE_LEGACY}:
        lists["kex"] = _dedupe(lists["kex"] + SAFE_LEGACY_KEX_ALGORITHMS)
        lists["host_key"] = _dedupe(lists["host_key"] + SAFE_LEGACY_HOST_KEY_ALGORITHMS)
        lists["cipher"] = _dedupe(lists["cipher"] + SAFE_LEGACY_CIPHERS)
        lists["mac"] = _dedupe(lists["mac"] + SAFE_LEGACY_MAC_ALGORITHMS)
    elif normalized == SSH_ALGORITHM_PROFILE_BREAK_GLASS:
        lists["kex"] = _dedupe(lists["kex"] + LEGACY_KEX_ALGORITHMS)
        lists["host_key"] = _dedupe(lists["host_key"] + LEGACY_HOST_KEY_ALGORITHMS)
        lists["cipher"] = _dedupe(lists["cipher"] + LEGACY_CIPHERS)
        lists["mac"] = _dedupe(lists["mac"] + LEGACY_MAC_ALGORITHMS)
    return lists


def filter_ssh_algorithm_names(
    values: object,
    category: str,
    profile: object = None,
) -> List[str]:
    """Filter a library's available names against the selected profile."""

    if not values:
        return []
    key = {
        "kex": "kex",
        "host": "host_key",
        "host_key": "host_key",
        "server_host_key": "host_key",
        "cipher": "cipher",
        "encryption": "cipher",
        "mac": "mac",
    }.get(str(category).strip().lower())
    if key is None:
        return []
    allowed = set(get_ssh_algorithm_lists(profile)[key])
    result: List[str] = []
    for value in values:  # type: ignore[union-attr]
        name = value.decode("ascii") if isinstance(value, bytes) else str(value)
        if name in allowed:
            result.append(name)
            continue
        # AsyncSSH/OpenSSH may expose certificate variants alongside the base
        # host-key algorithm.  A profile allowing the base key also allows its
        # certificate form; this does not enable ssh-dss unless explicitly
        # present in the break-glass profile.
        base = name.split("-cert-v01@", 1)[0] if "-cert-v01@" in name else name
        if base in allowed:
            result.append(name)
    return result


def _disabled_algorithms_for_profile(profile: object = None) -> Dict[str, List[str]]:
    """Build Paramiko's per-category deny list for the selected profile."""

    normalized = normalize_ssh_algorithm_profile(profile)
    if normalized == SSH_ALGORITHM_PROFILE_BREAK_GLASS:
        return {}

    allowed = get_ssh_algorithm_lists(normalized)
    legacy_by_category = {
        "kex": LEGACY_KEX_ALGORITHMS,
        "keys": LEGACY_HOST_KEY_ALGORITHMS,
        "ciphers": LEGACY_CIPHERS,
        "macs": LEGACY_MAC_ALGORITHMS,
    }
    category_to_profile_key = {
        "kex": "kex",
        "keys": "host_key",
        "ciphers": "cipher",
        "macs": "mac",
    }
    disabled: Dict[str, List[str]] = {}
    for category, candidates in legacy_by_category.items():
        profile_key = category_to_profile_key[category]
        values = [name for name in candidates if name not in set(allowed[profile_key])]
        if values:
            disabled[category] = _dedupe(values)

    # ``pubkeys`` controls client user-auth signatures rather than the server
    # host key list.  Keep rsa-sha1 out of strict mode while leaving password
    # authentication unaffected in the normal auto profile.
    if normalized == SSH_ALGORITHM_PROFILE_MODERN:
        disabled["pubkeys"] = ["ssh-rsa"]
    return disabled

LEGACY_SSH_ERROR_CODE = "legacy_ssh_algorithms"
SSH_AUTH_ERROR_CODE = "ssh_authentication_failed"
SSH_TIMEOUT_ERROR_CODE = "ssh_transport_timeout"
SSH_TRANSPORT_ERROR_CODE = "ssh_transport_unreachable"
SSH_HOST_KEY_ERROR_CODE = "ssh_host_key_untrusted"

# Netmiko/Paramiko use separate timers for TCP connect, SSH banner, auth,
# channel blocking, and the established session. Keep the transport stages
# aligned instead of extending only conn_timeout.
DEFAULT_SSH_TIMEOUT_SECONDS = 60
DEFAULT_SSH_SESSION_TIMEOUT_SECONDS = 120

PAGING_PROMPT_RE = re.compile(
    r"(?:----\s*More\s*----|--\s*More\s*--|--More--|<---\s*More\s*--->|Press\s+any\s+key\s+to\s+continue)",
    re.IGNORECASE,
)


def ensure_netmiko_custom_platforms() -> None:
    """Register custom Nexora platform keys in Netmiko's SSH dispatcher."""
    try:
        from netmiko import ssh_dispatcher as sd
        g = getattr(sd, '__globals__', None)
        if isinstance(g, dict):
            mapper = g.get('CLASS_MAPPER')
            mapper_base = g.get('CLASS_MAPPER_BASE')
            platforms = g.get('platforms')
            cisco_cls = g.get('CiscoIosSSH')
            
            if mapper is not None and cisco_cls:
                mapper['dptech_ios'] = cisco_cls
                mapper['dptech_conplat'] = cisco_cls
                mapper['dptech_conplat_fw'] = cisco_cls
                mapper['raisecom_ros'] = cisco_cls
            if mapper_base is not None and cisco_cls:
                mapper_base['dptech_ios'] = cisco_cls
                mapper_base['dptech_conplat'] = cisco_cls
                mapper_base['dptech_conplat_fw'] = cisco_cls
                mapper_base['raisecom_ros'] = cisco_cls
            if isinstance(platforms, list):
                for p_key in ('dptech_ios', 'dptech_conplat', 'dptech_conplat_fw', 'raisecom_ros'):
                    if p_key not in platforms:
                        platforms.append(p_key)
            if 'platforms_str' in g:
                for p_key in ('dptech_ios', 'dptech_conplat', 'dptech_conplat_fw', 'raisecom_ros'):
                    if p_key not in g['platforms_str']:
                        g['platforms_str'] += f"\n{p_key}"
    except Exception:
        pass

ensure_netmiko_custom_platforms()


def build_paramiko_compatibility_kwargs(profile: object = None) -> Dict[str, Any]:
    """Return safe Paramiko options for direct and Scrapli Paramiko opens."""

    return {
        "look_for_keys": False,
        "allow_agent": False,
        "disabled_algorithms": _disabled_algorithms_for_profile(profile),
    }


def build_netmiko_compatibility_kwargs(
    timeout: int | float | None = None,
    profile: object = None,
) -> Dict[str, Any]:
    """
    Netmiko/Paramiko 兼容老设备的连接参数。

    - ``disabled_algorithms`` 按 profile 保留附件所需的安全 legacy 子集，
      同时默认阻止 group1/ssh-dss/MD5/RC4 等高风险算法
    - use_keys/allow_agent 关闭本地 SSH agent 干扰
    - 不关闭 Netmiko 的 SHA-2 兼容修复，避免现代 RSA-SHA2 设备被全局降级
    - conn/banner/auth/blocking: 使用一致的 60 秒预算，避免只放宽 TCP
      连接却在 SSH Banner 或 channel 阶段仍按 Netmiko 短默认值失败
    - session_timeout: 给慢速设备保留更长的已建立会话生命周期
    """
    ensure_netmiko_custom_platforms()
    normalized_profile = normalize_ssh_algorithm_profile(profile)
    try:
        requested_timeout = int(float(timeout)) if timeout is not None else DEFAULT_SSH_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        requested_timeout = DEFAULT_SSH_TIMEOUT_SECONDS
    transport_timeout = max(DEFAULT_SSH_TIMEOUT_SECONDS, requested_timeout)
    return {
        "disabled_algorithms": _disabled_algorithms_for_profile(normalized_profile),
        "use_keys": False,
        "allow_agent": False,
        "disable_sha2_fix": False,
        "conn_timeout": transport_timeout,
        "banner_timeout": transport_timeout,
        "auth_timeout": transport_timeout,
        "blocking_timeout": transport_timeout,
        "session_timeout": max(DEFAULT_SSH_SESSION_TIMEOUT_SECONDS, transport_timeout),
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
    paging_pattern = r"(?:----\s*More\s*----|--\s*More\s*--|--More--|<---\s*More\s*--->|Press\s+any\s+key\s+to\s+continue)"
    
    for _ in range(max_pages):
        if not pending:
            break
        try:
            conn.write_channel(" ")
            if hasattr(conn, 'read_until_prompt_or_pattern'):
                chunk = conn.read_until_prompt_or_pattern(pattern=paging_pattern, read_timeout=2.0)
            else:
                chunk = conn.read_channel_timing(read_timeout=2.0)
        except AttributeError:
            break
        except Exception:
            chunk = ""
        if not chunk:
            break
        pending = contains_paging_prompt(chunk)
        collected += PAGING_PROMPT_RE.sub("", chunk)

    # Clean prompt erasure whitespace lines (leftover from erasing the paging prompt)
    clean_lines = []
    for line in collected.splitlines():
        if line and not line.strip():
            continue
        line = line.replace('\r', '')
        clean_lines.append(line)
        
    return '\n'.join(clean_lines)


@lru_cache(maxsize=8)
def _system_ssh_algorithms(query: str) -> set[str] | None:
    """Return algorithms implemented by the local OpenSSH, when available."""

    ssh_path = shutil.which("ssh")
    if not ssh_path:
        return None
    try:
        result = subprocess.run(
            [ssh_path, "-Q", query],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return values or None


def _filter_system_ssh_algorithms(query: str, values: List[str]) -> List[str]:
    available = _system_ssh_algorithms(query)
    if available is None:
        return _dedupe(values)
    return _dedupe([value for value in values if value in available])


@lru_cache(maxsize=1)
def _system_pubkey_accepted_option() -> str | None:
    """Pick the public-key option name supported by the local OpenSSH.

    OpenSSH 8.2 (used by the supplied capture) calls this option
    ``PubkeyAcceptedKeyTypes``; newer releases prefer
    ``PubkeyAcceptedAlgorithms`` but retain the former alias.  Probe with
    ``ssh -G`` so the generated Scrapli command is accepted on both families.
    """

    ssh_path = shutil.which("ssh")
    if not ssh_path:
        return None
    for option in ("PubkeyAcceptedAlgorithms", "PubkeyAcceptedKeyTypes"):
        try:
            result = subprocess.run(
                [ssh_path, "-G", "127.0.0.1", "-o", f"{option}=+ssh-rsa"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            return option
    return None


def build_system_ssh_open_cmd(profile: object = None) -> List[str]:
    """为 OpenSSH/system transport 生成兼容老设备的额外参数。
    
    使用 ``+`` 追加 legacy 算法，保留现代 OpenSSH 默认优先级；只在
    ``legacy_break_glass`` 档案中附加 group1/ssh-dss/MD5/RC4 等高风险算法。
    """
    normalized_profile = normalize_ssh_algorithm_profile(profile)
    if normalized_profile == SSH_ALGORITHM_PROFILE_MODERN:
        return []

    lists = get_ssh_algorithm_lists(normalized_profile)
    modern = get_ssh_algorithm_lists(SSH_ALGORITHM_PROFILE_MODERN)
    legacy_only = {
        key: [name for name in values if name not in set(modern[key])]
        for key, values in lists.items()
    }
    candidates = {
        "kex": _filter_system_ssh_algorithms("kex", legacy_only["kex"]),
        "host_key": _filter_system_ssh_algorithms("key", legacy_only["host_key"]),
        "cipher": _filter_system_ssh_algorithms("cipher", legacy_only["cipher"]),
        "mac": _filter_system_ssh_algorithms("mac", legacy_only["mac"]),
    }
    options = [
        ("KexAlgorithms", candidates["kex"]),
        ("HostKeyAlgorithms", candidates["host_key"]),
        ("Ciphers", candidates["cipher"]),
        ("MACs", candidates["mac"]),
    ]
    pubkey_option = _system_pubkey_accepted_option()
    if pubkey_option:
        options.insert(2, (pubkey_option, candidates["host_key"]))
    command: List[str] = []
    for option, values in options:
        if values:
            command.extend(["-o", f"{option}=+{','.join(values)}"])
    return command


def is_legacy_ssh_negotiation_error(error_text: str) -> bool:
    """判断是否为旧设备 SSH 算法协商失败。"""
    normalized = (error_text or "").lower()
    indicators = [
        "no matching key exchange method",
        "no matching host key type",
        "no matching cipher found",
        "no matching mac found",
        "no matching mac algorithm found",
        "incompatible ssh peer",
        "kexalgorithm",
        "hostkeyalgorithms",
        "pubkeyacceptedalgorithms",
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group1-sha1",
        "ssh-rsa",
        "ssh-dss",
        "hmac-md5",
        "hmac-sha1",
        "hmac-sha1-96",
        "hmac-md5-96",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_legacy_ssh_guidance(error_text: str) -> str:
    """为旧设备 SSH 协商失败生成可读提示。"""
    if not is_legacy_ssh_negotiation_error(error_text):
        return error_text

    return "SSH 算法不匹配。建议检查设备 SSH 服务版本或平台驱动类型。"


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

    return "凭据被拒绝。建议检查：1. 绑定的登录用户名与密码；2. 设备 AAA 与 Enable 特权密码。"


def is_ssh_timeout_error(error_text: str) -> bool:
    normalized = (error_text or "").lower()
    indicators = [
        "timed-out reading channel",
        "connection timed out",
        "tcp connection to device failed",
        "no existing session",
        "timed out",
        "timeout",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_ssh_timeout_guidance(error_text: str) -> str:
    if not is_ssh_timeout_error(error_text):
        return error_text

    return "SSH 响应超时。建议检查：1. IP/端口是否通畅；2. 设备负载与 VTY 线路空闲状态。"


def is_ssh_transport_error(error_text: str) -> bool:
    normalized = (error_text or "").lower()
    indicators = [
        "connection refused",
        "actively refused",
        "unable to connect",
        "network is unreachable",
        "no route to host",
        "connection reset by peer",
        "connection reset",
        "connection lost",
        "connection closed",
        "closed by remote host",
        "error reading ssh protocol banner",
        "broken pipe",
    ]
    return any(indicator in normalized for indicator in indicators)


def build_ssh_transport_guidance(error_text: str, port: int | str = 22) -> str:
    if not is_ssh_transport_error(error_text):
        return error_text

    port_str = f"{port} 端口" if port else "SSH 端口"
    return f"连接失败或被拒绝。建议检查：1. 目标 IP 与 {port_str}；2. 设备 VTY 是否启用 SSH 及防火墙策略。"


def is_ssh_host_key_error(error_text: str) -> bool:
    """Return whether an SSH failure is caused by host-key trust validation."""
    normalized = (error_text or "").lower()
    indicators = (
        "host key is not trusted",
        "host key is not known",
        "host key mismatch",
        "host key has changed",
        "hostkeynotverifiable",
        "known_hosts",
        "known hosts",
    )
    return any(indicator in normalized for indicator in indicators)


def build_ssh_host_key_guidance(error_text: str) -> str:
    """Build safe guidance for an untrusted or changed SSH host key."""
    if not is_ssh_host_key_error(error_text):
        return error_text

    return (
        "SSH 主机密钥未登记或指纹不符。请核对设备的 SHA256 主机密钥指纹，不要关闭 Host Key 校验。"
    )


def get_ssh_error_code(error_text: str) -> str | None:
    """返回已识别的 SSH 错误分类。"""
    if is_ssh_host_key_error(error_text):
        return SSH_HOST_KEY_ERROR_CODE
    if is_legacy_ssh_negotiation_error(error_text):
        return LEGACY_SSH_ERROR_CODE
    if is_ssh_authentication_error(error_text):
        return SSH_AUTH_ERROR_CODE
    if is_ssh_timeout_error(error_text):
        return SSH_TIMEOUT_ERROR_CODE
    if is_ssh_transport_error(error_text):
        return SSH_TRANSPORT_ERROR_CODE
    return None


def build_ssh_error_guidance(error_text: str, port: int | str = 22) -> str:
    """根据 SSH 错误类型生成统一用户提示。"""
    error_code = get_ssh_error_code(error_text)
    if error_code == LEGACY_SSH_ERROR_CODE:
        return build_legacy_ssh_guidance(error_text)
    if error_code == SSH_AUTH_ERROR_CODE:
        return build_ssh_authentication_guidance(error_text)
    if error_code == SSH_TIMEOUT_ERROR_CODE:
        return build_ssh_timeout_guidance(error_text)
    if error_code == SSH_TRANSPORT_ERROR_CODE:
        return build_ssh_transport_guidance(error_text, port=port)
    if error_code == SSH_HOST_KEY_ERROR_CODE:
        return build_ssh_host_key_guidance(error_text)
    return error_text


def diagnose_ssh_failure(error_text: str, ip: str = "", port: int | str = 22) -> tuple[str, str]:
    """根据具体报错日志智能分析根因，返回 (分类短原因, 精准排查建议)。"""
    raw = str(error_text or "").strip()
    low = raw.lower()
    ip_str = str(ip or "").strip()
    port_str = f"{port} 端口" if port else "SSH 端口"

    # 1. 检查 IP 地址格式是否非法 / DNS 解析失败
    if ip_str:
        import ipaddress
        parts = ip_str.split('.')
        is_numeric_like = len(parts) == 4 and all(part.isdigit() for part in parts)
        if is_numeric_like:
            try:
                ipaddress.ip_address(ip_str)
            except ValueError:
                return "IP地址无效", f"IP 格式错误（'{ip_str}' 不是有效 IPv4 地址，每段数值须在 0-255），请修正资产 IP。"

    if any(m in low for m in ["getaddrinfo failed", "nodename nor servname", "name or service not known", "11001", "gaierror"]):
        target = f"'{ip_str}'" if ip_str else "目标主机"
        return "地址解析失败", f"{target} 无法解析或格式不合法，请核对资产 IP 地址。"

    # 2. SSH 算法协商失败（Legacy Algorithm Mismatch）
    if is_legacy_ssh_negotiation_error(raw):
        if "no matching mac" in low or "mac algorithm" in low:
            return "MAC算法不兼容", "设备支持的 MAC 算法与客户端无交集，请检查设备 SSH 配置。"
        if "no matching cipher" in low or "cipher" in low:
            return "加密算法不兼容", "设备加密算法（Cipher）不匹配，请检查设备 SSH 加密配置。"
        if "no matching key exchange" in low or "kex" in low:
            return "KEX算法不兼容", "密钥交换算法（KEX）协商失败，请检查设备 SSH 协议版本。"
        return "SSH算法不兼容", "设备 SSH 算法过旧或与客户端无交集，建议检查设备 SSH 服务或平台类型。"

    # 3. 认证失败 / 凭据错误
    if is_ssh_authentication_error(raw):
        if "permission denied" in low:
            return "权限不足", "登录成功但权限不足以读取配置，或密码被拒绝。"
        return "认证失败", "用户名或密码被拒绝，请检查绑定的 SSH 凭据与 Enable 特权密码。"

    # 4. 主机密钥未受信 / 变更
    if is_ssh_host_key_error(raw):
        return "主机密钥未受信", "SSH 主机密钥未登记或指纹不符。请核对设备的 SHA256 指纹，不要关闭 Host Key 校验。"

    # 5. 连接被拒绝（Connection Refused）
    if any(m in low for m in ["connection refused", "actively refused", "10061", "errno 111", "wsaeconnrefused"]):
        return "连接被拒绝", f"目标端口拒绝连接。请检查设备 {port_str} 是否开放，以及 VTY 是否启用 SSH。"

    # 6. 网络不可达 / 路由不可达 / 主机下线
    if any(m in low for m in ["no route to host", "network is unreachable", "host unreachable", "10065", "errno 113", "wsaehostunreach"]):
        return "网络不可达", "无法路由到目标设备。请检查管理网络链路、路由及网关配置。"

    # 7. Prompt 提示符未识别 / 超时
    if any(m in low for m in ["pattern not detected", "unable to find prompt", "prompt not found", "search_pattern"]):
        return "提示符未识别", "已连接但未能识别命令行提示符。请检查平台驱动是否匹配，或确认分页是否关闭。"

    # 8. 特权提权失败
    if any(m in low for m in ["enable failed", "unable to enter enable", "bad enable password"]):
        return "特权提权失败", "进入特权模式失败，请核对设备凭据中的 Enable 密码。"

    # 9. TCP 握手超时 / 会话超时
    if is_ssh_timeout_error(raw):
        if "timed-out reading channel" in low:
            return "读取响应超时", "发送备份命令后未在超时时间内收到回包，请检查设备负载或命令执行耗时。"
        return "连接超时", f"TCP 连接建立超时。请检查网络丢包延迟，或确认防火墙是否放行 {port_str}。"

    # 10. CLI 命令报错
    if any(m in low for m in ["% invalid input", "% permission denied", "syntax error", "unrecognized command"]):
        return "命令执行报错", "设备不支持当前下发的备份命令或权限不足，请核对平台类型与驱动。"

    # 兜底
    return "无法获取配置", f"连接异常：{raw[:80]}" if raw and raw != 'Unknown error' else "无法建立 SSH 连接或获取到有效配置。"


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


# Monkeypatch Netmiko's BaseConnection.send_command globally to automatically
# intercept and drain paging output. This is crucial for low-privilege accounts
# (such as standard user/user read-only accounts) that are denied permission
# to execute paging disable commands (e.g. `screen-length disable`).
try:
    from netmiko.base_connection import BaseConnection

    _orig_send_command = BaseConnection.send_command

    def _patched_send_command(self, command_string: str, *args, **kwargs) -> str:
        # If the user explicitly provided expect_string, we honor it.
        # Otherwise, we construct a paging-aware expect_string regex matching
        # both the device prompt and standard pagination indicators.
        expect_string = kwargs.get('expect_string')
        if not expect_string:
            try:
                prompt = self.find_prompt()
                if prompt:
                    kwargs['expect_string'] = r'({}|----\s*More\s*----|--\s*More\s*--|--More--|<---\s*More\s*--->|Press\s+any\s+key\s+to\s+continue)'.format(re.escape(prompt))
            except Exception:
                pass

        output = _orig_send_command(self, command_string, *args, **kwargs)
        if isinstance(output, str):
            output = drain_paged_output(self, output, read_timeout=kwargs.get('read_timeout', 30))
        return output

    BaseConnection.send_command = _patched_send_command

except ImportError:
    pass
