from api.pam import get_asyncssh_compatible_algorithms
from drivers.ssh_compat import (
    LEGACY_CIPHERS,
    LEGACY_HOST_KEY_ALGORITHMS,
    LEGACY_KEX_ALGORITHMS,
    LEGACY_MAC_ALGORITHMS,
    build_system_ssh_open_cmd,
    get_ssh_error_code,
    is_legacy_ssh_negotiation_error,
)


def test_asyncssh_compatible_algorithms_includes_all_macs_and_kex():
    algs = get_asyncssh_compatible_algorithms()
    assert "mac_algs" in algs
    assert "kex_algs" in algs
    assert "encryption_algs" in algs
    assert "server_host_key_algs" in algs

    macs = algs["mac_algs"]
    for expected_mac in ["hmac-md5", "hmac-sha1", "hmac-sha1-96", "hmac-md5-96", "hmac-sha2-256"]:
        assert expected_mac in macs

    kex = algs["kex_algs"]
    for expected_kex in ["diffie-hellman-group14-sha1", "diffie-hellman-group1-sha1", "curve25519-sha256"]:
        assert expected_kex in kex

    ciphers = algs["encryption_algs"]
    for expected_cipher in ["aes128-ctr", "aes256-ctr", "aes256-cbc", "3des-cbc"]:
        assert expected_cipher in ciphers

    host_keys = algs["server_host_key_algs"]
    for expected_host_key in ["rsa-sha2-256", "ssh-rsa", "ssh-dss"]:
        assert expected_host_key in host_keys


def test_legacy_algorithm_lists_contain_full_network_device_suites():
    assert "hmac-md5" in LEGACY_MAC_ALGORITHMS
    assert "hmac-sha1-96" in LEGACY_MAC_ALGORITHMS
    assert "hmac-md5-96" in LEGACY_MAC_ALGORITHMS
    assert "ssh-dss" in LEGACY_HOST_KEY_ALGORITHMS
    assert "3des-cbc" in LEGACY_CIPHERS
    assert "diffie-hellman-group1-sha1" in LEGACY_KEX_ALGORITHMS

    cmd = build_system_ssh_open_cmd()
    cmd_str = " ".join(cmd)
    assert "hmac-md5" in cmd_str
    assert "ssh-dss" in cmd_str
    assert "diffie-hellman-group1-sha1" in cmd_str


def test_legacy_mac_error_recognition():
    raw_error = "No matching MAC algorithm found, sent hmac-sha2-256-etm@openssh.com and received hmac-md5,hmac-sha1,hmac-sha1-96,hmac-md5-96"
    assert is_legacy_ssh_negotiation_error(raw_error) is True
    assert get_ssh_error_code(raw_error) == "legacy_ssh_algorithms"


def test_netmiko_compatibility_kwargs_timeout():
    from drivers.ssh_compat import build_netmiko_compatibility_kwargs
    kwargs = build_netmiko_compatibility_kwargs()
    assert kwargs.get("conn_timeout") == 60
    assert kwargs.get("banner_timeout") == 60
    assert kwargs.get("auth_timeout") == 60
    assert kwargs.get("blocking_timeout") == 60
    assert kwargs.get("session_timeout") == 120
    assert kwargs.get("disabled_algorithms") == {}
    expanded = build_netmiko_compatibility_kwargs(180)
    assert expanded.get("banner_timeout") == 180
    assert expanded.get("session_timeout") == 180


def test_diagnose_ssh_failure_scenarios():
    from drivers.ssh_compat import diagnose_ssh_failure

    # 1. Invalid IP
    reason, detail = diagnose_ssh_failure("TCP connection to device failed", ip="1921.68.2.201")
    assert reason == "IP地址无效"
    assert "1921.68.2.201" in detail

    # 2. Connection refused
    reason, detail = diagnose_ssh_failure("Connection refused [Errno 111]", ip="192.168.2.201")
    assert reason == "连接被拒绝"
    assert "22" in detail

    # 3. Auth failed
    reason, detail = diagnose_ssh_failure("Authentication to device failed", ip="192.168.2.201")
    assert reason == "认证失败"
    assert "用户名或密码" in detail

    # 4. Pattern not detected / prompt issue
    reason, detail = diagnose_ssh_failure("Pattern not detected in output: foo#", ip="192.168.2.201")
    assert reason == "提示符未识别"

    # 5. Legacy MAC algorithm
    reason, detail = diagnose_ssh_failure("No matching MAC algorithm found", ip="192.168.2.201")
    assert reason == "MAC算法不兼容"

    # 6. Read timeout
    reason, detail = diagnose_ssh_failure("Timed-out reading channel", ip="192.168.2.201")
    assert reason == "读取响应超时"

    # 7. Custom port timeout & refused
    reason, detail = diagnose_ssh_failure("TCP connection timeout", ip="192.168.2.201", port=2222)
    assert reason == "连接超时"
    assert "2222 端口" in detail

    reason, detail = diagnose_ssh_failure("Connection refused [Errno 111]", ip="192.168.2.201", port=8022)
    assert reason == "连接被拒绝"
    assert "8022 端口" in detail

