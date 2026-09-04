"""Shared PostgreSQL fixtures for the backend test suite.

The backend test suite runs against PostgreSQL in every environment.  A
session-level schema template keeps the full bootstrap/migration cost bounded;
each test receives a disposable database cloned from that template so tests
can still mutate their database without sharing state.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

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


def _insert_user(
    connection,
    *,
    username: str,
    role: str,
    change_groups: list[str] | None,
) -> dict:
    user_id = str(uuid.uuid4())
    now = _utc_now_iso()
    connection.execute(
        """
        INSERT INTO users (
            id, username, password, role, status, created_at,
            group_name, change_groups_json, notification_channels,
            preferred_language, fixed_pin
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    connection.commit()
    return {"user_id": user_id, "username": username, "role": role}


@pytest.fixture(scope="session", autouse=True)
def _postgres_schema_template():
    """Initialize the source DB and a disposable template for this session."""
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

        # CREATE DATABASE ... TEMPLATE requires the source database to have no
        # active sessions.  Clone only after the complete migration history has
        # been committed; every isolated test then starts from the same schema.
        template = create_test_database(source_url, purpose="schema_template")
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
    ) -> dict:
        connection = database.get_db_connection()
        try:
            return _insert_user(
                connection,
                username=username,
                role=role,
                change_groups=change_groups,
            )
        finally:
            connection.close()

    return _factory


@pytest.fixture()
def requester(make_user):
    return make_user("alice_requester", role="Operator", change_groups=["initial_reviewer"])


@pytest.fixture()
def initial_reviewer(make_user):
    return make_user("bob_initial", role="Operator", change_groups=["initial_reviewer"])


@pytest.fixture()
def final_approver(make_user):
    return make_user("carol_final", role="Administrator", change_groups=["final_approver"])
