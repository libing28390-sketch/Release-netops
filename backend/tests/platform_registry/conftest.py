from __future__ import annotations

import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2

import pytest

import database
import database.core as database_core
import database.schema as database_schema
from database.migrations.m0072_platform_registry_p0 import upgrade
from database.migrations.m0073_repair_platform_registry_command_seeds import upgrade as repair_upgrade
from database.migrations.m0074_playbook_version_snapshots import upgrade as playbook_upgrade
from database.migrations.m0075_custom_scenario_tenant_scope import upgrade as scenario_upgrade
from database.migrations.m0076_playbook_version_lifecycle import upgrade as version_lifecycle_upgrade
from database.migrations.m0077_playbook_execution_tenant_scope import upgrade as execution_scope_upgrade
from database.migrations.m0078_playbook_output_security import upgrade as output_security_upgrade
from database.migrations.m0079_quarantine_playbook_plaintext import upgrade as output_quarantine_upgrade
from database.migrations.m0080_parameterized_registry_actions import upgrade as parameterized_actions_upgrade
from database.migrations.m0081_platform_registry_constraints import upgrade as registry_constraints_upgrade
from database.migrations.m0082_extend_bgp_registry_actions import upgrade as bgp_actions_upgrade
from database.migrations.m0083_device_group_scope import upgrade as device_group_scope_upgrade
from database.migrations.m0084_repair_cisco_bgp_neighbor_commands import upgrade as cisco_bgp_upgrade
from database.migrations.m0085_system_profile_adaptation_status import upgrade as adaptation_status_upgrade
from database.migrations.m0086_parser_template_lifecycle_security import upgrade as parser_lifecycle_upgrade
from database.migrations.m0087_device_binding_scope_columns import upgrade as binding_scope_upgrade
from database.migrations.m0088_seed_domestic_platform_identification_rules import upgrade as identification_rules_upgrade
from database.migrations.m0089_playbook_execution_approvals import upgrade as approval_upgrade
from database.migrations.m0090_platform_registry_health_telemetry import upgrade as health_telemetry_upgrade
from database.migrations.m0091_platform_identification_conflicts import upgrade as identification_conflicts_upgrade


@pytest.fixture
def isolated_db():
    """Provide a disposable PostgreSQL database for every registry test."""
    if not database_core._USE_PG:
        pytest.fail("Platform registry acceptance tests require PostgreSQL")

    previous_url = database_core._DATABASE_URL
    previous_use_pg = database_core._USE_PG
    previous_schema_use_pg = database_schema._USE_PG
    previous_initialized = database_schema._db_initialized
    previous_pool = getattr(database_core, "_pg_pool", None)
    if previous_pool is not None:
        previous_pool.closeall()
    database_core._pg_pool = None

    parsed = urlparse(previous_url)
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    database_name = f"nexora_registry_test_{uuid.uuid4().hex[:12]}"
    temp_url = urlunparse(parsed._replace(path=f"/{database_name}"))

    admin = psycopg2.connect(admin_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        admin.close()

    database_core._DATABASE_URL = temp_url
    database_core._USE_PG = True
    database_schema._USE_PG = True
    database_schema._db_initialized = False

    seed_conn = psycopg2.connect(temp_url)
    try:
        with seed_conn.cursor() as cursor:
            cursor.execute(
                """CREATE TABLE devices (
                    id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT,
                    status TEXT, username TEXT, password TEXT, connection_method TEXT
                )"""
            )
            cursor.execute(
                """CREATE TABLE playbook_executions (
                    id TEXT PRIMARY KEY, results_json TEXT DEFAULT '{}',
                    device_ids TEXT DEFAULT '[]', phases_json TEXT DEFAULT '{}',
                    created_at TEXT, updated_at TEXT
                )"""
            )
        seed_conn.commit()
    finally:
        seed_conn.close()

    migration_conn = database.get_db_connection()
    try:
        cursor = migration_conn.cursor()
        upgrade(cursor, True)
        repair_upgrade(cursor, True)
        playbook_upgrade(cursor, True)
        scenario_upgrade(cursor, True)
        version_lifecycle_upgrade(cursor, True)
        execution_scope_upgrade(cursor, True)
        output_security_upgrade(cursor, True)
        output_quarantine_upgrade(cursor, True)
        parameterized_actions_upgrade(cursor, True)
        registry_constraints_upgrade(cursor, True)
        bgp_actions_upgrade(cursor, True)
        device_group_scope_upgrade(cursor, True)
        cisco_bgp_upgrade(cursor, True)
        adaptation_status_upgrade(cursor, True)
        parser_lifecycle_upgrade(cursor, True)
        binding_scope_upgrade(cursor, True)
        identification_rules_upgrade(cursor, True)
        approval_upgrade(cursor, True)
        health_telemetry_upgrade(cursor, True)
        identification_conflicts_upgrade(cursor, True)
        migration_conn.commit()
    finally:
        migration_conn.close()

    try:
        yield {"module": database}
    finally:
        temp_pool = getattr(database_core, "_pg_pool", None)
        if temp_pool is not None:
            temp_pool.closeall()
        database_core._pg_pool = None
        database_core._DATABASE_URL = previous_url
        database_core._USE_PG = previous_use_pg
        database_schema._USE_PG = previous_schema_use_pg
        database_schema._db_initialized = previous_initialized

        admin = psycopg2.connect(admin_url)
        admin.autocommit = True
        try:
            with admin.cursor() as cursor:
                cursor.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')
        finally:
            admin.close()
