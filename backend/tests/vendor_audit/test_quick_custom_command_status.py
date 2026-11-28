from contextlib import nullcontext
from types import SimpleNamespace

from services import operational_data_service as service


def test_device_rejected_command_retains_error_status(monkeypatch):
    context = {
        "public_platform": "h3c_comware",
        "parser_platform": "h3c_comware_v3",
        "connection_driver": "hp_comware",
    }
    client = SimpleNamespace(
        find_prompt=lambda: "<H3C>",
        send_command=lambda *args, **kwargs: "Unrecognized command",
    )
    monkeypatch.setattr(service, "resolve_device_platform_context", lambda device: context)
    monkeypatch.setattr(service, "_build_connection_params", lambda *args, **kwargs: {"device_type": "hp_comware"})
    monkeypatch.setattr(service, "limited_connect_handler", lambda *args, **kwargs: nullcontext(client))
    monkeypatch.setattr(service, "parse_device_cli_output", lambda *args, **kwargs: {
        "records": [],
        "parser": "platform-parser",
        "parser_platform": "h3c_comware_v3",
        "parse_status": "device_error",
        "message": "Device rejected the command",
    })

    result = service.collect_custom_command_data({"id": "test-device"}, "display example")

    category = result["categories"][0]
    assert category["success"] is False
    assert category["parse_status"] == "device_error"
    assert category["error_code"] == "DEVICE_COMMAND_ERROR"
    assert category["raw_outputs"][0]["command"] == "display example"
    assert result["summary"]["failed_categories"] == 1
