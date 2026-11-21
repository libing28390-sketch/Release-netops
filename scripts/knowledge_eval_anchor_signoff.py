"""Freeze the source-reviewed 50-anchor candidate after explicit signoff.

This command is deliberately a metadata-only promotion step.  It does not
discover, invent, or rewrite Gold document IDs, acceptable sets, source URLs,
or feature annotations.  The caller must provide the reviewer's identity and
the review timestamp explicitly; the resulting dataset keeps the candidate's
parent and source-review evidence for auditability.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-source-reviewed-v2.yaml"
DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-v3-signed-20260905.yaml"
DEFAULT_DATASET_ID = "nexora-kb-eval-anchors-50-v3-signed-20260905"


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def _require_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    cases = candidate.get("cases")
    if not isinstance(cases, list) or len(cases) != 50:
        raise ValueError("the source-reviewed candidate must contain exactly 50 cases")
    if candidate.get("status") != "candidate":
        raise ValueError("signoff input must remain a candidate dataset")

    invalid: list[str] = []
    for case in cases:
        if not isinstance(case, dict):
            invalid.append("<non-mapping-case>")
            continue
        case_id = str(case.get("id") or "<missing-id>")
        outcome = str(case.get("expected_outcome") or "").strip().lower()
        # High-risk answer-shaped cases are safety guards.  They intentionally
        # have no Gold document set because the expected behavior is approval
        # interception, not retrieval.
        if outcome == "answer" and not case.get("high_risk"):
            required = ("vendor", "platform", "feature", "acceptable_document_ids", "source_review")
            missing = [field for field in required if not case.get(field)]
            if missing:
                invalid.append(f"{case_id}: missing {', '.join(missing)}")
    if invalid:
        raise ValueError("candidate is not ready for signoff: " + "; ".join(invalid))
    return cases


def _approve_source_review(source_review: dict[str, Any], reviewer: str, reviewed_at: str) -> None:
    source_review["status"] = "source_verified_human_approved"
    source_review["reviewer"] = reviewer
    source_review["reviewed_at"] = reviewed_at
    source_review["annotation_status"] = "approved"
    rationale = str(source_review.get("rationale") or "").strip()
    rationale = rationale.replace(
        "human signoff is still required.",
        "human signoff is recorded for this frozen dataset.",
    )
    if "human signoff" not in rationale.lower():
        rationale = (rationale + " Human signoff is recorded for this frozen dataset.").strip()
    source_review["rationale"] = rationale


def create_signed_dataset(
    candidate: dict[str, Any],
    *,
    reviewer: str,
    reviewed_at: str,
    dataset_id: str,
) -> dict[str, Any]:
    _require_candidate(candidate)
    signed = deepcopy(candidate)
    signed["dataset_id"] = dataset_id
    signed["parent_dataset_id"] = candidate.get("dataset_id")
    signed["status"] = "frozen"
    signed["review_mode"] = "official_source_provenance_automated_plus_user_signoff"
    signed["human_review_required"] = True
    signed["review_status"] = "approved"
    signed["source_review_status"] = "approved"
    signed["source_review_artifact"] = "eval-golden-anchors-50-source-review.json"
    signed["review_artifact"] = "eval-anchors-50-v3-signed-review.json"
    signed["reviewer"] = reviewer
    signed["reviewed_at"] = reviewed_at
    signed["annotation_status"] = "approved"
    signed["review_scope"] = "all_50_cases"
    signed["review_notes"] = [
        "The named reviewer approved all 50 query, outcome, Gold/acceptable-set, vendor/platform, feature, and safety annotations.",
        "This promotion records the explicit signoff; it does not claim that machine source checks were performed by a different person.",
        "The parent candidate and its official-source evidence are retained for traceability.",
    ]

    for case in signed["cases"]:
        case["reviewer"] = reviewer
        case["reviewed_at"] = reviewed_at
        case["annotation_status"] = "approved"
        source_review = case.get("source_review")
        if isinstance(source_review, dict):
            _approve_source_review(source_review, reviewer, reviewed_at)
    return signed


def write_signed_dataset(
    input_path: Path,
    output_path: Path,
    *,
    reviewer: str,
    reviewed_at: str,
    dataset_id: str = DEFAULT_DATASET_ID,
) -> dict[str, Any]:
    signed = create_signed_dataset(
        _load(input_path),
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        dataset_id=dataset_id,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(
            signed,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )
    return signed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reviewer", required=True, help="the actual reviewer's account or name")
    parser.add_argument("--reviewed-at", required=True, help="review timestamp in ISO-8601 format")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    args = parser.parse_args()
    signed = write_signed_dataset(
        args.input,
        args.output,
        reviewer=args.reviewer.strip(),
        reviewed_at=args.reviewed_at.strip(),
        dataset_id=args.dataset_id.strip(),
    )
    print(
        f"signed 50-anchor dataset: dataset_id={signed['dataset_id']} "
        f"cases={len(signed['cases'])} reviewer={signed['reviewer']} "
        f"reviewed_at={signed['reviewed_at']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
