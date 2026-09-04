from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.ai_rag_release_config_check import ConfigContractError, parse_env_file, validate_mapping  # noqa: E402


def test_release_config_example_has_safe_defaults_and_bounded_endpoints():
    values = parse_env_file(ROOT / ".env.example")

    validate_mapping(values)


def test_release_config_rejects_active_default_and_external_endpoint():
    values = parse_env_file(ROOT / ".env.example")
    values["AI_RERANKER_MODE"] = "active"
    values["AI_RERANKER_ENDPOINT"] = "https://public.example.invalid/v1/rerank"

    with pytest.raises(ConfigContractError):
        validate_mapping(values)
