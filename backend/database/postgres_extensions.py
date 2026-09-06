"""Fail-closed PostgreSQL extension checks for database migrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


REQUIRED_V2_EXTENSIONS: tuple[str, ...] = ("vector", "pg_trgm")
OPTIONAL_V2_EXTENSIONS: tuple[str, ...] = ("pgcrypto",)


class PostgreSQLExtensionError(RuntimeError):
    """Base error with a stable code safe to expose in migration diagnostics."""

    def __init__(self, code: str, message: str, *, extension: str | None = None):
        super().__init__(message)
        self.code = code
        self.extension = extension


class ExtensionInspectionError(PostgreSQLExtensionError):
    def __init__(self, message: str):
        super().__init__("POSTGRES_EXTENSION_INSPECTION_FAILED", message)


class MissingPostgreSQLExtension(PostgreSQLExtensionError):
    def __init__(self, extension: str, message: str):
        super().__init__("POSTGRES_EXTENSION_MISSING", message, extension=extension)


class ExtensionInstallError(PostgreSQLExtensionError):
    def __init__(self, extension: str, message: str):
        super().__init__("POSTGRES_EXTENSION_INSTALL_FAILED", message, extension=extension)


@dataclass(frozen=True)
class ExtensionState:
    """Observed extension state without connection credentials or raw errors."""

    installed: Mapping[str, str]
    available: Mapping[str, str]
    missing: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing


def _normalise_names(names: Iterable[str]) -> tuple[str, ...]:
    normalised: list[str] = []
    for name in names:
        value = str(name or "").strip().lower()
        if not value or not value.replace("_", "").isalnum():
            raise ValueError(f"Invalid PostgreSQL extension name: {name!r}")
        if value not in normalised:
            normalised.append(value)
    if not normalised:
        raise ValueError("At least one PostgreSQL extension is required")
    return tuple(normalised)


def _placeholder_list(names: tuple[str, ...]) -> str:
    return ", ".join("?" for _ in names)


def inspect_extensions(cursor, *, names: Iterable[str] = REQUIRED_V2_EXTENSIONS) -> ExtensionState:
    """Inspect installed and available PostgreSQL extensions."""

    required = _normalise_names(names)
    placeholders = _placeholder_list(required)
    try:
        installed_rows = cursor.execute(
            f"SELECT extname, extversion FROM pg_extension WHERE extname IN ({placeholders})",
            required,
        ).fetchall()
        available_rows = cursor.execute(
            f"SELECT name, COALESCE(installed_version, default_version) "
            f"FROM pg_available_extensions WHERE name IN ({placeholders})",
            required,
        ).fetchall()
    except Exception as exc:  # do not leak DSN/credentials from driver errors
        raise ExtensionInspectionError(
            f"Unable to inspect PostgreSQL extensions; verify database permissions and server health ({type(exc).__name__})"
        ) from exc

    installed = {str(row[0]).lower(): str(row[1] or "") for row in installed_rows}
    available = {str(row[0]).lower(): str(row[1] or "") for row in available_rows}
    missing = tuple(name for name in required if name not in installed)
    return ExtensionState(
        installed=installed,
        available=available,
        missing=missing,
    )


def ensure_required_extensions(
    cursor,
    *,
    names: Iterable[str] = REQUIRED_V2_EXTENSIONS,
    create_missing: bool = True,
) -> ExtensionState:
    """Ensure required extensions exist, or raise an actionable safe error.

    ``CREATE EXTENSION`` is only attempted for the explicit allowlist supplied
    by the migration.  No arbitrary name or connection secret is interpolated.
    """

    required = _normalise_names(names)
    state = inspect_extensions(cursor, names=required)
    if not state.missing:
        return state
    if not create_missing:
        missing = ", ".join(state.missing)
        raise MissingPostgreSQLExtension(
            missing,
            f"Required PostgreSQL extensions are not installed: {missing}. "
            "Install the server packages (pgvector for vector; contrib for pg_trgm) and retry the migration.",
        )

    for name in state.missing:
        if name not in state.available:
            package = "pgvector" if name == "vector" else "the PostgreSQL contrib package"
            raise MissingPostgreSQLExtension(
                name,
                f"PostgreSQL extension '{name}' is unavailable on the server image. "
                f"Install {package}, restart PostgreSQL, then retry the migration.",
            )
        try:
            cursor.execute(f"CREATE EXTENSION IF NOT EXISTS {name}")
        except Exception as exc:  # avoid leaking DSN/credentials from driver errors
            raise ExtensionInstallError(
                name,
                f"PostgreSQL extension '{name}' is available but could not be installed. "
                f"Grant CREATE privilege or install it as a database administrator ({type(exc).__name__}).",
            ) from exc

    final_state = inspect_extensions(cursor, names=required)
    if final_state.missing:
        missing = ", ".join(final_state.missing)
        raise MissingPostgreSQLExtension(
            missing,
            f"PostgreSQL extension installation did not become visible: {missing}. "
            "Verify the target database and retry; V2 migration remains blocked.",
        )
    return final_state
