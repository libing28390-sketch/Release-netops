from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_baseline_manifest_is_reproducible_metadata_only() -> None:
    from knowledge_eval_baseline_manifest import build_manifest

    payload = build_manifest()
    assert payload["schema_version"] == 1
    assert payload["reproducibility"]["dataset"]["case_count"] == 50
    assert payload["reproducibility"]["dataset"]["sha256"]
    assert payload["components"]["chunker"]["config_sha256"]
    assert payload["components"]["embedding"]["distance_algorithm"] == "cosine"
    assert payload["evaluation"]["overall_status"] == "PASS"
    assert payload["evaluation"]["status"] == "PASS"
    assert payload["evaluation"]["safety_status"] == "PASS"
    assert payload["evaluation"]["quality_status"] == "PASS"
    assert payload["redaction"] == {
        "contains_prompt_or_answer": False,
        "contains_document_or_cli_content": False,
        "contains_secrets_or_credentials": False,
        "contains_tenant_or_user_identifiers": False,
    }

    rendered = json.dumps(payload, ensure_ascii=False).casefold()
    assert "postgresql://" not in rendered
    assert "raw_prompt" not in rendered
    assert "full_response" not in rendered
