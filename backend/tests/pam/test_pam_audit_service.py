from __future__ import annotations

from services.pam_audit_service import (
    CommandAssembler,
    PromptParser,
    assess_command,
    build_command_submission,
    canonical_action,
    is_bare_terminal_enter,
    redact_command_input,
    redact_output,
)


def test_command_assembler_handles_backspace_cursor_and_submit():
    assembler = CommandAssembler()
    assert assembler.feed("show intf brie\x08ef\r") == ["show intf brief"]
    assert assembler.feed("abc\x1b[DX\r") == ["abXc"]


def test_bare_enter_is_a_terminal_control_action_not_a_command():
    assert is_bare_terminal_enter("\r")
    assert is_bare_terminal_enter("\n")
    assert is_bare_terminal_enter("\r\n")
    assert not is_bare_terminal_enter("show version\r")


def test_prompt_parser_and_canonical_action_are_vendor_aware():
    assert PromptParser().parse("\r\n", vendor_platform="cisco_ios").mode == "unknown"
    assert PromptParser().parse("<SW01>", vendor_platform="h3c_comware").privilege == "user"
    assert PromptParser().parse("[SW01-GigabitEthernet1/0/1]", vendor_platform="h3c_comware").mode == "config"
    assert canonical_action("display current-configuration", vendor_platform="h3c_comware") == "READ_FULL_CONFIGURATION"


def test_pam_risk_policy_blocks_secrets_and_destructive_commands():
    secret = assess_command("set password SuperSecret", vendor_platform="cisco_ios")
    destructive = assess_command("reload", vendor_platform="cisco_ios")
    change = assess_command("configure terminal", vendor_platform="cisco_ios")
    assert secret.policy_decision == "BLOCK" and secret.risk_level == "L4"
    assert destructive.policy_decision == "BLOCK"
    assert change.policy_decision == "CONFIRM" and change.confirmation_required


def test_output_is_redacted_but_raw_is_not_returned():
    safe, categories = redact_output("username admin password SuperSecret")
    assert "SuperSecret" not in safe
    assert "credential" in categories


def test_secret_command_value_never_enters_audit_projection():
    decision = assess_command("set password SuperSecret123")
    assert decision.policy_decision == "BLOCK"
    assert "SuperSecret123" not in decision.command_safe
    assert "<REDACTED>" in decision.command_safe
    assert "SuperSecret123" not in redact_command_input("password=SuperSecret123")


def test_command_submission_build_does_not_touch_database(monkeypatch):
    from services import pam_audit_service

    def fail_if_called():
        raise AssertionError("interactive command construction must not wait for PostgreSQL")

    monkeypatch.setattr(pam_audit_service, "get_db_connection", fail_if_called)
    submission = build_command_submission(
        tenant_id="tenant-default",
        session_id="session-1",
        actor_id="alice",
        device_id="device-1",
        source_type="interactive",
        command_index=1,
        decision=assess_command("show version", vendor_platform="cisco_ios"),
        vendor_platform="cisco_ios",
        cli_mode="exec",
    )
    assert submission["command"]["policy_decision"] == "ALLOW"
    assert submission["operation"]["event_hash"]


def test_audit_only_submission_records_risk_without_enforcement(monkeypatch):
    from services import pam_audit_service

    def fail_if_called():
        raise AssertionError("audit-only projection construction must not wait for PostgreSQL")

    monkeypatch.setattr(pam_audit_service, "get_db_connection", fail_if_called)
    submission = build_command_submission(
        tenant_id="tenant-default",
        session_id="session-1",
        actor_id="alice",
        device_id="device-1",
        source_type="interactive",
        command_index=2,
        decision=assess_command("reload", vendor_platform="cisco_ios"),
        vendor_platform="cisco_ios",
        cli_mode="exec",
        enforcement_mode="audit_only",
    )
    assert submission["command"]["policy_decision"] == "AUDIT"
    assert submission["command"]["accepted_state"] == "accepted"
    assert submission["command"]["execution_status"] == "executing"
    assert submission["operation"]["metadata"]["recommended_policy_decision"] == "BLOCK"
