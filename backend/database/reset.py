from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import core, schema


SYSTEM_DATABASES = {"postgres", "template0", "template1"}
REQUIRED_TABLES = {"credentials", "devices", "schema_migrations", "users"}


class DatabaseResetError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseTarget:
    backend: str
    host: str
    port: int | None
    database: str
    username: str


def _database_url() -> str:
    return getattr(core, "_DATABASE_URL", "").strip()


def backup_directory() -> Path:
    return Path(core.PROJECT_ROOT) / "data" / "backups" / "database-reset"


def parse_database_target(database_url: str) -> DatabaseTarget:
    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"postgresql", "postgres"}:
        raise DatabaseResetError("PostgreSQL DATABASE_URL is required")

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise DatabaseResetError("DATABASE_URL does not contain a target database name")
    return DatabaseTarget(
        backend="postgresql",
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=database,
        username=unquote(parsed.username or ""),
    )


def inspect_target() -> DatabaseTarget:
    target = parse_database_target(_database_url())
    connection = core._pg_connect(dsn=_database_url())
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            database, username = cursor.fetchone()
    finally:
        connection.close()

    if database.lower() in SYSTEM_DATABASES:
        raise DatabaseResetError(f"Refusing to reset protected PostgreSQL database: {database}")
    if database != target.database:
        raise DatabaseResetError(
            f"DATABASE_URL target mismatch: expected {target.database}, connected to {database}"
        )
    return DatabaseTarget(target.backend, target.host, target.port, database, username)


def _find_pg_dump() -> str | None:
    executable = shutil.which("pg_dump")
    if executable:
        return executable
    if os.name != "nt":
        return None
    candidates = glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe")
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0]


def create_backup(target: DatabaseTarget, backup_root: Path | None = None) -> Path:
    pg_dump = _find_pg_dump()
    if not pg_dump:
        raise DatabaseResetError("pg_dump was not found; database reset has been cancelled")

    parsed = urlparse(_database_url())
    backup_dir = backup_root or backup_directory()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{target.database}_{timestamp}.dump"
    command = [
        pg_dump,
        "--format=custom",
        "--file",
        str(backup_path),
        "--host",
        target.host,
        "--port",
        str(target.port or 5432),
        "--username",
        target.username,
        target.database,
    ]
    environment = os.environ.copy()
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    result = subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0:
        backup_path.unlink(missing_ok=True)
        detail = (result.stderr or result.stdout or "pg_dump failed").strip()
        raise DatabaseResetError(f"Database backup failed: {detail}")
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        backup_path.unlink(missing_ok=True)
        raise DatabaseResetError("Database backup did not produce a valid file")
    return backup_path


def _reset_postgresql_schema(target: DatabaseTarget) -> int:
    connection = core._pg_connect(dsn=_database_url())
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (target.database,),
            )
            terminated = sum(1 for row in cursor.fetchall() if row[0])
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
            cursor.execute("GRANT USAGE, CREATE ON SCHEMA public TO CURRENT_USER")
        return terminated
    finally:
        connection.close()


def _initialize_and_verify(target: DatabaseTarget) -> dict[str, Any]:
    schema._db_initialized = False
    schema.init_db()
    connection = core.get_db_connection()
    try:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
        table_names = {row[0] for row in rows}
        missing = sorted(REQUIRED_TABLES - table_names)
        if missing:
            raise DatabaseResetError(f"Database initialization is incomplete; missing tables: {', '.join(missing)}")
        admin = connection.execute("SELECT username, password FROM users WHERE username = ?", ("admin",)).fetchone()
        if not admin or not str(admin[1]).startswith("$2"):
            raise DatabaseResetError("Default administrator account was not initialized correctly")
        migration_count = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        return {"table_count": len(table_names), "migration_count": migration_count}
    finally:
        connection.close()


def reset_database(confirm_database: str, backup: bool = True) -> dict[str, Any]:
    target = inspect_target()
    if confirm_database != target.database:
        raise DatabaseResetError("The confirmation database name does not match the active database")

    backup_path: Path | None = None
    terminated_connections = 0
    if backup:
        backup_path = create_backup(target)
    terminated_connections = _reset_postgresql_schema(target)

    verification = _initialize_and_verify(target)
    return {
        "ok": True,
        "target": asdict(target),
        "backup_path": str(backup_path) if backup_path else "",
        "terminated_connections": terminated_connections,
        "verification": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely inspect or reset the NetOps database")
    parser.add_argument("action", choices=("inspect", "reset"))
    parser.add_argument("--confirm-database", default="")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            result: dict[str, Any] = {
                "ok": True,
                "target": asdict(inspect_target()),
                "config_source": str(Path(core.PROJECT_ROOT) / ".env"),
                "backup_directory": str(backup_directory()),
            }
        else:
            result = reset_database(args.confirm_database, backup=not args.no_backup)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
