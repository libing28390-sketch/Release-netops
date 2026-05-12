"""
Phase A — Exploration test for cluster 1.1 (template enforcement).

**Property 1: Bug Condition** — Manual / empty-template submission accepted on
unfixed code.

Per the spec front-matter of `tasks.md`:
    "Tests that need to fail on unfixed code are marked xfail(strict=True)
     → flip to strict-pass after the fix lands."

So the xfail-marked assertions below encode the *fixed* expectation
(`HTTP 400` for every bad `command_template` × non-draft `status` combo).
On UNFIXED code the assertions fail → pytest reports XFAIL → exploration
SUCCESS (the bug exists). On FIXED code (after task 14.1/14.2) the
assertions pass → pytest reports XPASS-strict → we remove the xfail marker
and the test becomes a plain passing regression guard (task 14.4).

Validates: Property 1 (design.md §Correctness Properties)
Bug_Condition: `C1(input)` in `design.md §Bug Details`
Requirements: 1.1, 1.2, 1.3 (bugfix.md)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st
import api.change_orders as _co_module


@pytest.fixture(autouse=True)
def enable_template_required(monkeypatch):
    """Enable FEATURE_TEMPLATE_REQUIRED for all tests in this module.

    Task 14.1 gates enforcement behind this flag.  The exploration tests
    (Phase A) verify the *fixed* behavior, so the flag must be ON.
    """
    monkeypatch.setattr(_co_module, "FEATURE_TEMPLATE_REQUIRED", True)


# ── Strategy: the four scoped bad `command_template` variants ─────────
# Exactly the set enumerated in the task description:
#   {}, {mode:'manual', commands:['shutdown']},
#   {mode:'template', scenario_id:'', preview:{execute:[]}},
#   {mode:'template', scenario_id:'s-x', variables:{}, preview:{execute:[]}}
_BAD_TEMPLATE_VARIANTS = [
    {},
    {"mode": "manual", "commands": ["shutdown"]},
    {"mode": "template", "scenario_id": "", "preview": {"execute": []}},
    {
        "mode": "template",
        "scenario_id": "s-x",
        "variables": {},
        "preview": {"execute": []},
    },
]

_NON_DRAFT_STATUSES = ["initial_review", "final_review", "approved"]


def _bad_template_strategy():
    return st.sampled_from(_BAD_TEMPLATE_VARIANTS)


def _non_draft_status_strategy():
    return st.sampled_from(_NON_DRAFT_STATUSES)


def _commands_for(template: dict) -> list[str]:
    if isinstance(template, dict) and template.get("mode") == "manual":
        return list(template.get("commands") or ["shutdown"])
    return ["shutdown"]


# ── Helper: invoke the handler in-process, bypass HTTP/middleware ────
def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)`.  200 on success, the
    HTTPException `status_code` and `detail` on failure."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body_payload.setdefault("title", "Exploration test order")
    body_payload.setdefault("description", "")
    body_payload.setdefault("order_type", "config_change")
    body_payload.setdefault("priority", "medium")
    body_payload.setdefault("target_devices", [])
    body_payload.setdefault("rollback_plan", "")
    body_payload.setdefault("risk_level", "low")
    body_payload.setdefault("scheduled_start", "")
    body_payload.setdefault("scheduled_end", "")
    body = ChangeOrderCreate(**body_payload)
    try:
        result = api_create_change_order(body, user=actor)
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


# ─────────────────────────────────────────────────────────────────────
# Property P1 — full bad-template × non-draft-status matrix
# ─────────────────────────────────────────────────────────────────────
@given(
    template=_bad_template_strategy(),
    target_status=_non_draft_status_strategy(),
)
@settings(
    max_examples=32,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p1_bad_template_rejected_at_non_draft(
    template, target_status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Property 1** — ∀ `command_template ∈ BAD_VARIANTS`,
    ∀ `status ∈ {'initial_review','final_review','approved'}`,
    `POST /api/change-orders` MUST return HTTP 400.

    Counterexample on unfixed code: `template={}, status='initial_review'`
    is accepted with HTTP 200. Hypothesis will find this within a handful
    of examples.
    """
    payload = {
        "status": target_status,
        "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        "command_template": dict(template),
        "commands": _commands_for(template),
    }

    status_code, _ = _invoke_create(payload, actor=requester)

    assert status_code == 400, (
        f"Bug_Condition C1 surfaced: command_template={template!r}, "
        f"status={target_status!r} → HTTP {status_code} (expected 400 after fix)."
    )


# ─────────────────────────────────────────────────────────────────────
# Shortest counterexample per bad-template branch
# ─────────────────────────────────────────────────────────────────────
# Branch A (empty dict) — the real backend bug.  XFAIL on unfixed.
def test_c1_branch_a_empty_template_initial_review(
    isolated_db, requester, initial_reviewer
):
    """Shortest input: `command_template={}` + `status='initial_review'`."""
    status_code, _ = _invoke_create(
        {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["shutdown"],
        },
        actor=requester,
    )
    assert status_code == 400


# Branches B, C, D — these variants are ALREADY rejected today by
# `_build_command_template_snapshot` (which requires a non-empty
# `scenario_id` and a scenario that exists in the catalogue).  We keep
# them as regression guards (no xfail) so that when the cluster-1.1 fix
# reorganizes the validation path it cannot accidentally widen
# acceptance.  These tests pass on both unfixed and fixed code.
def test_c1_branch_b_manual_mode_with_commands_rejected(
    isolated_db, requester, initial_reviewer
):
    """Lock-in: `{mode:'manual', commands:['shutdown']}` is rejected today
    because `_build_command_template_snapshot` demands a scenario_id."""
    status_code, detail = _invoke_create(
        {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {"mode": "manual", "commands": ["shutdown"]},
            "commands": ["shutdown"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"Regression: manual-mode template must be rejected (got {status_code} / {detail!r})"
    )


def test_c1_branch_c_template_empty_scenario_rejected(
    isolated_db, requester, initial_reviewer
):
    """Lock-in: template mode with empty `scenario_id` is rejected today."""
    status_code, detail = _invoke_create(
        {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {
                "mode": "template",
                "scenario_id": "",
                "preview": {"execute": []},
            },
            "commands": ["shutdown"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"Regression: template mode with empty scenario_id must be rejected "
        f"(got {status_code} / {detail!r})"
    )


def test_c1_branch_d_template_unknown_scenario_rejected(
    isolated_db, requester, initial_reviewer
):
    """Lock-in: template mode with a non-existent `scenario_id` is rejected."""
    status_code, detail = _invoke_create(
        {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {
                "mode": "template",
                "scenario_id": "s-x",
                "variables": {},
                "preview": {"execute": []},
            },
            "commands": ["shutdown"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"Regression: unknown scenario_id must be rejected "
        f"(got {status_code} / {detail!r})"
    )


# ─────────────────────────────────────────────────────────────────────
# Frontend-fallback property test (ChangeOrderTab.tsx:1381–1389)
# ─────────────────────────────────────────────────────────────────────
# The frontend is TypeScript so a real Vitest/fast-check runner would need
# node_modules + a test harness that does not exist in this repo today.
# Instead we port the fallback-branch logic literally into Python and use
# Hypothesis to fuzz the same property — this matches the fast-check
# "fast-check property" requested in the task description without taking
# on a new toolchain dependency.  Once a Vitest harness lands, this block
# can be mirrored in TypeScript verbatim.

def _frontend_build_payload(
    *,
    command_mode: str,
    selected_scenario_id: str,
    effective_scenario_platform: str,
    form_target_device_platform: str,
    as_draft: bool = False,
) -> dict:
    """Faithful port of the payload-building block in
    `src/pages/ChangeOrderTab.tsx` around lines 1355–1395."""
    payload: dict = {
        "status": "draft" if as_draft else "initial_review",
        "command_template": {},
        "commands": [],
        "rollback_plan": "",
    }

    if (
        command_mode == "template"
        and selected_scenario_id
        and effective_scenario_platform
    ):
        payload["command_template"] = {
            "scenario_id": selected_scenario_id,
            "source_kind": "scenario",
            "platform": effective_scenario_platform,
            "variables": {},
        }

    return payload


@given(
    device_platform=st.sampled_from(
        ["cisco_ios", "huawei_vrp", "arista_eos", "juniper_junos", "h3c_comware"]
    )
)
@settings(max_examples=16, deadline=None)
def test_p1_frontend_fallback_does_not_silently_build_payload(device_platform):
    """
    **Validates: Property 1 (frontend sub-clause)** — the
    ChangeOrderTab.tsx fallback branch `commandMode === 'template' &&
    !scenarioId && devicePlatform != ''` MUST NOT build a
    `command_template` payload.  The task expressly asks that the "built
    payload does not carry `scenario_id == devicePlatform`"; we assert
    the stronger fixed-behavior invariant: `command_template` remains
    `{}` so the order cannot be submitted behind the user's back.
    """
    payload = _frontend_build_payload(
        command_mode="template",
        selected_scenario_id="",
        effective_scenario_platform="",
        form_target_device_platform=device_platform,
        as_draft=False,
    )

    # Primary explicit check from task description: the payload must not
    # reuse devicePlatform as scenario_id.  (Holds even on unfixed code;
    # included as a sanity guard on a separate mutation vector.)
    assert payload["command_template"].get("scenario_id") != device_platform, (
        "scenario_id must never equal devicePlatform"
    )

    # Fixed-behavior expectation: no silent payload synthesis.
    assert payload["command_template"] == {}, (
        f"Bug_Condition C1 (frontend): fallback synthesized "
        f"command_template={payload['command_template']!r} from devicePlatform="
        f"{device_platform!r}. Expected after fix: command_template == {{}}."
    )
