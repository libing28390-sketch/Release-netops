"""Shared PostgreSQL fixtures for the backend test suite.

The backend test suite runs against PostgreSQL in every environment.  A
session-level, data-free schema template keeps the full bootstrap/migration
cost bounded; each test receives a disposable database cloned from that
template so tests can still mutate their database without sharing state.
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import struct
import time
import uuid
from datetime import datetime, timezone

import pytest

# CI supplies this synthetic key at the job boundary.  Provide the same
# non-production default for local pytest runs when a developer has not
# exported one, without overriding an explicitly configured local key.  The
# application itself still fails closed for an unconfigured production key.
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY",
    "test-only-credential-placeholder",
)

import database
import database.core as database_core
import database.schema as database_schema
from backend.tests.pg_test_utils import (
    capture_database_state,
    close_database_pool,
    close_temporary_test_connections,
    create_test_database,
    drop_test_database,
    switch_database,
    validate_test_server_url,
    restore_database_state,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def current_test_totp(secret: str) -> str:
    """Return the current six-digit TOTP for lifecycle integration tests.

    This helper intentionally mirrors the application's pure-Python TOTP
    implementation instead of depending on an optional authenticator package.
    It is test-only and never used by production request handling.
    """
    padded = str(secret).strip().replace(" ", "")
    padded += "=" * ((8 - len(padded) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    counter = int(time.time() / 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _insert_user(
    connection,
    *,
    username: str,
    role: str,
    change_groups: list[str] | None,
    mfa_enabled: bool = False,
    mfa_secret: str | None = None,
) -> dict:
    user_id = str(uuid.uuid4())
    now = _utc_now_iso()
    resolved_mfa_secret = mfa_secret or (base64.b32encode(os.urandom(10)).decode("ascii").rstrip("=") if mfa_enabled else "")
    connection.execute(
        """
        INSERT INTO users (
            id, username, password, role, status, created_at,
            group_name, change_groups_json, notification_channels,
            preferred_language, fixed_pin, mfa_enabled, mfa_secret
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            "x",
            role,
            "active",
            now,
            "",
            json.dumps(change_groups if change_groups is not None else []),
            "{}",
            "zh",
            "",
            1 if mfa_enabled else 0,
            resolved_mfa_secret,
        ),
    )
    connection.commit()
    return {
        "user_id": user_id,
        "username": username,
        "role": role,
        "mfa_enabled": bool(mfa_enabled),
        "mfa_secret": resolved_mfa_secret,
    }


@pytest.fixture(scope="session", autouse=True)
def _postgres_schema_template():
    """Initialize the source DB and build a disposable, data-free template.

    The configured ``DATABASE_URL`` may point at a developer's real local
    application database.  Cloning it would leak application rows (for
    example AI providers) into every supposedly isolated test and make local
    results differ from the empty PostgreSQL service used by CI.  The source
    database is still initialized for tests that intentionally use the normal
    application connection, but the per-test template is created empty and
    bootstrapped independently.
    """
    original_state = capture_database_state()
    source_url = database_core._DATABASE_URL
    if not database_core._USE_PG or not database_schema._USE_PG:
        pytest.fail("Backend tests require PostgreSQL; configure DATABASE_URL for the test service")
    validate_test_server_url(source_url)

    close_database_pool()
    template = None
    try:
        # The CI service starts with an empty application database.  Initialize
        # that source database first so tests that intentionally use the normal
        # application connection (rather than isolated_db) still see the full
        # PostgreSQL schema.
        switch_database(source_url, initialized=False)
        database.init_db()
        close_database_pool()

        # Never clone the configured application database: it may contain
        # developer data.  Create an empty database and initialize the complete
        # schema once; every isolated test then starts from this data-free
        # template while retaining the normal bootstrap seeds.
        template = create_test_database(
            source_url,
            purpose="schema_template",
        )
        switch_database(template.url, initialized=False)
        database.init_db()
        close_database_pool()
        yield template
    finally:
        close_temporary_test_connections()
        close_database_pool()
        restore_database_state(original_state)
        if template is not None:
            drop_test_database(template)


@pytest.fixture()
def isolated_db(_postgres_schema_template):
    """Provide a fresh, fully migrated PostgreSQL database to one test."""
    original_state = capture_database_state()
    close_database_pool()
    target = create_test_database(
        _postgres_schema_template.url,
        purpose="case",
        template_name=_postgres_schema_template.name,
    )
    try:
        # The cloned database already contains the complete schema and tracked
        # migration history, so init_db must remain guarded for this test.
        switch_database(target.url, initialized=True)
        yield {"module": database}
    finally:
        close_temporary_test_connections()
        close_database_pool()
        drop_test_database(target)
        restore_database_state(original_state)


@pytest.fixture()
def make_user(isolated_db):
    """Return a factory for inserting a test user into the isolated database."""

    def _factory(
        username: str,
        *,
        role: str = "Operator",
        change_groups: list[str] | None = None,
        mfa_enabled: bool = False,
        mfa_secret: str | None = None,
    ) -> dict:
        connection = database.get_db_connection()
        try:
            return _insert_user(
                connection,
                username=username,
                role=role,
                change_groups=change_groups,
                mfa_enabled=mfa_enabled,
                mfa_secret=mfa_secret,
            )
        finally:
            connection.close()

    return _factory


@pytest.fixture()
def requester(make_user):
    return make_user(
        "alice_requester",
        role="Operator",
        change_groups=["initial_reviewer"],
        mfa_enabled=True,
    )


@pytest.fixture()
def initial_reviewer(make_user):
    return make_user("bob_initial", role="Operator", change_groups=["initial_reviewer"])


@pytest.fixture()
def final_approver(make_user):
    return make_user("carol_final", role="Administrator", change_groups=["final_approver"])
