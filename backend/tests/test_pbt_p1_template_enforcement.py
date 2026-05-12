"""
Phase E — Fix-checking PBT for Property P1: command-template enforcement.

Task 17.1 — Property P1 — command-template enforcement PBT

Generates the full matrix of:
  (command_template_kind ∈ {empty, manual, template-no-scenario,
                             template-no-execute, template-valid})
  × (status ∈ {'draft', 'initial_review', 'final_review', 'approved'})

Asserts the acceptance matrix from design.md §Testing Strategy →
Property-Based Tests → P1:

  - status == 'draft' + empty template          → accepted (HTTP 200)
  - status == 'draft' + non-empty template      → validated by
    _build_command_template_snapshot (structural check, not P1 enforcement)
  - status ∈ {'initial_review','final_review','approved'} + empty template
                                                → rejected (HTTP 400) — P1 enforcement
  - status ∈ {'initial_review','final_review','approved'} + invalid template
                                                → rejected (HTTP 400)
  - status ∈ {'initial_review','final_review','approved'} + template-valid
                                                → not rejected for P1 completeness

The core P1 invariant: the completeness enforcement (FEATURE_TEMPLATE_REQUIRED)
only fires for non-draft statuses. For draft, an empty template is always
accepted. For non-draft, any template that fails the completeness check
(empty, manual mode, no scenario_id, no preview.execute) is rejected.

**Validates: Requirements 2.1, 2.2, 2.3**
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st

import api.change_orders as _co_module


# ── Feature flag fixture ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def enable_template_required(monkeypatch):
    """Enable FEATURE_TEMPLATE_REQUIRED for all tests in this module.

    Task 14.1 gates enforcement behind this flag; the fix-checking PBT
    (Phase E) verifies the *fixed* behavior, so the flag must be ON.
    """
    monkeypatch.setattr(_co_module, "FEATURE_TEMPLATE_REQUIRED", True)


# ── Template kind definitions ─────────────────────────────────────────
# Exactly the five kinds specified in task 17.1:

TEMPLATE_KINDS: dict[str, dict] = {
    "empty": {},
    "manual": {"mode": "manual", "commands": ["shutdown"]},
    "template-no-scenario": {
        "mode": "template",
        "scenario_id": "",
        "preview": {"execute": []},
    },
    "template-no-execute": {
        "mode": "template",
        "scenario_id": "test-001",
        "preview": {"execute": []},
    },
    "template-valid": {
        "mode": "template",
        "scenario_id": "test-001",
        "preview": {"execute": ["show version"]},
        "platform": "cisco_ios",
        "variables": {},
    },
}

# Invalid kinds for P1 completeness enforcement (non-draft rejection):
# These are the kinds that _validate_template_completeness rejects.
# Note: manual, template-no-scenario, template-no-execute are also rejected
# by _build_command_template_snapshot (structural check), but the P1
# enforcement additionally rejects empty templates at non-draft status.
P1_INVALID_KINDS = ["empty", "manual", "template-no-scenario", "template-no-execute"]

# Statuses under test
DRAFT_STATUS = "draft"
NON_DRAFT_STATUSES = ["initial_review", "final_review", "approved"]
ALL_STATUSES = [DRAFT_STATUS] + NON_DRAFT_STATUSES

# P1 completeness error messages from _validate_template_completeness
# and _normalize_command_template_payload
P1_COMPLETENESS_MESSAGES = [
    "提交初审前必须选择场景化命令模板并渲染出可执行命令",
    "提交初审前必须渲染出可执行命令",
    "非草稿状态的配置变更工单必须携带有效的场景化模板",
]


# ── Helper: invoke api_create_change_order in-process ────────────────

def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return ``(status_code, result_or_detail)``.

    Calls ``api_create_change_order`` directly, bypassing HTTP routing.
    Returns 200 on success, or the HTTPException status_code + detail on
    failure.
    """
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body_payload.setdefault("title", "P1 PBT order")
    body_payload.setdefault("description", "")
    body_payload.setdefault("order_type", "config_change")
    body_payload.setdefault("priority", "medium")
    body_payload.setdefault("target_devices", [])
    body_payload.setdefault("commands", [])
    body_payload.setdefault("rollback_plan", "")
    body_payload.setdefault("risk_level", "low")
    body_payload.setdefault("scheduled_start", "")
    body_payload.setdefault("scheduled_end", "")

    body = ChangeOrderCreate(**body_payload)
    try:
        result = api_create_change_order(body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _is_p1_completeness_rejection(detail: object) -> bool:
    """Return True if the detail string is a P1 completeness error message."""
    detail_str = str(detail)
    return any(msg in detail_str for msg in P1_COMPLETENESS_MESSAGES)


# ── Strategies ────────────────────────────────────────────────────────

def _kind_strategy():
    return st.sampled_from(list(TEMPLATE_KINDS.keys()))


def _status_strategy():
    return st.sampled_from(ALL_STATUSES)


def _p1_invalid_kind_strategy():
    return st.sampled_from(P1_INVALID_KINDS)


def _non_draft_status_strategy():
    return st.sampled_from(NON_DRAFT_STATUSES)


# ── Core P1 invariant: draft + empty template is always accepted ──────

def test_p1_draft_empty_template_accepted(isolated_db, requester):
    """
    **Validates: Requirements 2.1, 2.3**

    The most fundamental P1 invariant: draft status with an empty
    command_template MUST be accepted (HTTP 200).

    This is the baseline: draft orders do not require a template.
    """
    status_code, detail = _invoke_create(
        {"status": "draft", "command_template": {}},
        actor=requester,
    )
    assert status_code == 200, (
        f"P1 violation: draft + empty template → HTTP {status_code}. "
        f"Detail: {detail!r}"
    )


# ── Core P1 invariant: non-draft + empty template is always rejected ──

@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_non_draft_empty_template_rejected(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    P1 enforcement: non-draft status with an empty command_template MUST
    be rejected with HTTP 400 (P1 completeness check).
    """
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": {},
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 violation: status={status!r} + empty template → HTTP {status_code} "
        f"(expected 400). Detail: {detail!r}"
    )
    assert _is_p1_completeness_rejection(detail), (
        f"P1 violation: status={status!r} + empty template → HTTP 400 but "
        f"not for P1 completeness reason. Detail: {detail!r}"
    )


# ── Core P1 invariant: non-draft + manual mode is always rejected ─────

@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_non_draft_manual_template_rejected(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    P1 enforcement: non-draft status with manual mode command_template
    MUST be rejected with HTTP 400.

    Manual mode fails _validate_template_completeness because
    mode != 'template'.
    """
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": {"mode": "manual", "commands": ["shutdown"]},
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 violation: status={status!r} + manual template → HTTP {status_code} "
        f"(expected 400). Detail: {detail!r}"
    )


# ── Core P1 invariant: non-draft + template-no-scenario is rejected ───

@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_non_draft_template_no_scenario_rejected(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    P1 enforcement: non-draft status with template mode but empty
    scenario_id MUST be rejected with HTTP 400.
    """
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": {
                "mode": "template",
                "scenario_id": "",
                "preview": {"execute": []},
            },
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 violation: status={status!r} + template-no-scenario → "
        f"HTTP {status_code} (expected 400). Detail: {detail!r}"
    )


# ── Core P1 invariant: non-draft + template-no-execute is rejected ────

@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_non_draft_template_no_execute_rejected(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    P1 enforcement: non-draft status with template mode, a scenario_id,
    but empty preview.execute MUST be rejected with HTTP 400.
    """
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": {
                "mode": "template",
                "scenario_id": "test-001",
                "preview": {"execute": []},
            },
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 violation: status={status!r} + template-no-execute → "
        f"HTTP {status_code} (expected 400). Detail: {detail!r}"
    )


# ── Core P1 invariant: non-draft + template-valid not rejected for P1 ─

@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_non_draft_valid_template_not_rejected_for_completeness(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    P1 enforcement: non-draft status with a structurally valid template
    (mode='template', non-empty scenario_id, non-empty preview.execute)
    MUST NOT be rejected for P1 completeness reasons.

    The scenario 'test-001' may not exist in the test catalogue, so a
    400 for "scenario not found" is acceptable — but a 400 for
    "must select scenario template" is a P1 violation.
    """
    template = dict(TEMPLATE_KINDS["template-valid"])
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": template,
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )

    if status_code == 400:
        assert not _is_p1_completeness_rejection(detail), (
            f"P1 violation: non-draft + template-valid → HTTP 400 with "
            f"P1 completeness message. status={status!r}, detail={detail!r}"
        )


# ── PBT: full matrix — P1 completeness enforcement ───────────────────

@given(
    kind=_p1_invalid_kind_strategy(),
    status=_non_draft_status_strategy(),
)
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p1_pbt_invalid_template_rejected_at_non_draft(
    kind, status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    Property: ∀ kind ∈ P1_INVALID_KINDS,
              ∀ status ∈ {'initial_review','final_review','approved'},
    POST /api/change-orders MUST return HTTP 400.

    This is the core P1 fix-checking property: the completeness
    enforcement gate rejects all invalid template kinds at non-draft
    statuses.
    """
    template = dict(TEMPLATE_KINDS[kind])
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": template,
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 PBT violation: kind={kind!r}, status={status!r} → "
        f"HTTP {status_code} (expected 400). Detail: {detail!r}"
    )


# ── PBT: draft + empty template always accepted ───────────────────────

@given(status=st.just("draft"))
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p1_pbt_draft_empty_template_accepted(status, isolated_db, requester):
    """
    **Validates: Requirements 2.1, 2.3**

    Property: draft + empty template → HTTP 200.

    The P1 enforcement is a no-op for draft status; empty templates
    are always accepted.
    """
    status_code, detail = _invoke_create(
        {"status": status, "command_template": {}},
        actor=requester,
    )
    assert status_code == 200, (
        f"P1 PBT violation: draft + empty template → HTTP {status_code} "
        f"(expected 200). Detail: {detail!r}"
    )


# ── PBT: non-draft + empty template always rejected with P1 message ──

@given(status=_non_draft_status_strategy())
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p1_pbt_non_draft_empty_template_rejected_with_p1_message(
    status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    Property: non-draft + empty template → HTTP 400 with P1 completeness
    error message.

    This verifies both that the request is rejected AND that the rejection
    is specifically due to the P1 enforcement (not some other validation).
    """
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": {},
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 PBT violation: non-draft + empty template → HTTP {status_code} "
        f"(expected 400). status={status!r}, detail={detail!r}"
    )
    assert _is_p1_completeness_rejection(detail), (
        f"P1 PBT violation: non-draft + empty template → HTTP 400 but "
        f"not for P1 completeness reason. status={status!r}, detail={detail!r}"
    )


# ── Parametrized matrix: all P1-invalid kinds × all non-draft statuses ─

@pytest.mark.parametrize("kind", P1_INVALID_KINDS)
@pytest.mark.parametrize("status", NON_DRAFT_STATUSES)
def test_p1_matrix_invalid_kinds_rejected_at_non_draft(
    kind, status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.1, 2.2, 2.3**

    Full parametrized matrix: every P1-invalid template kind × every
    non-draft status MUST be rejected with HTTP 400.

    This is the explicit enumeration of the acceptance matrix from
    design.md §Testing Strategy → Property-Based Tests → P1.
    """
    template = dict(TEMPLATE_KINDS[kind])
    status_code, detail = _invoke_create(
        {
            "status": status,
            "command_template": template,
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"P1 matrix violation: status={status!r} + kind={kind!r} → "
        f"HTTP {status_code} (expected 400). Detail: {detail!r}"
    )
