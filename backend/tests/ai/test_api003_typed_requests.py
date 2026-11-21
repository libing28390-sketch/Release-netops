from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.knowledge_contracts import (
    AttachmentCheckRequest,
    DiagnosticContext,
    DiagnosticPlanPayload,
    SecurityPolicyUpdateRequest,
    SecurityTestPayloadRequest,
)


AI_API_ROOT = Path(__file__).resolve().parents[2] / "ai" / "api"


def test_ai_api_has_no_untyped_stable_body_parameters():
    offenders: list[str] = []
    body_names = {"payload", "body", "req"}
    for path in AI_API_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                if arg.arg not in body_names or arg.annotation is None:
                    continue
                rendered = ast.unparse(arg.annotation).replace(" ", "")
                if rendered == "dict" or rendered.startswith("Dict[") or rendered.startswith("dict["):
                    offenders.append(f"{path.name}:{node.name}:{arg.arg}:{rendered}")
    assert offenders == [], "untyped stable request body parameters: " + ", ".join(offenders)


def test_security_and_diagnostic_requests_reject_unknown_fields():
    policy = SecurityPolicyUpdateRequest(allowed_provider_types=["deepseek"])
    assert policy.max_payload_bytes == 256_000
    with pytest.raises(ValidationError):
        SecurityTestPayloadRequest(messages=[{"role": "user", "content": "ok"}], raw_sql="select 1")
    with pytest.raises(ValidationError):
        AttachmentCheckRequest(text="ok", unexpected=True)
    context = DiagnosticContext(device_id="device-1", vendor="cisco", platform="ios_xe")
    assert context.device_id == "device-1"
    with pytest.raises(ValidationError):
        DiagnosticContext(device_id="device-1", credential="secret")


def test_diagnostic_plan_contract_preserves_read_only_authority():
    plan = DiagnosticPlanPayload(
        run_id="dia_1",
        symptom="interface down",
        playbook="interface_down",
        steps=[{"step_no": 1, "purpose": "interface_status", "target": "device-1", "command": "show ip interface brief"}],
    )
    assert plan.read_only is True
    assert plan.write_operations_enabled is False
    with pytest.raises(ValidationError):
        DiagnosticPlanPayload(
            run_id="dia_1", symptom="x", playbook="interface_down", write_operations_enabled=True,
        )
