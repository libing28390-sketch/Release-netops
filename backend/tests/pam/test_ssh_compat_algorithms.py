from api.pam import get_asyncssh_compatible_algorithms
from drivers.ssh_compat import (
    LEGACY_CIPHERS,
    LEGACY_HOST_KEY_ALGORITHMS,
    LEGACY_KEX_ALGORITHMS,
    LEGACY_MAC_ALGORITHMS,
    SAFE_LEGACY_CIPHERS,
    SAFE_LEGACY_HOST_KEY_ALGORITHMS,
    SAFE_LEGACY_KEX_ALGORITHMS,
    SAFE_LEGACY_MAC_ALGORITHMS,
    build_paramiko_compatibility_kwargs,
    build_system_ssh_open_cmd,
    get_ssh_algorithm_lists,
    get_ssh_error_code,
    is_legacy_ssh_negotiation_error,
    normalize_ssh_algorithm_profile,
)


def test_asyncssh_compatible_algorithms_includes_safe_legacy_macs_and_kex():
    algs = get_asyncssh_compatible_algorithms()
    assert "mac_algs" in algs
    assert "kex_algs" in algs
    assert "encryption_algs" in algs
    assert "server_host_key_algs" in algs

    macs = algs["mac_algs"]
    for expected_mac in ["hmac-sha1", "hmac-sha2-256"]:
        assert expected_mac in macs
    for blocked_mac in ["hmac-md5", "hmac-sha1-96", "hmac-md5-96"]:
        assert blocked_mac not in macs

    kex = algs["kex_algs"]
    for expected_kex in ["diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1", "curve25519-sha256"]:
        assert expected_kex in kex
    assert "diffie-hellman-group1-sha1" not in kex

    ciphers = algs["encryption_algs"]
    for expected_cipher in ["aes128-ctr", "aes256-ctr", "aes256-cbc"]:
        assert expected_cipher in ciphers
    assert "3des-cbc" not in ciphers

    host_keys = algs["server_host_key_algs"]
    for expected_host_key in ["rsa-sha2-256", "ssh-rsa"]:
        assert expected_host_key in host_keys
    assert "ssh-dss" not in host_keys


def test_legacy_algorithm_lists_contain_full_network_device_suites():
    assert "hmac-md5" in LEGACY_MAC_ALGORITHMS
    assert "hmac-sha1-96" in LEGACY_MAC_ALGORITHMS
    assert "hmac-md5-96" in LEGACY_MAC_ALGORITHMS
    assert "ssh-dss" in LEGACY_HOST_KEY_ALGORITHMS
    assert "3des-cbc" in LEGACY_CIPHERS
    assert "diffie-hellman-group1-sha1" in LEGACY_KEX_ALGORITHMS

    cmd = build_system_ssh_open_cmd("legacy_break_glass")
    cmd_str = " ".join(cmd)
    assert "hmac-md5" in cmd_str
    assert "ssh-dss" in cmd_str
    assert "diffie-hellman-group1-sha1" in cmd_str


def test_auto_profile_keeps_modern_algorithms_first_and_blocks_weak_legacy():
    lists = get_ssh_algorithm_lists()
    assert lists["kex"][:2] == ["curve25519-sha256", "curve25519-sha256@libssh.org"]
    assert lists["kex"][-2:] == SAFE_LEGACY_KEX_ALGORITHMS
    assert lists["host_key"][-1] == SAFE_LEGACY_HOST_KEY_ALGORITHMS[0]
    assert lists["cipher"][-3:] == SAFE_LEGACY_CIPHERS
    assert lists["mac"][-2:] == SAFE_LEGACY_MAC_ALGORITHMS
    assert "diffie-hellman-group1-sha1" not in lists["kex"]
    assert "ssh-dss" not in lists["host_key"]
    assert "hmac-md5" not in lists["mac"]

    cmd = " ".join(build_system_ssh_open_cmd())
    assert "KexAlgorithms=+" in cmd
    assert "diffie-hellman-group14-sha1" in cmd
    assert "diffie-hellman-group1-sha1" not in cmd
    assert "HostKeyAlgorithms=+ssh-rsa" in cmd


def test_profile_aliases_fail_closed_to_auto():
    assert normalize_ssh_algorithm_profile(None) == "auto"
    assert normalize_ssh_algorithm_profile("strict") == "modern"
    assert normalize_ssh_algorithm_profile("legacy") == "legacy_compat"
    assert normalize_ssh_algorithm_profile("break-glass") == "legacy_break_glass"
    assert normalize_ssh_algorithm_profile("unrecognized") == "auto"


def test_system_open_cmd_can_use_the_openSSH_8_2_pubkey_option(monkeypatch):
    import drivers.ssh_compat as ssh_compat

    supported = {
        "kex": {"diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1"},
        "key": {"ssh-rsa"},
        "cipher": {"aes128-cbc", "aes192-cbc", "aes256-cbc"},
        "mac": {"hmac-sha1"},
    }
    monkeypatch.setattr(
        ssh_compat,
        "_system_ssh_algorithms",
        lambda query: supported.get(query, set()),
    )
    monkeypatch.setattr(
        ssh_compat,
        "_system_pubkey_accepted_option",
        lambda: "PubkeyAcceptedKeyTypes",
    )

    command = " ".join(ssh_compat.build_system_ssh_open_cmd())
    assert "PubkeyAcceptedKeyTypes=+ssh-rsa" in command
    assert "PubkeyAcceptedAlgorithms=" not in command


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
    disabled = kwargs.get("disabled_algorithms")
    assert "diffie-hellman-group1-sha1" in disabled["kex"]
    assert "ssh-dss" in disabled["keys"]
    assert "hmac-md5" in disabled["macs"]
    assert kwargs.get("disable_sha2_fix") is False
    expanded = build_netmiko_compatibility_kwargs(180)
    assert expanded.get("banner_timeout") == 180
    assert expanded.get("session_timeout") == 180

    break_glass = build_netmiko_compatibility_kwargs(profile="legacy_break_glass")
    assert break_glass.get("disabled_algorithms") == {}


def test_paramiko_options_share_the_same_profile_policy():
    options = build_paramiko_compatibility_kwargs()
    assert options["look_for_keys"] is False
    assert options["allow_agent"] is False
    assert "diffie-hellman-group1-sha1" in options["disabled_algorithms"]["kex"]
    assert "ssh-dss" in options["disabled_algorithms"]["keys"]

    break_glass = build_paramiko_compatibility_kwargs("legacy_break_glass")
    assert break_glass["disabled_algorithms"] == {}


def test_paramiko_auto_profile_intersects_captured_old_device_offers():
    import socket

    import paramiko

    client_socket, peer_socket = socket.socketpair()
    transport = paramiko.Transport(
        client_socket,
        disabled_algorithms=build_paramiko_compatibility_kwargs()[
            "disabled_algorithms"
        ],
    )
    try:
        assert set(transport.preferred_kex) & {
            "diffie-hellman-group-exchange-sha1",
            "diffie-hellman-group14-sha1",
        }
        assert "ssh-rsa" in transport.preferred_keys
        assert {"aes128-ctr", "aes256-ctr"} & set(transport.preferred_ciphers)
        assert "aes128-cbc" in transport.preferred_ciphers
        assert "hmac-sha1" in transport.preferred_macs
        assert "diffie-hellman-group1-sha1" not in transport.preferred_kex
    finally:
        transport.close()
        peer_socket.close()


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

