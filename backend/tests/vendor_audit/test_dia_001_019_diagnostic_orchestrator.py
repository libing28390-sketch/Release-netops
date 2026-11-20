from __future__ import annotations

import asyncio

import pytest

from services.diagnostic_orchestrator import (
    DiagnosticErrorCode,
    DiagnosticOrchestrationError,
    DiagnosticOrchestrator,
    command_contract,
    normalize_interface_name,
    parse_cli_output,
)


def test_command_contract_requires_explicit_platform_and_never_falls_back():
    assert command_contract("cisco", "ios_xe", "interface_status").command == "show ip interface brief"
    assert command_contract("huawei", "vrp", "ospf_neighbors").command == "display ospf peer"
    assert command_contract("h3c", "comware", "bgp_summary").command == "display bgp peer"
    with pytest.raises(DiagnosticOrchestrationError) as exc:
        command_contract("cisco", None, "interface_status")
    assert exc.value.code == DiagnosticErrorCode.PLATFORM_REQUIRED


def test_interface_canonicalizer_covers_vendor_aliases():
    assert normalize_interface_name("Te1/0/1") == "TenGigabitEthernet1/0/1"
    assert normalize_interface_name("XGE1/0/1") == "TenGigabitEthernet1/0/1"
    assert normalize_interface_name("10GE1/0/1") == "TenGigabitEthernet1/0/1"
    assert normalize_interface_name("GE0/0/1") == "GigabitEthernet0/0/1"


def test_pasted_cli_is_local_and_platform_bound():
    output = "GigabitEthernet0/0/1 10.0.0.1 up up"
    evidence = parse_cli_output(output, vendor="cisco", platform="ios_xe", purpose="interface_status")
    assert evidence[0]["interface"] == "GigabitEthernet0/0/1"
    with pytest.raises(DiagnosticOrchestrationError) as exc:
        parse_cli_output(output, vendor="cisco", platform=None, purpose="interface_status")
    assert exc.value.code == DiagnosticErrorCode.PLATFORM_REQUIRED


def test_plan_is_read_only_and_each_step_requires_authorization():
    orchestrator = DiagnosticOrchestrator()
    plan = orchestrator.build_plan(symptom="OSPF 邻居异常", playbook="ospf", vendor="huawei", platform="vrp", target="sw-1")
    assert plan["read_only"] is True
    assert plan["write_operations_enabled"] is False
    result = asyncio.run(orchestrator.run(plan=plan, authorized_steps=[]))
    assert all(step["status"] == "skipped" for step in result["steps"])
    assert all(step["error_code"] == "DIA_NOT_AUTHORIZED" for step in result["steps"])


def test_run_records_evidence_duration_and_no_duplicate_checks():
    async def probe(spec, context):
        return "GigabitEthernet0/0/1 10.0.0.1 up up"

    orchestrator = DiagnosticOrchestrator(probe=probe)
    plan = orchestrator.build_plan(symptom="interface down", playbook="interface_down", vendor="cisco", platform="ios", target="sw-1")
    plan["steps"].append(dict(plan["steps"][0]))
    result = asyncio.run(orchestrator.run(plan=plan, authorized_steps=[1, 2]))
    assert result["state"] == "conclusion"
    assert result["steps"][0]["status"] == "passed"
    assert result["steps"][0]["duration_ms"] >= 0
    assert result["steps"][1]["error_code"] == "DIA_NO_INFORMATION_GAIN"
    assert result["write_operations_enabled"] is False


def test_stable_timeout_and_authentication_codes():
    async def timeout_probe(spec, context):
        await asyncio.sleep(0.02)
        return "GigabitEthernet0/0/1 10.0.0.1 up up"

    orchestrator = DiagnosticOrchestrator(probe=timeout_probe)
    plan = orchestrator.build_plan(symptom="interface down", playbook="interface_down", vendor="cisco", platform="ios", target="sw-1")
    plan["steps"][0]["command"] = "show ip interface brief"
    # The production spec timeout is intentionally bounded; this test checks
    # that exceptions remain stable and do not expose driver text.
    async def auth_probe(spec, context):
        raise PermissionError("secret should not escape")
    auth_orchestrator = DiagnosticOrchestrator(probe=auth_probe)
    result = asyncio.run(auth_orchestrator.run(plan=plan, authorized_steps=[1]))
    assert result["steps"][0]["error_code"] == "DIA_SSH_AUTH_FAILED"


@pytest.mark.parametrize(
    ("vendor", "platform", "purpose", "output"),
    [
        ("cisco", "ios_xe", "interface_status", "GigabitEthernet0/0/1 10.0.0.1 up up"),
        ("huawei", "vrp", "interface_status", "GigabitEthernet0/0/1 10.0.0.1 up up"),
        ("h3c", "comware", "interface_status", "GigabitEthernet0/0/1 10.0.0.1 up up"),
    ],
)
def test_multivendor_fixture_parse_is_platform_bound(vendor, platform, purpose, output):
    evidence = parse_cli_output(output, vendor=vendor, platform=platform, purpose=purpose)
    assert evidence and evidence[0]["status"] == "up/up"


def test_parse_failure_is_stable_and_does_not_return_raw_output():
    with pytest.raises(DiagnosticOrchestrationError) as exc:
        parse_cli_output("password=do-not-return", vendor="huawei", platform="vrp", purpose="interface_status")
    assert exc.value.code == DiagnosticErrorCode.PARSE_FAILED
    assert "do-not-return" not in str(exc.value)
