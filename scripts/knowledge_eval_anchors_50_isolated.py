#!/usr/bin/env python3
"""Run the 50-anchor Assistant benchmark in a disposable PostgreSQL database.

The normal 50-anchor runner intentionally exercises the configured
application corpus.  That is useful for production-like diagnostics, but a
mutable developer database makes two runs incomparable.  This wrapper
initializes a fresh PostgreSQL database, projects the checked-in official
templates/product registry, runs the existing Assistant benchmark unchanged,
and removes the temporary database afterwards.

It does not alter Gold labels or thresholds.  Human review remains a separate
requirement of the 50-anchor dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database  # noqa: E402
import database.core as database_core  # noqa: E402
import database.schema as database_schema  # noqa: E402
from backend.tests.pg_test_utils import (  # noqa: E402
    capture_database_state,
    close_database_pool,
    create_test_database,
    drop_test_database,
    restore_database_state,
    switch_database,
    validate_test_server_url,
)


def run(
    output_path: Path,
    *,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    if not database_core._USE_PG or not database_schema._USE_PG:
        raise RuntimeError("PostgreSQL DATABASE_URL is required")

    original_state = capture_database_state()
    source_url = database_core._DATABASE_URL
    validate_test_server_url(source_url)
    target = None
    try:
        target = create_test_database(source_url, purpose="anchors50_isolated")
        switch_database(target.url, initialized=False)
        database.init_db()
        close_database_pool()

        from services.official_product_catalog_service import ensure_official_product_registry_documents
        from services.official_template_projection_service import project_official_templates_to_knowledge

        project_official_templates_to_knowledge(
            tenant_id="tenant-default",
            created_by="system",
        )
        ensure_official_product_registry_documents(
            tenant_id="tenant-default",
            created_by="system",
        )

        import knowledge_eval_anchors_50_runner as runner

        runner.REPORT_PATH = output_path
        return runner.evaluate_anchors(
            dataset_path=dataset_path,
            report_path=output_path,
        )
    finally:
        close_database_pool()
        restore_database_state(original_state)
        if target is not None:
            drop_test_database(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="benchmark YAML to evaluate; defaults to the current signed frozen 50-anchor dataset",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "knowledge-engine" / "eval" / "eval-anchors-50-isolated-report.json",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="write the report but return success even when the benchmark fails",
    )
    args = parser.parse_args(argv)
    try:
        report = run(args.output, dataset_path=args.dataset)
    except Exception as exc:
        report = {
            "status": "NOT_READY",
            "safety_status": "NOT_READY",
            "quality_status": "NOT_READY",
            "overall_status": "NOT_READY",
            "database": "PostgreSQL",
            "database_mode": "isolated_temporary_database",
            "errors": [type(exc).__name__],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "50-anchor isolated benchmark: "
        f"overall={report.get('overall_status')} "
        f"safety={report.get('safety_status')} "
        f"quality={report.get('quality_status')} "
        f"passed={report.get('passed_cases', 0)}/{report.get('total_cases', 0)}"
    )
    if args.report_only:
        return 0
    return 0 if report.get("overall_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
