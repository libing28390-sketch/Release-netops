#!/usr/bin/env python3
"""Fail-closed validation for Nexora Knowledge Engine test configuration.

The validator deliberately understands only a small, safe configuration
contract.  It never prints values, and it rejects production mode, production
markers, literal secrets in config files, network writes, and non-mock AI
egress for the test profile.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ALLOWED_ENVIRONMENTS = {"development", "test", "shadow", "preprod"}
REQUIRED_FILE_KEYS = {
    "ENVIRONMENT",
    "DATABASE_URL",
    "REDIS_URL",
    "AI_GATEWAY_MODE",
    "AI_ENABLED",
    "EXTERNAL_AI_ENABLED",
    "NETWORK_WRITE_ENABLED",
    "PRODUCTION_CREDENTIALS_ALLOWED",
    "DATA_CLASSIFICATION",
    "DEVICE_CREDENTIAL_SOURCE",
}
SECRET_NAME_RE = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|DATABASE_URL|REDIS_URL)",
    re.IGNORECASE,
)
PRODUCTION_MARKER_RE = re.compile(r"(?:^|[._:/-])(prod(?:uction)?|live)(?:$|[._:/-])", re.IGNORECASE)
REFERENCE_RE = re.compile(r"^(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|(?:secret|vault)://[^\s]+)$")
PLACEHOLDER_MARKERS = (
    "replace-with",
    "change-me",
    "your_password",
    "your-password",
    "__change_me__",
    "test-only",
    "example",
    "dummy",
)


class PolicyError(ValueError):
    """One or more safe-configuration policy violations."""


def parse_env_text(text: str) -> dict[str, str]:
    """Parse a conservative dotenv subset without expanding variables."""

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise PolicyError(f"line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise PolicyError(f"line {line_number}: invalid key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _is_reference_or_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or bool(REFERENCE_RE.fullmatch(value.strip()))
        or any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    )


def _is_false(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "off", "no"}


def _has_production_marker(value: str) -> bool:
    return bool(PRODUCTION_MARKER_RE.search(value))


def _validate_url(key: str, value: str, errors: list[str]) -> None:
    if _has_production_marker(value):
        errors.append(f"{key}: production/live marker is forbidden")
    parsed = urlparse(value)
    if parsed.password and not _is_reference_or_placeholder(parsed.password):
        errors.append(f"{key}: literal URL password is forbidden")


def validate_mapping(
    values: dict[str, str], *, source: str = "file", expected_environment: str | None = None
) -> None:
    """Validate a file or runtime mapping; raise :class:`PolicyError` on failure."""

    errors: list[str] = []
    environment = values.get("ENVIRONMENT", "").strip().lower()
    if environment not in ALLOWED_ENVIRONMENTS:
        errors.append("ENVIRONMENT must be development, test, shadow, or preprod")
    if expected_environment and environment != expected_environment.lower():
        errors.append("ENVIRONMENT does not match the requested profile")

    if source == "file":
        missing = sorted(REQUIRED_FILE_KEYS - values.keys())
        errors.extend(f"missing required key: {key}" for key in missing)

    if values.get("AI_GATEWAY_MODE", "").strip().lower() not in {"mock", "sandbox", "offline"}:
        errors.append("AI_GATEWAY_MODE must be mock, sandbox, or offline")
    for key in (
        "NETWORK_WRITE_ENABLED",
        "PRODUCTION_CREDENTIALS_ALLOWED",
        "AI_ENABLED",
        "EXTERNAL_AI_ENABLED",
    ):
        if not _is_false(values.get(key)):
            errors.append(f"{key} must be explicitly false")
    if values.get("DATA_CLASSIFICATION", "").strip().lower() not in {"synthetic", "sanitized"}:
        errors.append("DATA_CLASSIFICATION must be synthetic or sanitized")
    if values.get("DEVICE_CREDENTIAL_SOURCE", "").strip().lower() not in {
        "fixture",
        "synthetic",
        "sandbox",
        "readonly",
    }:
        errors.append("DEVICE_CREDENTIAL_SOURCE must be fixture, synthetic, sandbox, or readonly")

    for key in ("DATABASE_URL", "REDIS_URL"):
        if key in values:
            _validate_url(key, values[key], errors)

    for key, value in values.items():
        if not SECRET_NAME_RE.search(key) or key in {
            "DATABASE_URL",
            "REDIS_URL",
            "PRODUCTION_CREDENTIALS_ALLOWED",
            "DEVICE_CREDENTIAL_SOURCE",
        }:
            continue
        if source == "file" and value and not _is_reference_or_placeholder(value):
            errors.append(f"{key}: literal secret/password is forbidden in a config file")
        if source == "runtime" and _has_production_marker(value):
            errors.append(f"{key}: production/live marker is forbidden")

    if errors:
        raise PolicyError("; ".join(errors))


def _read_values(args: argparse.Namespace) -> dict[str, str]:
    if args.file:
        return parse_env_text(Path(args.file).read_text(encoding="utf-8"))
    return {key: value for key, value in os.environ.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="dotenv-like candidate config; no secrets may be literal")
    parser.add_argument("--environment", required=True, choices=sorted(ALLOWED_ENVIRONMENTS))
    parser.add_argument("--source", choices=("file", "runtime"), default="file")
    args = parser.parse_args(argv)
    try:
        validate_mapping(_read_values(args), source=args.source, expected_environment=args.environment)
    except (OSError, PolicyError) as exc:
        print(f"KNOWLEDGE TEST CONFIG FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"KNOWLEDGE TEST CONFIG PASS: {args.environment} ({args.source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
