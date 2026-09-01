from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ai.schemas.tool import AgentResponse, ToolCallPlan, ToolPlanStatus
from ai.tools.plan import ToolConfirmationStore, ToolPlanError
from ai.tools.registry import StrictToolArgs, ToolRegistry
from ai.tools.risk import ToolRiskLevel


class WriteArgs(StrictToolArgs):
    device_id: str
    command: str


class VendorArgs(StrictToolArgs):
    vendor: str


def test_agent_response_and_tool_arguments_are_strict() -> None:
    with pytest.raises(ValidationError):
        AgentResponse.model_validate_json(
            json.dumps({
                "action": "tool_call",
                "tool_name": "get_asset",
                "arguments": {"device_id": "edge-01"},
                "unexpected": "reject",
            })
        )

    registry = ToolRegistry()
    result = registry.execute_tool(
        "get_asset",
        {"device_id": "edge-01", "unexpected": "must-reject"},
        permissions={"ai.assistant"},
    )
    assert result["success"] is False
    assert result["error_code"] == "TOOL_ARGUMENTS_INVALID"


def test_plan_enforces_vendor_compatibility_and_never_executes_preview() -> None:
    registry = ToolRegistry()
    called: list[dict] = []

    def handler(*, vendor: str, tenant_id: str):
        called.append({"vendor": vendor, "tenant_id": tenant_id})
        return {"ok": True}

    registry.register_tool(
        "huawei_read",
        "Huawei read",
        "read Huawei evidence",
        "test",
        "R0",
        handler,
        VendorArgs,
        supported_vendors=("Huawei",),
    )

    incompatible = registry.plan_tool_call(
        "huawei_read",
        {"vendor": "Cisco"},
        permissions={"ai.assistant"},
    )
    assert incompatible["success"] is False
    assert incompatible["error_code"] == "TOOL_VENDOR_INCOMPATIBLE"

    preview = registry.plan_tool_call(
        "huawei_read",
        {"vendor": "Huawei"},
        permissions={"ai.assistant"},
    )
    assert preview["success"] is True
    assert preview["status"] == ToolPlanStatus.READY.value
    assert called == []


def test_high_risk_write_requires_change_order_confirmation_and_single_use_token() -> None:
    registry = ToolRegistry()
    calls: list[dict] = []

    def handler(*, device_id: str, command: str, tenant_id: str):
        calls.append({"device_id": device_id, "command": command, "tenant_id": tenant_id})
        return {"changed": True}

    registry.register_tool(
        "apply_device_command",
        "Apply command",
        "write a device command",
        "execution",
        "R3",
        handler,
        WriteArgs,
        permission_code="ai.execute",
        read_only=False,
    )

    missing_change_order = registry.plan_tool_call(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        permissions={"ai.execute"},
    )
    assert missing_change_order["success"] is False
    assert missing_change_order["error_code"] == "TOOL_CHANGE_ORDER_REQUIRED"

    prepared = registry.issue_confirmation_token(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        device_state="reachable",
        impact_scope="one device / one interface",
    )
    assert prepared["success"] is True
    assert prepared["plan"]["requires_confirmation"] is True
    assert prepared["plan"]["dry_run"] is True
    token = prepared["confirmation_token"]

    denied = registry.execute_tool(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
    )
    assert denied["error_code"] == "TOOL_CONFIRMATION_REQUIRED"
    assert calls == []

    changed_parameter = registry.execute_tool(
        "apply_device_command",
        {"device_id": "edge-01", "command": "reload"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        device_state="reachable",
        impact_scope="one device / one interface",
        confirmation_token=token,
    )
    assert changed_parameter["error_code"] == "TOOL_CONFIRMATION_INVALID"
    assert calls == []

    executed = registry.execute_tool(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        device_state="reachable",
        impact_scope="one device / one interface",
        confirmation_token=token,
    )
    assert executed["success"] is True, executed
    assert executed["audit"]["risk_level"] == ToolRiskLevel.R3_HIGH.value
    assert len(calls) == 1

    replay = registry.execute_tool(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        device_state="reachable",
        impact_scope="one device / one interface",
        confirmation_token=token,
    )
    assert replay["error_code"] == "TOOL_CONFIRMATION_INVALID"
    assert len(calls) == 1


def test_high_risk_plan_model_forces_confirmation_and_preview() -> None:
    plan = ToolCallPlan(
        tool_name="apply_device_command",
        arguments={"device_id": "edge-01", "command": "shutdown"},
        action="shutdown",
        risk_level=ToolRiskLevel.R3_HIGH,
        read_only=False,
        status=ToolPlanStatus.READY,
        dry_run=False,
    )

    assert plan.requires_confirmation is True
    assert plan.status is ToolPlanStatus.CONFIRMATION_REQUIRED
    assert plan.dry_run is True


def test_confirmation_store_binds_owner_and_plan() -> None:
    store = ToolConfirmationStore(ttl_seconds=30)
    plan = ToolCallPlan(
        tool_name="apply_device_command",
        arguments={"device_id": "edge-01", "command": "shutdown"},
        action="shutdown",
        risk_level=ToolRiskLevel.R3_HIGH,
        read_only=False,
    )
    token = store.issue(plan, tenant_id="tenant-a", user_id="alice")
    with pytest.raises(ToolPlanError) as wrong_owner:
        store.consume(plan, token, tenant_id="tenant-b", user_id="alice")
    assert wrong_owner.value.code == "TOOL_CONFIRMATION_INVALID"
    store.consume(plan, token, tenant_id="tenant-a", user_id="alice")
    with pytest.raises(ToolPlanError) as replay:
        store.consume(plan, token, tenant_id="tenant-a", user_id="alice")
    assert replay.value.code == "TOOL_CONFIRMATION_INVALID"
