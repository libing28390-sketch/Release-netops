from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ai.schemas.tool import AgentResponse, ToolCallPlan, ToolPlanStatus
from ai.security.minimizer import minimize_tool_result
from ai.tools.plan import ToolConfirmationStore, ToolPlanError
from ai.tools.registry import DeviceArgs, StrictToolArgs, ToolRegistry
from ai.tools.risk import ToolRiskLevel


class WriteArgs(StrictToolArgs):
    device_id: str
    command: str


class VendorArgs(StrictToolArgs):
    vendor: str


class ActionArgs(StrictToolArgs):
    device_id: str
    operation: str


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


def test_tool_arguments_and_results_reject_nested_secret_material() -> None:
    registry = ToolRegistry()
    called: list[dict] = []

    def handler(*, device_id: str, tenant_id: str):
        called.append({"device_id": device_id, "tenant_id": tenant_id})
        return {"ok": True}

    registry.register_tool(
        "nested_secret_test",
        "Nested secret test",
        "test",
        "test",
        "R0",
        handler,
        DeviceArgs,
    )

    rejected = registry.execute_tool(
        "nested_secret_test",
        {"device_id": "edge-01", "nested": [{"api_key": "opaque-secret-value"}]},
        permissions={"ai.assistant"},
    )
    assert rejected["success"] is False
    assert rejected["error_code"] == "TOOL_SENSITIVE_ARGUMENTS_BLOCKED"
    assert called == []

    safe = minimize_tool_result({
        "evidence": [{"source_type": "cmdb", "metadata": {"password_hash": "NeverExposeThis"}}],
        "nested": ["password=NeverExposeThis", {"apiKey": "opaque-secret-value"}],
    })
    rendered = json.dumps(safe, ensure_ascii=False)
    assert "NeverExposeThis" not in rendered
    assert "opaque-secret-value" not in rendered
    assert "password_hash" not in rendered


def test_tool_permissions_are_checked_before_validation_or_execution() -> None:
    registry = ToolRegistry()
    result = registry.execute_tool(
        "get_asset",
        {"device_id": "edge-01"},
        permissions=set(),
    )
    assert result == {"success": False, "error_code": "TOOL_PERMISSION_DENIED"}


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

    missing_device_state = registry.issue_confirmation_token(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        impact_scope="one device / one interface",
    )
    assert missing_device_state["error_code"] == "TOOL_DEVICE_STATE_REQUIRED"

    missing_impact_scope = registry.issue_confirmation_token(
        "apply_device_command",
        {"device_id": "edge-01", "command": "shutdown"},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-100",
        device_state="reachable",
    )
    assert missing_impact_scope["error_code"] == "TOOL_IMPACT_SCOPE_REQUIRED"

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


@pytest.mark.parametrize(
    ("operation", "expected_error"),
    [
        pytest.param("shutdown", "TOOL_CONFIRMATION_REQUIRED", id="shutdown"),
        pytest.param("delete configuration", "TOOL_CONFIRMATION_REQUIRED", id="delete_configuration"),
        pytest.param("批量端口操作", "TOOL_CONFIRMATION_REQUIRED", id="batch_port_operation"),
        pytest.param("rotate", "TOOL_CONFIRMATION_REQUIRED", id="credential_rotation_by_reference"),
        pytest.param("credential rotation", "TOOL_SENSITIVE_ARGUMENTS_BLOCKED", id="credential_payload_blocked"),
        pytest.param("全网变更", "TOOL_CONFIRMATION_REQUIRED", id="full_network_change"),
    ],
)
def test_high_risk_operation_matrix_never_executes_without_confirmation(operation: str, expected_error: str) -> None:
    registry = ToolRegistry()
    calls: list[dict] = []

    def handler(*, device_id: str, operation: str, tenant_id: str):
        calls.append({"device_id": device_id, "operation": operation, "tenant_id": tenant_id})
        return {"changed": True}

    registry.register_tool(
        "dangerous_operation",
        "High-risk operation",
        "execute a high-risk operation",
        "execution",
        "R3",
        handler,
        ActionArgs,
        permission_code="ai.execute",
        read_only=False,
    )
    result = registry.execute_tool(
        "dangerous_operation",
        {"device_id": "edge-01", "operation": operation},
        tenant_id="tenant-a",
        user_id="alice",
        permissions={"ai.execute"},
        change_order_id="CHG-MATRIX",
    )

    assert result["success"] is False
    assert result["error_code"] == expected_error
    if expected_error == "TOOL_CONFIRMATION_REQUIRED":
        assert result["plan"]["risk_level"] in {"R3", "R4"}
    assert calls == []


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


def test_confirmation_store_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ToolConfirmationStore(ttl_seconds=30)
    plan = ToolCallPlan(
        tool_name="apply_device_command",
        arguments={"device_id": "edge-01", "command": "shutdown"},
        action="shutdown",
        risk_level=ToolRiskLevel.R3_HIGH,
        read_only=False,
    )
    now = 1_000.0
    monkeypatch.setattr("ai.tools.plan.time.time", lambda: now)
    token = store.issue(plan, tenant_id="tenant-a", user_id="alice")
    monkeypatch.setattr("ai.tools.plan.time.time", lambda: now + 31)
    with pytest.raises(ToolPlanError) as expired:
        store.consume(plan, token, tenant_id="tenant-a", user_id="alice")
    assert expired.value.code == "TOOL_CONFIRMATION_INVALID"
