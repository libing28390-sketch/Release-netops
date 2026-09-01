"""Isolation checks for the optional Instructor feasibility study.

Instructor is intentionally not a production dependency.  These tests freeze
the only bridge shape that a future adapter may use: a gateway-owned request
in and a Pydantic model out.  They do not import a provider SDK, contact a
remote model, or exercise a production call path.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
from pathlib import Path
from typing import Any, TypeVar

from ai.schemas.intent import IntentDecision


ROOT = Path(__file__).resolve().parents[3]
MODEL = TypeVar("MODEL", bound=IntentDecision)


def test_instructor_is_absent_from_production_dependencies_and_call_paths() -> None:
    dependency_files = [
        ROOT / "backend" / "requirements.txt",
        ROOT / "requirements.txt",
        ROOT / "pyproject.toml",
    ]
    dependency_pattern = re.compile(r"(?im)^\s*instructor(?:\s*[<>=!~].*)?\s*$")
    for path in dependency_files:
        if path.exists():
            assert not dependency_pattern.search(path.read_text(encoding="utf-8")), path

    import_pattern = re.compile(r"(?im)^\s*(?:from|import)\s+instructor\b")
    for path in (ROOT / "backend").rglob("*.py"):
        if "tests" in path.parts:
            continue
        assert not import_pattern.search(path.read_text(encoding="utf-8")), path

    # This is an explicit environment check for the isolated study.  If a
    # future change installs the package, the ADR must be revisited instead of
    # silently turning the package into a production dependency.
    assert importlib.util.find_spec("instructor") is None


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        return {
            "content": (
                '{"intent":"knowledge","filters":{},"metadata":{},'
                '"confidence":0.91,"needs_clarification":false,'
                '"missing_fields":[],"clarification_question":null,'
                '"risk_level":"R0","requires_confirmation":false}'
            )
        }


async def _gateway_only_structured_bridge(
    gateway: _FakeGateway,
    *,
    messages: tuple[tuple[str, str], ...],
) -> IntentDecision:
    """Model the permitted future bridge without importing Instructor."""

    outbound_messages = [
        {"role": role, "content": content} for role, content in messages
    ]
    result = await gateway.chat(
        scene="isolated_structured_output",
        messages=outbound_messages,
        response_format={"type": "json_object"},
        user_id="isolated-test-user",
        tenant_id="isolated-test-tenant",
        task_id="isolated-instructor-bridge",
    )
    return IntentDecision.model_validate_json(result["content"])


def test_future_structured_adapter_stays_on_gateway_and_pydantic_boundary() -> None:
    gateway = _FakeGateway()
    decision = asyncio.run(
        _gateway_only_structured_bridge(
            gateway,
            messages=(("user", "查询华为 OSPF 文档"),),
        )
    )

    assert decision.intent.value == "knowledge"
    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call["scene"] == "isolated_structured_output"
    assert call["response_format"] == {"type": "json_object"}
    assert "api_key" not in call
    assert "endpoint" not in call
    assert all("http://" not in str(value) and "https://" not in str(value) for value in call.values())
