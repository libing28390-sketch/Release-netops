from drivers.ssh_compat import (
    SSH_HOST_KEY_ERROR_CODE,
    build_ssh_error_guidance,
    get_ssh_error_code,
)


def test_asyncssh_untrusted_host_key_has_stable_error_code_and_guidance():
    error = 'HostKeyNotVerifiable: Host key is not trusted for host 192.168.56.12'
    assert get_ssh_error_code(error) == SSH_HOST_KEY_ERROR_CODE
    guidance = build_ssh_error_guidance(error)
    assert 'SHA256' in guidance
    assert '关闭 Host Key' in guidance
