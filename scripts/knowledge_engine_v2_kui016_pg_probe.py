"""KUI-016 PostgreSQL acceptance probe.

Runs the fixed RAG baseline through the same service used by the API and
asserts that the response is bounded, tenant-labelled and metadata-only.
The underlying runner uses temporary tables and rolls the transaction back.
"""

from __future__ import annotations

import json

from services.knowledge_evaluation_service import get_evaluation_report, run_evaluation


def main() -> dict[str, object]:
    user = {"username": "kui016-probe", "role": "Administrator", "tenant_id": "tenant-kui016-probe"}
    report = run_evaluation(user)
    other = get_evaluation_report({**user, "tenant_id": "tenant-kui016-other"}, include_cases=False)
    serialized = json.dumps(report, ensure_ascii=False).lower()
    checks = {
        "postgresql": report.get("database") == "PostgreSQL",
        "passed": report.get("status") == "passed" and all(bool(item.get("passed")) for item in report.get("gates") or []),
        "bounded_cases": int(report.get("case_count") or 0) <= 200 and len(report.get("cases") or []) <= 200,
        "tenant_label": report.get("tenant_id") == "tenant-kui016-probe" and other.get("tenant_id") == "tenant-kui016-other",
        "no_production_write": report.get("production_database_write") is False,
        "transaction_rollback": report.get("rollback") == "transaction_rollback",
        "no_raw_leak": not any(marker in serialized for marker in ("debug", "expected_ids", "returned_ids", "select ", "chunk body")),
        "no_external_network": report.get("external_network_call") is False,
    }
    if not all(checks.values()):
        raise SystemExit(json.dumps(checks, ensure_ascii=False))
    return checks


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, sort_keys=True))
