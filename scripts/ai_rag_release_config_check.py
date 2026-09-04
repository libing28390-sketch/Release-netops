#!/usr/bin/env python3
"""Validate the checked-in AI/RAG release configuration contract.

This gate reads only a dotenv example file.  It verifies safe disabled
defaults, bounded sidecar settings, and endpoint policy without printing any
configuration values or secret material.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / ".env.example"

REQUIRED_KEYS = frozenset(
    {
        "AI_ENABLED",
        "EXTERNAL_AI_ENABLED",
        "AI_KILL_SWITCH",
        "AI_PROVIDER_ALLOWLIST",
        "AI_DEBUG_PAYLOAD",
        "AI_EMBEDDING_MODE",
        "AI_EMBEDDING_DIMENSIONS",
        "AI_CONFIG_CLARIFICATION_ENABLED",
        "AI_CONFIG_CLARIFICATION_ROLLOUT_PERCENT",
        "AI_RERANKER_MODE",
        "AI_RERANKER_ENDPOINT",
        "AI_RERANKER_TIMEOUT_MS",
        "AI_PARSER_MODE",
        "AI_DOCUMENT_PARSER_MODE",
        "AI_DOCLING_BASE_URL",
        "AI_DOCLING_TIMEOUT_SECONDS",
        "AI_DOCLING_MAX_PAGES",
        "AI_OBSERVABILITY_MODE",
        "LANGFUSE_METADATA_ENDPOINT",
        "LANGFUSE_TIMEOUT_SECONDS",
        "NETWORK_WRITE_ENABLED",
        "PRODUCTION_CREDENTIALS_ALLOWED",
        "AI_GATEWAY_MODE",
        "DATA_CLASSIFICATION",
        "DEVICE_CREDENTIAL_SOURCE",
    }
)

SAFE_DEFAULTS = {
    "AI_ENABLED": "0",
    "EXTERNAL_AI_ENABLED": "0",
    "AI_KILL_SWITCH": "0",
    "AI_DEBUG_PAYLOAD": "0",
    "AI_RERANKER_MODE": "legacy",
    "AI_PARSER_MODE": "legacy",
    "AI_DOCUMENT_PARSER_MODE": "legacy",
    "AI_DOCLING_BASE_URL": "",
    "AI_OBSERVABILITY_MODE": "off",
    "NETWORK_WRITE_ENABLED": "0",
    "PRODUCTION_CREDENTIALS_ALLOWED": "0",
    "AI_GATEWAY_MODE": "offline",
    "DATA_CLASSIFICATION": "synthetic",
    "DEVICE_CREDENTIAL_SOURCE": "fixture",
}

_ALLOWED_ENDPOINT_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "reranker-sidecar", "docling", "docling-service", "langfuse", "netops"}
)
_SECRET_VALUE_MARKERS = re.compile(
    r"(?i)(?:sk_live_|sk-proj-|gho_|github_pat_|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"-----begin [^-]+ private key-----)"
)


class ConfigContractError(ValueError):
    """One or more release configuration contract checks failed."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a conservative dotenv subset and reject duplicate keys."""

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigContractError(f"line_{line_number}_missing_equals")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigContractError(f"line_{line_number}_invalid_key")
        if key in values:
            raise ConfigContractError(f"duplicate_key_{key.lower()}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _int_value(values: dict[str, str], key: str, errors: list[str], *, minimum: int, maximum: int) -> None:
    try:
        value = int(values.get(key, ""))
    except ValueError:
        errors.append(f"{key.lower()}_not_integer")
        return
    if not minimum <= value <= maximum:
        errors.append(f"{key.lower()}_out_of_range")


def _float_value(values: dict[str, str], key: str, errors: list[str], *, minimum: float, maximum: float) -> None:
    try:
        value = float(values.get(key, ""))
    except ValueError:
        errors.append(f"{key.lower()}_not_number")
        return
    if not minimum <= value <= maximum:
        errors.append(f"{key.lower()}_out_of_range")


def _validate_endpoint(values: dict[str, str], key: str, errors: list[str], *, allow_empty: bool = False) -> None:
    raw = values.get(key, "").strip()
    if not raw and allow_empty:
        return
    if not raw:
        errors.append(f"{key.lower()}_empty")
        return
    parsed = urlparse(raw)
    try:
        host = (parsed.hostname or "").lower()
        _ = parsed.port
    except ValueError:
        errors.append(f"{key.lower()}_malformed")
        return
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or host not in _ALLOWED_ENDPOINT_HOSTS
    ):
        errors.append(f"{key.lower()}_outside_allowlist")


def validate_mapping(values: dict[str, str]) -> None:
    """Validate release-safe defaults and bounded sidecar configuration."""

    errors: list[str] = []
    missing = sorted(REQUIRED_KEYS - values.keys())
    errors.extend(f"missing_{key.lower()}" for key in missing)
    if missing:
        raise ConfigContractError(";".join(errors))

    for key, expected in SAFE_DEFAULTS.items():
        if values.get(key, "").strip().lower() != expected.lower():
            errors.append(f"unsafe_default_{key.lower()}")
    if values.get("AI_PROVIDER_ALLOWLIST", "").strip() == "":
        errors.append("provider_allowlist_empty")
    if values.get("AI_EMBEDDING_MODE", "").strip().lower() not in {"local", "disabled"}:
        errors.append("embedding_mode_invalid")
    _int_value(values, "AI_EMBEDDING_DIMENSIONS", errors, minimum=0, maximum=16_384)
    _int_value(values, "AI_CONFIG_CLARIFICATION_ROLLOUT_PERCENT", errors, minimum=0, maximum=100)
    _int_value(values, "AI_RERANKER_TIMEOUT_MS", errors, minimum=1, maximum=5_000)
    _float_value(values, "AI_DOCLING_TIMEOUT_SECONDS", errors, minimum=0.01, maximum=60.0)
    _int_value(values, "AI_DOCLING_MAX_PAGES", errors, minimum=1, maximum=10_000)
    _float_value(values, "LANGFUSE_TIMEOUT_SECONDS", errors, minimum=0.01, maximum=60.0)
    if values.get("AI_OBSERVABILITY_MODE", "").strip().lower() not in {"off", "metadata"}:
        errors.append("observability_mode_invalid")
    if values.get("AI_RERANKER_MODE", "").strip().lower() not in {"legacy", "shadow", "active"}:
        errors.append("reranker_mode_invalid")
    parser_modes = {"legacy", "shadow", "docling", "active"}
    if values.get("AI_PARSER_MODE", "").strip().lower() not in parser_modes:
        errors.append("parser_mode_invalid")
    if values.get("AI_DOCUMENT_PARSER_MODE", "").strip().lower() not in parser_modes:
        errors.append("document_parser_mode_invalid")

    _validate_endpoint(values, "AI_RERANKER_ENDPOINT", errors)
    _validate_endpoint(values, "AI_DOCLING_BASE_URL", errors, allow_empty=True)
    _validate_endpoint(values, "LANGFUSE_METADATA_ENDPOINT", errors)

    rendered = "\n".join(f"{key}={value}" for key, value in values.items())
    if _SECRET_VALUE_MARKERS.search(rendered):
        errors.append("secret_pattern_detected")
    for secret_key in ("BGE_API_KEY", "AI_HASH_SALT", "VAULT_TOKEN"):
        if values.get(secret_key, "").strip():
            errors.append(f"secret_key_{secret_key.lower()}_must_not_be_literal")
    if errors:
        raise ConfigContractError(";".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args(argv)
    try:
        values = parse_env_file(args.file)
        validate_mapping(values)
    except (OSError, ConfigContractError) as exc:
        print(f"AI/RAG release config: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"AI/RAG release config: PASS (checked_keys={len(REQUIRED_KEYS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

