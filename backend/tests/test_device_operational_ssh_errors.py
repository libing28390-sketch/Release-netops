import json

from api.devices import _build_device_operation_ssh_failure_response


def _payload(response):
    return json.loads(response.body.decode("utf-8"))


def test_operational_data_authentication_failure_is_structured_400():
    response = _build_device_operation_ssh_failure_response(
        {
            "id": "dev-1",
            "hostname": "Core-SW1",
            "ip_address": "192.168.96.220",
        },
        "Authentication failed.",
        "operational-data",
    )

    assert response is not None
    assert response.status_code == 400
    body = _payload(response)
    assert body["error_code"] == "ssh_authentication_failed"
    assert body["detail"] == "Core-SW1 可达，但 SSH 认证被拒绝。请检查账号密码或 AAA/VTY 配置。"
    assert body["operation"] == "operational-data"
    assert body["device"]["id"] == "dev-1"


def test_parsed_command_transport_banner_failure_is_structured_400():
    response = _build_device_operation_ssh_failure_response(
        {
            "id": "dev-2",
            "hostname": "ACC-SW2",
            "ip_address": "172.16.255.12",
        },
        "Error reading SSH protocol banner",
        "parsed-command",
    )

    assert response is not None
    assert response.status_code == 400
    body = _payload(response)
    assert body["error_code"] == "ssh_transport_unreachable"
    assert body["operation"] == "parsed-command"
    assert body["device"]["hostname"] == "ACC-SW2"


def test_unknown_operational_error_is_not_reclassified():
    response = _build_device_operation_ssh_failure_response(
        {
            "id": "dev-3",
            "hostname": "Unknown-SW",
            "ip_address": "10.0.0.1",
        },
        "unexpected parser crash",
        "operational-data",
    )

    assert response is None
