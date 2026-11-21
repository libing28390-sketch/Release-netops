import pytest

from api.pam import get_asyncssh_compatible_algorithms
from drivers.ssh_compat import (
    LEGACY_CIPHERS,
    LEGACY_HOST_KEY_ALGORITHMS,
    LEGACY_KEX_ALGORITHMS,
    LEGACY_MAC_ALGORITHMS,
    filter_ssh_algorithm_names,
    build_paramiko_compatibility_kwargs,
    build_system_ssh_open_cmd,
    get_ssh_algorithm_lists,
    get_ssh_error_code,
    is_legacy_ssh_negotiation_error,
    normalize_ssh_algorithm_profile,
)


def test_asyncssh_compatible_algorithms_includes_full_legacy_macs_and_kex():
    algs = get_asyncssh_compatible_algorithms()
    assert "mac_algs" in algs
    assert "kex_algs" in algs
    assert "encryption_algs" in algs
    assert "server_host_key_algs" in algs

    macs = algs["mac_algs"]
    for expected_mac in ["hmac-sha1", "hmac-sha2-256"]:
        assert expected_mac in macs
    for legacy_mac in ["hmac-md5", "hmac-sha1-96", "hmac-md5-96"]:
        assert legacy_mac in macs

    kex = algs["kex_algs"]
    for expected_kex in ["diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1", "curve25519-sha256"]:
        assert expected_kex in kex
    assert "diffie-hellman-group1-sha1" in kex
    assert kex.index("curve25519-sha256") < kex.index("diffie-hellman-group1-sha1")

    ciphers = algs["encryption_algs"]
    for expected_cipher in ["aes128-ctr", "aes256-ctr", "aes256-cbc"]:
        assert expected_cipher in ciphers
    assert "3des-cbc" in ciphers

    host_keys = algs["server_host_key_algs"]
    for expected_host_key in ["rsa-sha2-256", "ssh-rsa"]:
        assert expected_host_key in host_keys
    assert "ssh-dss" in host_keys


def test_legacy_algorithm_lists_contain_full_network_device_suites():
    assert "hmac-md5" in LEGACY_MAC_ALGORITHMS
    assert "hmac-sha1-96" in LEGACY_MAC_ALGORITHMS
    assert "hmac-md5-96" in LEGACY_MAC_ALGORITHMS
    assert "ssh-dss" in LEGACY_HOST_KEY_ALGORITHMS
    assert "3des-cbc" in LEGACY_CIPHERS
    assert "diffie-hellman-group1-sha1" in LEGACY_KEX_ALGORITHMS


@pytest.mark.parametrize(
    ("supported_host_keys", "expected"),
    [
        ({"ssh-rsa", "ssh-dss"}, "HostKeyAlgorithms=+ssh-rsa,ssh-dss"),
        ({"ssh-rsa"}, "HostKeyAlgorithms=+ssh-rsa"),
    ],
)
def test_system_ssh_host_key_arguments_follow_local_client_capabilities(
    monkeypatch,
    supported_host_keys,
    expected,
):
    import drivers.ssh_compat as ssh_compat

    monkeypatch.setattr(
        ssh_compat,
        "_system_ssh_algorithms",
        lambda query: supported_host_keys if query == "key" else set(),
    )
    monkeypatch.setattr(ssh_compat, "_system_pubkey_accepted_option", lambda: None)

    command = " ".join(build_system_ssh_open_cmd("legacy_break_glass"))

    assert expected in command
    if "ssh-dss" not in supported_host_keys:
        assert "ssh-dss" not in command


@pytest.mark.parametrize("profile", [None, "auto", "legacy_compat", "legacy_break_glass"])
def test_compatibility_profiles_keep_modern_first_and_include_old_device_suites(profile):
    lists = get_ssh_algorithm_lists(profile)
    assert lists["kex"][:2] == ["curve25519-sha256", "curve25519-sha256@libssh.org"]
    assert set(LEGACY_KEX_ALGORITHMS) <= set(lists["kex"])
    assert set(LEGACY_HOST_KEY_ALGORITHMS) <= set(lists["host_key"])
    assert set(LEGACY_CIPHERS) <= set(lists["cipher"])
    assert set(LEGACY_MAC_ALGORITHMS) <= set(lists["mac"])

    cmd = " ".join(build_system_ssh_open_cmd(profile))
    assert "KexAlgorithms=+" in cmd
    assert "diffie-hellman-group14-sha1" in cmd
    assert "diffie-hellman-group1-sha1" in cmd
    assert "HostKeyAlgorithms=+ssh-rsa" in cmd


def test_profile_aliases_fail_closed_to_auto():
    assert normalize_ssh_algorithm_profile(None) == "auto"
    assert normalize_ssh_algorithm_profile("strict") == "modern"
    assert normalize_ssh_algorithm_profile("legacy") == "legacy_compat"
    assert normalize_ssh_algorithm_profile("break-glass") == "legacy_break_glass"
    assert normalize_ssh_algorithm_profile("unrecognized") == "auto"


def test_modern_profile_still_rejects_legacy_algorithms():
    options = build_paramiko_compatibility_kwargs("modern")["disabled_algorithms"]
    assert "diffie-hellman-group1-sha1" in options["kex"]
    assert "ssh-rsa" in options["keys"]
    assert "hmac-md5" in options["macs"]
    assert "ssh-rsa" in options["pubkeys"]
    assert build_system_ssh_open_cmd("modern") == []
    modern = get_asyncssh_compatible_algorithms("modern")
    assert "diffie-hellman-group1-sha1" not in modern["kex_algs"]
    assert "ssh-dss" not in modern["server_host_key_algs"]
    assert "hmac-md5" not in modern["mac_algs"]


def test_library_algorithm_order_cannot_prefer_legacy_over_modern():
    assert filter_ssh_algorithm_names(
        [b"ssh-dss", b"ssh-rsa", b"ssh-ed25519-cert-v01@openssh.com", b"ssh-ed25519"],
        "host_key",
    ) == ["ssh-ed25519-cert-v01@openssh.com", "ssh-ed25519", "ssh-rsa", "ssh-dss"]


@pytest.mark.parametrize("profile", [None, "legacy_compat", "legacy_break_glass"])
@pytest.mark.parametrize("old_peer", [True, False])
def test_paramiko_negotiates_with_old_and_modern_peers(profile, old_peer):
    """Exercise a real SSH handshake without contacting any managed device."""
    import socket
    import threading
    import paramiko

    class PasswordServer(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL

    client_socket, peer_socket = socket.socketpair()
    client = paramiko.Transport(
        client_socket,
        disabled_algorithms=build_paramiko_compatibility_kwargs(profile)["disabled_algorithms"],
    )
    server = paramiko.Transport(peer_socket)
    security = server.get_security_options()
    security.kex = ("diffie-hellman-group1-sha1" if old_peer else "ecdh-sha2-nistp256",)
    security.key_types = ("ssh-rsa" if old_peer else "rsa-sha2-256",)
    security.ciphers = ("aes128-cbc" if old_peer else "aes128-ctr",)
    security.digests = ("hmac-md5" if old_peer else "hmac-sha2-256",)
    server.add_server_key(paramiko.RSAKey.generate(2048))
    server_errors = []

    def serve():
        try:
            server.start_server(server=PasswordServer())
        except Exception as exc:
            server_errors.append(exc)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        client.start_client(timeout=5)
        client.auth_password("synthetic-test-user", "synthetic-test-password")
        assert client.is_authenticated()
        assert client.host_key_type == security.key_types[0]
        assert client.local_cipher == security.ciphers[0]
        assert client.local_mac == security.digests[0]
    finally:
        client.close()
        server.close()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert not server_errors


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
    assert kwargs.get("disabled_algorithms") == {}
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
    assert options["disabled_algorithms"] == {}

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
        assert "diffie-hellman-group1-sha1" in transport.preferred_kex
        assert "hmac-md5" in transport.preferred_macs
        assert "hmac-sha1-96" in transport.preferred_macs
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

