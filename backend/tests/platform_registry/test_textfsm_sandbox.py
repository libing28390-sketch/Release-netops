import pytest

from services.platform_registry_service import PlatformRegistryError, _normalize_records, _validate_field_contract, redact_raw_output
from services.textfsm_sandbox_service import TextFSMSandboxError, parse_template_in_sandbox


VALID_TEMPLATE = """Value FIELD (.*)

Start
  ^${FIELD} -> Record"""


def test_textfsm_runs_in_bounded_child_process():
    assert parse_template_in_sandbox(VALID_TEMPLATE, "hello\n") == [{"FIELD": "hello"}]


def test_textfsm_reports_sandbox_failure_in_chinese():
    unmatched_template = "not a valid TextFSM template"

    with pytest.raises(TextFSMSandboxError, match="测试回显与当前 TextFSM 模板不匹配") as error:
        parse_template_in_sandbox(unmatched_template, "hello\n")
    assert error.value.code == "TEMPLATE_NOT_MATCHED"


def test_textfsm_rejects_template_and_output_limits():
    with pytest.raises(TextFSMSandboxError, match="template") as template_error:
        parse_template_in_sandbox("x" * 20, "", max_template_bytes=10)
    assert template_error.value.code == "TEMPLATE_LIMIT_EXCEEDED"

    with pytest.raises(TextFSMSandboxError, match="output") as output_error:
        parse_template_in_sandbox(VALID_TEMPLATE, "x" * 20, max_output_bytes=10)
    assert output_error.value.code == "OUTPUT_LIMIT_EXCEEDED"


def test_field_contract_validates_normalized_records():
    records = _normalize_records([{"FIELD": "hello", "COUNT": 2}], 10)
    _validate_field_contract(records, {"required": ["field"], "types": {"count": "integer"}})

    with pytest.raises(PlatformRegistryError) as error:
        _validate_field_contract([{"field": ""}], {"required": ["field"]})
    assert error.value.code == "FIELD_CONTRACT_VIOLATION"


def test_h3c_brief_field_names_are_adapted_to_registry_contract():
    records = _normalize_records(
        [{"INTERFACE": "Vlan100", "LINK": "UP", "PROTOCOL": "UP", "PRIMARY_IP": "10.0.0.1"}],
        10,
        expected_fields={"interface", "admin_status", "oper_status", "ip_address"},
    )

    assert records == [{
        "interface": "Vlan100",
        "link": "UP",
        "protocol": "UP",
        "primary_ip": "10.0.0.1",
        "admin_status": "UP",
        "oper_status": "UP",
        "ip_address": "10.0.0.1",
    }]


def test_raw_output_redacts_credential_material():
    output = "username admin password P@ssw0rd\nsnmp-server community public ro\n"
    redacted = redact_raw_output(output)
    assert "P@ssw0rd" not in redacted
    assert "public" not in redacted
    assert "<redacted>" in redacted


def test_playbook_websocket_event_redacts_credential_material():
    from api.playbooks.manager import ConnectionManager

    safe = ConnectionManager._redact_event({"output": "password: top-secret\n", "records": [{"value": "ok"}]})
    assert "top-secret" not in safe["output"]
    assert safe["records"][0]["value"] == "ok"
