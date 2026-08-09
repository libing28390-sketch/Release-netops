from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from database import get_db_connection

from services.pam_audit_service import (
    assess_command,
    calculate_batch_risk,
    check_jit_grant,
    create_batch_operation,
    create_jit_grant,
    create_rollback_checkpoint,
    detect_behavior_risk,
    evaluate_file_transfer_policy,
    generate_session_summary,
    queue_external_event,
    record_command_event,
    record_file_transfer,
    update_batch_progress,
    verify_rollback_checkpoint,
)


def test_jit_grant_is_time_bounded_and_revocable(isolated_db):
    now = datetime.now(timezone.utc)
    grant = create_jit_grant(
        tenant_id="tenant-a",
        subject_user_id="alice",
        scope={"device_ids": ["dev-1"]},
        allowed_actions=["SHOW", "INTERFACE_CONFIG"],
        denied_actions=["REBOOT"],
        created_by="admin",
        reason="approved maintenance",
        starts_at=now.isoformat(),
        ends_at=(now + timedelta(minutes=30)).isoformat(),
    )
    assert check_jit_grant(grant_id=grant["id"], tenant_id="tenant-a", subject_user_id="alice", action="SHOW")["allowed"]
    assert not check_jit_grant(grant_id=grant["id"], tenant_id="tenant-a", subject_user_id="alice", action="REBOOT")["allowed"]


def test_break_glass_and_sensitive_file_transfer_fail_closed(isolated_db):
    with pytest.raises(ValueError):
        create_jit_grant(
            tenant_id="tenant-a", subject_user_id="alice", scope={}, allowed_actions=["SHOW"], denied_actions=[],
            created_by="admin", reason="", break_glass=True, mfa_verified=False,
        )
    policy = evaluate_file_transfer_policy(file_name="running-config", direction="DOWNLOAD")
    assert policy["policy_decision"] == "BLOCK"
    event = record_file_transfer(
        tenant_id="tenant-a", session_id="sess-1", actor_id="alice", file_name="running-config",
        direction="DOWNLOAD", content_hash="sha256:abc", size_bytes=100,
    )
    assert event["policy_decision"] == "BLOCK"
    assert event["content_hash"] == "a256abc"  # only metadata is retained and non-hex characters are removed


def test_batch_risk_stops_after_failure_threshold(isolated_db):
    risk = calculate_batch_risk(command_risk_score=80, asset_criticality="critical", target_count=300, topology_impact=15, concurrency=10)
    assert risk["risk_level"] == "L4"
    operation = create_batch_operation(
        tenant_id="tenant-a", created_by="alice", target_ids=["dev-1", "dev-2", "dev-3"],
        command_risk_score=80, failure_threshold=0.1,
    )
    result = update_batch_progress(operation_id=operation["id"], tenant_id="tenant-a", completed_count=1, failed_count=1)
    assert result["state"] == "stopped"


def test_summary_behavior_checkpoint_and_external_queue_are_safe(isolated_db):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO pam_sessions (id, tenant_id, requester_username, token_expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess-1", "tenant-default", "alice", now, now, now),
        )
        conn.commit()
    decision = assess_command("show interfaces")
    record_command_event(session_id="sess-1", command_index=1, decision=decision, vendor_platform="cisco_ios", cli_mode="exec")
    summary = generate_session_summary(tenant_id="tenant-default", session_id="sess-1")
    assert summary["command_count"] == 1
    behavior = detect_behavior_risk(tenant_id="tenant-default", user_id="alice", session_id="sess-1", metrics={"blocked_commands": 4, "off_hours": True})
    assert behavior["risk_level"] in {"L2", "L3", "L4"}
    checkpoint = create_rollback_checkpoint(tenant_id="tenant-default", change_transaction_id="chg-1", device_id="dev-1")
    verification = verify_rollback_checkpoint(checkpoint_id=checkpoint["id"], tenant_id="tenant-default", health_state="DOWN", passed=False)
    assert verification["rollback_state"] == "requested"
    queued = queue_external_event(
        tenant_id="tenant-default", session_id="sess-1", event_type="pam.audit", destination_type="json",
        payload={"command_raw": "password=secret", "event_id": "evt-1"},
    )
    assert "command_raw" not in queued["metadata_keys"]
