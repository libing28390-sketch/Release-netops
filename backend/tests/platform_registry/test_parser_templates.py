from __future__ import annotations

import pytest
from fastapi import HTTPException

from core import crypto
from core.config import settings
from api.parser_templates import _enabled, api_parser_capabilities
from database import get_db_connection
from database.migrations.m0099_repair_unverified_parser_reviews import upgrade as repair_unverified_parser_reviews_upgrade
from services.parser_template_service import (
    approve_version,
    create_sample,
    create_template,
    create_version,
    delete_template,
    delete_sample,
    deprecate_version,
    fork_template,
    list_audit_logs,
    list_samples,
    list_templates_page,
    list_templates,
    list_version_mappings,
    publish_version,
    regression_test_template,
    run_published_version_regression,
    rollback_version,
    sandbox_test,
    submit_version,
    withdraw_version,
    template_impact,
    test_version as run_version_test,
    update_version,
    update_template,
)
from services.platform_registry_service import PlatformRegistryError


VALID_TEMPLATE = """Value FIELD (.*)

Start
  ^${FIELD} -> Record"""


def test_parser_template_write_gate_is_closed_by_default(monkeypatch):
    monkeypatch.delenv("PLATFORM_REGISTRY_ENABLED", raising=False)
    with pytest.raises(HTTPException) as error:
        _enabled()
    assert error.value.status_code == 503


def test_profile_scoped_template_uses_canonical_parser_platform(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template(
        {
            "platform_code": "hp_comware",
            "platform_profile_id": "system-profile-h3c_comware",
            "template_code": "H3C_PROFILE_SCOPED",
            "name": "H3C profile scoped",
        },
        owner,
    )
    assert template["platform_profile_id"] == "system-profile-h3c_comware"
    assert template["platform_code"] == "hp_comware"


def test_parser_template_list_can_filter_by_netmiko_driver_platform(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    cisco = create_template(
        {"platform_code": "cisco_ios", "template_code": "DRIVER_CISCO", "name": "Cisco driver template"},
        owner,
    )
    h3c = create_template(
        {"platform_code": "hp_comware", "template_code": "DRIVER_H3C", "name": "H3C driver template"},
        owner,
    )

    cisco_page = list_templates_page(owner, driver_platform="cisco_ios", page=1, page_size=100)
    h3c_page = list_templates_page(owner, driver_platform="hp_comware", page=1, page_size=100)

    assert cisco["id"] in {item["id"] for item in cisco_page["items"]}
    assert h3c["id"] not in {item["id"] for item in cisco_page["items"]}
    assert h3c["id"] in {item["id"] for item in h3c_page["items"]}


def test_parser_capabilities_report_closed_write_gate_and_read_only_sandbox(monkeypatch):
    monkeypatch.delenv("PLATFORM_REGISTRY_ENABLED", raising=False)
    closed = api_parser_capabilities({"role": "Viewer", "tenant_id": "tenant-1"})
    assert closed["data"] == {"write_enabled": False, "read_only_sandbox_enabled": True}

    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    opened = api_parser_capabilities({"role": "Viewer", "tenant_id": "tenant-1"})
    assert opened["data"] == {"write_enabled": True, "read_only_sandbox_enabled": True}


def test_parser_template_version_test_is_tenant_scoped_and_sandboxed(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    other = {"id": "other-1", "username": "other", "role": "Operator", "tenant_id": "tenant-2"}

    template = create_template(
        {"platform_code": "cisco_ios", "template_code": "CUSTOM_CLOCK", "name": "Custom clock"},
        owner,
    )
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    tested = run_version_test(version["id"], {"sample_output": "hello\n"}, owner)

    assert tested["success"] is True
    assert tested["records"] == [{"field": "hello"}]
    assert all(item.get("tenant_id") != "tenant-1" for item in list_templates(other))
    with pytest.raises(PlatformRegistryError) as error:
        run_version_test(version["id"], {"sample_output": "hello\n"}, other)
    assert getattr(error.value, "code", "") == "PARSER_SCOPE_DENIED"


def test_parser_template_lifecycle_requires_separation_and_passed_test(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "test-parser-lifecycle-key")
    monkeypatch.setattr(crypto, "_aes_key", None)
    author = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "LIFECYCLE"}, author)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, author)
    create_sample(version["id"], {"sample_output": "hello\n"}, author)

    regression = regression_test_template(template["id"], author, version_id=version["id"])
    assert regression["passed"] is True
    assert regression["sample_count"] == 1

    with pytest.raises(PlatformRegistryError) as submit_required:
        submit_version(version["id"], author)
    assert submit_required.value.code == "PARSER_TEST_REQUIRED"
    assert str(submit_required.value) == "解析版本在提交审核前必须先通过 Sandbox 测试"

    run_version_test(version["id"], {"sample_output": "hello\n"}, author)
    submitted = submit_version(version["id"], author)
    assert submitted["status"] == "IN_REVIEW"
    with pytest.raises(PlatformRegistryError) as self_approval:
        approve_version(version["id"], author)
    assert self_approval.value.code == "PARSER_RELEASE_PERMISSION_REQUIRED"

    approved = approve_version(version["id"], reviewer)
    assert approved["status"] == "APPROVED"
    published = publish_version(version["id"], reviewer)
    assert published["status"] == "PUBLISHED"
    assert published["submitted_by"] == "author-1"
    assert published["approved_by"] == "reviewer-1"
    assert published["published_by"] == "reviewer-1"
    assert '"regression_count": 1' in published["test_summary_json"]
    conn = get_db_connection()
    try:
        release_regression = run_published_version_regression(conn, version["id"])
    finally:
        conn.close()
    assert release_regression == {"version_id": version["id"], "sample_count": 1, "passed": True}


def test_parser_approval_rejects_legacy_unverified_review(isolated_db):
    owner = {"id": "owner-legacy", "username": "owner-legacy", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-legacy", "username": "reviewer-legacy", "role": "Administrator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "LEGACY_REVIEW_GATE"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(version["id"], {"sample_output": "hello\n"}, owner)
    submit_version(version["id"], owner)

    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute("UPDATE parser_template_versions SET test_summary_json = '{}' WHERE id = ?", (version["id"],))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(PlatformRegistryError) as approval_required:
        approve_version(version["id"], reviewer)
    assert approval_required.value.code == "PARSER_TEST_REQUIRED"

    run_version_test(version["id"], {"sample_output": "hello\n"}, owner)
    approved = approve_version(version["id"], reviewer)
    assert approved["status"] == "APPROVED"


def test_parser_migration_returns_unverified_review_states_to_draft(isolated_db):
    owner = {"id": "owner-repair", "username": "owner-repair", "role": "Operator", "tenant_id": "tenant-1"}
    version_ids = []
    for index, status in enumerate(("IN_REVIEW", "APPROVED"), start=1):
        template = create_template({"platform_code": "cisco_ios", "template_code": f"REPAIR_GATE_{index}"}, owner)
        version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
        version_ids.append(version["id"])
        conn = isolated_db["module"].get_db_connection()
        try:
            conn.execute(
                "UPDATE parser_template_versions SET status = ?, test_summary_json = '{}' WHERE id = ?",
                (status, version["id"]),
            )
            conn.commit()
        finally:
            conn.close()

    conn = isolated_db["module"].get_db_connection()
    try:
        repair_unverified_parser_reviews_upgrade(conn.cursor(), True)
        conn.commit()
        rows = conn.execute(
            "SELECT id, status FROM parser_template_versions WHERE id = ANY(?)",
            (version_ids,),
        ).fetchall()
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM parser_template_audit_logs WHERE event_type = 'VERSION_GATE_REPAIRED' AND version_id = ANY(?)",
            (version_ids,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert {row["status"] for row in rows} == {"DRAFT"}
    assert audit_count == 2


def test_parser_submitter_can_withdraw_in_review_version(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    other = {"id": "other-1", "username": "other", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "WITHDRAW_TEST"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(version["id"], {"sample_output": "hello\n"}, owner)
    submitted = submit_version(version["id"], owner)
    assert submitted["status"] == "IN_REVIEW"

    with pytest.raises(PlatformRegistryError) as forbidden:
        withdraw_version(version["id"], other)
    assert forbidden.value.code == "PARSER_WITHDRAW_FORBIDDEN"

    withdrawn = withdraw_version(version["id"], owner)
    assert withdrawn["status"] == "DRAFT"
    assert {row["event_type"] for row in list_audit_logs(template["id"], owner)} >= {"VERSION_WITHDRAWN"}


def test_parser_samples_are_encrypted_and_never_listed_as_plaintext(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "test-parser-sample-key")
    monkeypatch.setattr(crypto, "_aes_key", None)
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "SAMPLE_SECURE"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)

    sample = create_sample(
        version["id"],
        {"sample_name": "clock", "sample_output": "secret-device-output\n", "expected_records": [{"FIELD": "secret"}]},
        owner,
    )
    assert sample["encrypted"] is True
    conn = isolated_db["module"].get_db_connection()
    try:
        stored = conn.execute(
            "SELECT sample_output, sample_output_encrypted, raw_output_expires_at FROM parser_test_samples WHERE id = ?",
            (sample["id"],),
        ).fetchone()
        assert stored["sample_output"] == "{}"
        assert stored["sample_output_encrypted"].startswith("enc:v2:")
        assert stored["raw_output_expires_at"]
    finally:
        conn.close()
    listed = list_samples(version["id"], owner)
    assert listed[0]["id"] == sample["id"]
    assert "sample_output" not in listed[0]
    assert "sample_output_encrypted" not in listed[0]


def test_parser_sample_storage_fails_closed_without_encryption_key(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "change-me-to-a-random-secret")
    monkeypatch.setattr(crypto, "_aes_key", None)
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "SAMPLE_NO_KEY"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    with pytest.raises(PlatformRegistryError) as error:
        create_sample(version["id"], {"sample_output": "secret\n"}, owner)
    assert error.value.code == "OUTPUT_ENCRYPTION_UNAVAILABLE"


def test_parser_template_fork_creates_tenant_owned_draft(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    conn = isolated_db["module"].get_db_connection()
    try:
        system = conn.execute(
            "SELECT id FROM parser_templates WHERE source = 'SYSTEM' ORDER BY template_code LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert system
    forked = fork_template(system["id"], {"template_code": "FORKED_TEMPLATE"}, owner)
    assert forked["source"] == "FORKED"
    assert forked["tenant_id"] == "tenant-1"
    assert forked["forked_from_template_id"] == system["id"]
    assert forked["initial_version"]["status"] == "DRAFT"


def test_legacy_fork_without_tenant_is_not_treated_as_system_for_admin_delete(isolated_db):
    """Administrator-created forks from older sessions may have NULL tenant_id."""
    admin = {"id": "admin-1", "username": "admin", "role": "Administrator"}
    conn = isolated_db["module"].get_db_connection()
    try:
        template_id = "legacy-fork-without-tenant"
        conn.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_code, template_code, source, status, created_by, created_at, updated_at)
               VALUES (?, NULL, 'zte_zxros', 'ZTE_ZXROS_SHOW_VLAN_FORK', 'FORKED', 'ACTIVE', 'admin', 'now', 'now')""",
            (template_id,),
        )
        conn.commit()
    finally:
        conn.close()

    assert delete_template(template_id, admin) == {"id": template_id, "deleted": True}


def test_parser_draft_update_sandbox_persists_summary_and_audit(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "DRAFT_UPDATE"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    updated = update_version(version["id"], {"content": VALID_TEMPLATE + "\n", "field_contract": {}, "lock_version": version.get("lock_version")}, owner)
    assert updated["checksum"] != version["checksum"]
    result = sandbox_test(
        {"version_id": updated["id"], "content": updated["content"], "field_contract": {}, "sample_output": "hello\n", "persist": True, "lock_version": updated.get("lock_version")},
        owner,
    )
    assert result["records"] == [{"field": "hello"}]
    assert result["summary"]["duration_ms"] >= 0
    assert {row["event_type"] for row in list_audit_logs(template["id"], owner)} >= {"VERSION_UPDATED", "SANDBOX_PERSISTED"}
    page = list_templates_page(owner, search="DRAFT_UPDATE", page=1, page_size=10)
    assert page["total"] == 1
    assert page["items"][0]["template_code"] == "DRAFT_UPDATE"


def test_parser_draft_template_can_update_identity_and_delete_when_unused(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "DRAFT_IDENTITY", "name": "Before"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)

    updated = update_template(
        template["id"],
        {
            "platform_code": "cisco_ios",
            "template_code": "DRAFT_IDENTITY_RENAMED",
            "name": "After",
            "platform_profile_id": None,
            "lock_version": template.get("lock_version"),
        },
        owner,
    )
    assert updated["template_code"] == "DRAFT_IDENTITY_RENAMED"
    assert updated["name"] == "After"
    assert updated["lock_version"] == int(template.get("lock_version") or 1) + 1

    deleted = delete_template(updated["id"], owner)
    assert deleted == {"id": updated["id"], "deleted": True}
    conn = isolated_db["module"].get_db_connection()
    try:
        assert conn.execute("SELECT id FROM parser_templates WHERE id = ?", (updated["id"],)).fetchone() is None
        assert conn.execute("SELECT id FROM parser_template_versions WHERE id = ?", (version["id"],)).fetchone() is None
    finally:
        conn.close()


def test_parser_template_delete_rejects_system_and_mapped_versions(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    conn = isolated_db["module"].get_db_connection()
    try:
        system = conn.execute("SELECT id FROM parser_templates WHERE source = 'SYSTEM' LIMIT 1").fetchone()
    finally:
        conn.close()
    assert system
    with pytest.raises(PlatformRegistryError) as system_error:
        delete_template(system["id"], owner)
    assert system_error.value.code == "SYSTEM_TEMPLATE_IMMUTABLE"

    template = create_template({"platform_code": "cisco_ios", "template_code": "DRAFT_MAPPED"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    conn = isolated_db["module"].get_db_connection()
    try:
        release = conn.execute("SELECT id FROM platform_releases LIMIT 1").fetchone()
        assert release
        conn.execute(
            """UPDATE platform_release_actions SET parser_template_version_id = ?
               WHERE id = (SELECT id FROM platform_release_actions WHERE release_id = ? LIMIT 1)""",
            (version["id"], release["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PlatformRegistryError) as mapped_error:
        delete_template(template["id"], owner)
    assert mapped_error.value.code == "PARSER_TEMPLATE_IN_USE"


def test_system_version_can_be_sandboxed_without_mutation(isolated_db):
    user = {"id": "viewer-1", "username": "viewer", "role": "Operator", "tenant_id": "tenant-1"}
    conn = isolated_db["module"].get_db_connection()
    try:
        template_id = "system-sandbox-template"
        version_id = "system-sandbox-version"
        conn.execute(
            """INSERT INTO parser_templates (id, tenant_id, platform_code, template_code, source, status, created_by, created_at, updated_at)
               VALUES (?, NULL, 'cisco_ios', 'SYSTEM_SANDBOX', 'SYSTEM', 'ACTIVE', 'system', 'now', 'now')""",
            (template_id,),
        )
        conn.execute(
            """INSERT INTO parser_template_versions (id, template_id, version_number, status, content, checksum, field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, 'checksum', '{}', '{}', 'system', 'now', 'now')""",
            (version_id, template_id, VALID_TEMPLATE),
        )
        conn.commit()
    finally:
        conn.close()
    result = sandbox_test({"version_id": version_id, "sample_output": "hello\n"}, user)
    assert result["records"] == [{"field": "hello"}]
    conn = isolated_db["module"].get_db_connection()
    try:
        stored = conn.execute("SELECT test_summary_json FROM parser_template_versions WHERE id = ?", (version_id,)).fetchone()[0]
    finally:
        conn.close()
    assert stored == "{}"


def test_parser_version_mapping_read_model_returns_action_and_release_context(isolated_db):
    user = {"id": "viewer-1", "username": "viewer", "role": "Operator", "tenant_id": "tenant-1"}
    conn = isolated_db["module"].get_db_connection()
    try:
        version = conn.execute(
            """SELECT v.id FROM parser_template_versions v
               JOIN parser_templates t ON t.id = v.template_id
               WHERE t.source = 'SYSTEM' AND v.status = 'PUBLISHED'
               ORDER BY t.template_code LIMIT 1""",
        ).fetchone()
        action = conn.execute(
            """SELECT a.id FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               WHERE r.status = 'PUBLISHED' ORDER BY a.action_code LIMIT 1""",
        ).fetchone()
        assert version and action
        conn.execute(
            "UPDATE platform_release_actions SET parser_template_version_id = ? WHERE id = ?",
            (version["id"], action["id"]),
        )
        conn.commit()
    finally:
        conn.close()


    mappings = list_version_mappings(version["id"], user)
    assert mappings
    assert mappings[0]["parser_template_version_id"] == version["id"]
    assert mappings[0]["action_code"]
    assert mappings[0]["command"]
    assert mappings[0]["release_status"] == "PUBLISHED"
    assert mappings[0]["profile_id"]


def test_parser_template_delete_allows_unreleased_review_lifecycle(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}

    in_review = create_template({"platform_code": "cisco_ios", "template_code": "DELETE_IN_REVIEW"}, owner)
    in_review_version = create_version(in_review["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(in_review_version["id"], {"sample_output": "hello\n"}, owner)
    submitted = submit_version(in_review_version["id"], owner)
    assert submitted["status"] == "IN_REVIEW"
    assert delete_template(in_review["id"], owner) == {"id": in_review["id"], "deleted": True}

    approved = create_template({"platform_code": "cisco_ios", "template_code": "DELETE_APPROVED"}, owner)
    approved_version = create_version(approved["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(approved_version["id"], {"sample_output": "hello\n"}, owner)
    submitted_approved = submit_version(approved_version["id"], owner)
    approved_version = approve_version(submitted_approved["id"], reviewer)
    assert approved_version["status"] == "APPROVED"
    assert delete_template(approved["id"], owner) == {"id": approved["id"], "deleted": True}


def test_parser_template_delete_rejects_published_version(isolated_db):
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "DELETE_PUBLISHED"}, owner)
    version = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(version["id"], {"sample_output": "hello\n"}, owner)
    submitted = submit_version(version["id"], owner)
    approved = approve_version(submitted["id"], reviewer)
    published = publish_version(approved["id"], reviewer)
    assert published["status"] == "PUBLISHED"

    with pytest.raises(PlatformRegistryError) as error:
        delete_template(template["id"], owner)
    assert error.value.code == "PARSER_TEMPLATE_DELETE_BLOCKED"


def test_published_version_can_be_deprecated_and_rolled_back(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "test-parser-rollback-key")
    monkeypatch.setattr(crypto, "_aes_key", None)
    owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    template = create_template({"platform_code": "cisco_ios", "template_code": "ROLLBACK_TEST"}, owner)
    first = create_version(template["id"], {"content": VALID_TEMPLATE}, owner)
    run_version_test(first["id"], {"sample_output": "one\n"}, owner)
    submitted_first = submit_version(first["id"], owner)
    approved_first = approve_version(submitted_first["id"], reviewer)
    publish_version(approved_first["id"], reviewer)
    second = create_version(template["id"], {"content": VALID_TEMPLATE.replace("FIELD", "OTHER")}, owner)
    run_version_test(second["id"], {"sample_output": "two\n"}, owner)
    submitted_second = submit_version(second["id"], owner)
    approved = approve_version(submitted_second["id"], reviewer)
    publish_version(approved["id"], reviewer)
    deprecate_version(approved["id"], reviewer)
    rolled = rollback_version(first["id"], reviewer)
    assert rolled["status"] == "PUBLISHED"
