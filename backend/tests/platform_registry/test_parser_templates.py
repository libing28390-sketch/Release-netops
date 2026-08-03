from __future__ import annotations

import pytest
from fastapi import HTTPException

from core import crypto
from core.config import settings
from api.parser_templates import _enabled
from database import get_db_connection
from services.parser_template_service import (
    approve_version,
    create_sample,
    create_template,
    create_version,
    fork_template,
    list_samples,
    list_templates,
    publish_version,
    regression_test_template,
    run_published_version_regression,
    submit_version,
    test_version as run_version_test,
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

    submitted = submit_version(version["id"], author)
    assert submitted["status"] == "IN_REVIEW"
    with pytest.raises(PlatformRegistryError) as self_approval:
        approve_version(version["id"], author)
    assert self_approval.value.code == "PARSER_RELEASE_PERMISSION_REQUIRED"

    approved = approve_version(version["id"], reviewer)
    assert approved["status"] == "APPROVED"
    with pytest.raises(PlatformRegistryError) as test_required:
        publish_version(version["id"], reviewer)
    assert test_required.value.code == "PARSER_TEST_REQUIRED"

    run_version_test(version["id"], {"sample_output": "hello\n"}, author)
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
