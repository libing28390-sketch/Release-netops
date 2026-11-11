"""Rehearse restoring current IPAM ledger rows into a fresh local PostgreSQL DB.

The rehearsal creates two disposable ``nexora_pytest_*`` databases, initializes
the current schema, dumps only current address-space/Prefix/IP/Pool tables, and
restores them into the fresh schema. It never connects to or writes the
configured application database and never reads historical observation tables.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from backend.tests.pg_test_utils import (  # noqa: E402
    capture_database_state,
    create_test_database,
    drop_test_database,
    restore_database_state,
    switch_database,
    validate_test_server_url,
)
from database import get_db_connection, init_db  # noqa: E402
from database.migrations import build_migration_plan, discover_migrations  # noqa: E402
from services.ipam_address_space_service import create_address_space  # noqa: E402
from services.ipam_service import create_address, create_pool, create_subnet  # noqa: E402


RESTORE_TABLES = (
    "public.ipam_address_spaces",
    "public.prefixes",
    "public.ip_addresses",
    "public.ipam_pools",
)


def _pg_client_env(database_url: str) -> tuple[dict[str, str], str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("Restore rehearsal requires a local PostgreSQL URL")
    validate_test_server_url(database_url)
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name.startswith("nexora_pytest_"):
        raise RuntimeError("Refusing pg_dump/pg_restore outside a disposable test database")

    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname
    env["PGPORT"] = str(parsed.port or 5432)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    for source_name, env_name in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        values = parse_qs(parsed.query).get(source_name)
        if values:
            env[env_name] = values[0]
    return env, database_name


def _client_binary(name: str) -> str:
    discovered = shutil.which(name)
    if discovered:
        return discovered
    windows_candidate = Path(r"C:\Program Files\PostgreSQL\18\bin") / f"{name}.exe"
    if windows_candidate.is_file():
        return str(windows_candidate)
    raise RuntimeError(f"Required PostgreSQL client is unavailable: {name}")


def _run_client(command: list[str], *, env: dict[str, str], label: str) -> None:
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise RuntimeError(f"{label} failed with exit code {result.returncode}: {error[-1500:]}")


def _ledger_snapshot() -> dict[str, list[tuple]]:
    with get_db_connection() as conn:
        return {
            "spaces": [
                tuple(row[key] for key in (
                    "id", "security_tenant_id", "name", "kind", "vrf_id", "status",
                ))
                for row in conn.execute(
                    """SELECT id, security_tenant_id, name, kind, vrf_id, status
                         FROM ipam_address_spaces ORDER BY id"""
                ).fetchall()
            ],
            "prefixes": [
                tuple(row[key] for key in (
                    "id", "prefix", "prefix_cidr", "tenant_id", "site_id",
                    "address_space_id", "vrf_id",
                ))
                for row in conn.execute(
                    """SELECT id, prefix, prefix_cidr, tenant_id, site_id,
                              address_space_id, vrf_id
                         FROM prefixes ORDER BY id"""
                ).fetchall()
            ],
            "addresses": [
                tuple(row[key] for key in (
                    "id", "subnet_id", "address", "address_space_id", "tenant_id", "status",
                ))
                for row in conn.execute(
                    """SELECT id, subnet_id, address, address_space_id, tenant_id, status
                         FROM ip_addresses ORDER BY id"""
                ).fetchall()
            ],
            "pools": [
                tuple(row[key] for key in (
                    "id", "prefix_id", "address_space_id", "start_ip", "end_ip",
                    "management_mode", "allocation_allowed",
                ))
                for row in conn.execute(
                    """SELECT id, prefix_id, address_space_id, start_ip, end_ip,
                              management_mode, allocation_allowed
                         FROM ipam_pools ORDER BY id"""
                ).fetchall()
            ],
        }


def _latest_schema_version() -> int:
    versions = [int(module.VERSION) for module in discover_migrations()]
    if not versions:
        raise RuntimeError("No versioned PostgreSQL migrations were discovered")
    return max(versions)


def _assert_latest_schema() -> int:
    latest_expected = _latest_schema_version()
    with get_db_connection() as conn:
        plan = build_migration_plan(conn, True)
        latest_applied = int(
            conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"]
        )
    if not plan.safe_for(strict_history=True) or plan.pending_versions:
        raise RuntimeError(
            f"Restored schema is not current: pending={plan.pending_versions}, "
            f"unknown={plan.unknown_applied_versions}, drift={plan.name_drift}"
        )
    if latest_applied != latest_expected:
        raise RuntimeError(
            f"Restored schema version {latest_applied} does not match {latest_expected}"
        )
    return latest_applied


def rehearse() -> dict:
    original_state = capture_database_state()
    validate_test_server_url(original_state.url)
    source = None
    target = None
    completed = False
    result: dict = {}
    try:
        source = create_test_database(original_state.url, purpose="ipam_restore_source")
        target = create_test_database(source.url, purpose="ipam_restore_target")

        switch_database(source.url, initialized=False)
        init_db()
        address_space = create_address_space(
            name=f"Restore rehearsal {uuid4().hex[:8]}",
            kind="global",
            vrf_id=None,
            security_tenant_id="tenant-default",
        )
        prefix = create_subnet(
            prefix="198.18.240.0/24",
            address_space_id=address_space["id"],
            tenant_id="tenant-default",
            name="Restore rehearsal mapped prefix",
        )
        create_address(
            prefix["id"], address="198.18.240.10", hostname="restore-rehearsal-host",
        )
        create_pool(
            name="Restore rehearsal external DHCP pool",
            prefix_id=prefix["id"],
            start_ip="198.18.240.20",
            end_ip="198.18.240.25",
            management_mode="external_dhcp",
            allocation_allowed=False,
        )
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO prefixes
                       (id, prefix, prefix_cidr, address_space_id, vrf_id, site_id,
                        tenant_id, status, name, created_at, updated_at)
                   VALUES (?, ?, ?, NULL, NULL, NULL, 'tenant-default', 'active',
                           'Restore rehearsal unmapped legacy Prefix', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                ("restore-rehearsal-unmapped", "198.18.241.0/24", "198.18.241.0/24"),
            )
            conn.commit()
        source_snapshot = _ledger_snapshot()
        if len(source_snapshot["prefixes"]) != 2 or len(source_snapshot["spaces"]) != 1:
            raise RuntimeError("Restore source is not the isolated two-Prefix fixture")
        if len(source_snapshot["addresses"]) != 1 or len(source_snapshot["pools"]) != 1:
            raise RuntimeError("Restore source contains unexpected IP or Pool rows")

        pg_dump = _client_binary("pg_dump")
        pg_restore = _client_binary("pg_restore")
        source_env, source_database = _pg_client_env(source.url)
        target_env, target_database = _pg_client_env(target.url)
        with tempfile.TemporaryDirectory(prefix="nexora-ipam-restore-") as temp_dir:
            dump_file = str(Path(temp_dir) / "current-ipam-ledger.dump")
            dump_command = [
                pg_dump,
                "--format=custom",
                "--data-only",
                "--no-owner",
                "--no-privileges",
                "--file",
                dump_file,
                "--dbname",
                source_database,
                *[f"--table={table}" for table in RESTORE_TABLES],
            ]
            _run_client(dump_command, env=source_env, label="pg_dump")

            switch_database(target.url, initialized=False)
            init_db()
            restore_command = [
                pg_restore,
                "--data-only",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--dbname",
                target_database,
                dump_file,
            ]
            _run_client(restore_command, env=target_env, label="pg_restore")

        # Re-run the app's normal schema bootstrap against the restored test DB.
        # Legacy prefix rows must remain pending; startup must not infer Global.
        from database import schema as database_schema

        database_schema._db_initialized = False
        init_db()
        restored_snapshot = _ledger_snapshot()
        if restored_snapshot != source_snapshot:
            raise RuntimeError("Restored current IPAM rows differ from the source ledger")
        if not any(
            row[0] == "restore-rehearsal-unmapped" and row[5] is None
            for row in restored_snapshot["prefixes"]
        ):
            raise RuntimeError("Unmapped restored Prefix was reassigned to an address space")
        version = _assert_latest_schema()
        result = {
            "status": "passed",
            "schema_version": version,
            "restored_spaces": len(restored_snapshot["spaces"]),
            "restored_prefixes": len(restored_snapshot["prefixes"]),
            "restored_formal_addresses": len(restored_snapshot["addresses"]),
            "restored_pools": len(restored_snapshot["pools"]),
            "unmapped_prefix_remained_pending": True,
            "dump_scope": list(RESTORE_TABLES),
            "historical_observation_tables_dumped": False,
            "configured_application_database_opened": False,
            "temporary_databases": [source.name, target.name],
        }
        completed = True
        return result
    finally:
        cleanup_errors = []
        try:
            restore_database_state(original_state)
        except Exception as exc:  # cleanup must still attempt to drop both test databases
            cleanup_errors.append(exc)
        for test_database in (target, source):
            if test_database is None:
                continue
            try:
                drop_test_database(test_database)
            except Exception as exc:
                cleanup_errors.append(exc)
        if not completed:
            print(
                json.dumps(
                    {"status": "failed", "temporary_databases_dropped": True},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
        if cleanup_errors:
            raise RuntimeError(
                f"Restore rehearsal cleanup failed for {len(cleanup_errors)} resource(s)"
            ) from cleanup_errors[0]


if __name__ == "__main__":
    print(json.dumps(rehearse(), ensure_ascii=False, indent=2))
