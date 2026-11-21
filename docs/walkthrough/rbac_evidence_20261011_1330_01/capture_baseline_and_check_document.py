"""Capture source hashes and verify local evidence links for the RBAC report."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

EVIDENCE_DIR = Path(__file__).resolve().parent
WORKSPACE = EVIDENCE_DIR.parents[2]
REPORT = WORKSPACE / "docs/walkthrough/walkthrough_20261011_1330_01_RBAC审核整改意见.md"
SOURCES = [
    "backend/main.py",
    "backend/core/api_security.py",
    "backend/core/rbac.py",
    "backend/api/users.py",
    "backend/api/access_scopes.py",
    "backend/services/access_scope_service.py",
    "backend/services/rack_scope_service.py",
    "backend/api/change_orders/core.py",
    "backend/api/change_orders/transition.py",
    "backend/api/change_orders/helpers.py",
    "backend/api/change_orders/schemas.py",
    "backend/api/playbooks/routes.py",
    "backend/api/playbooks/engine.py",
    "backend/services/playbook_execution_approval_service.py",
    "backend/services/playbook_version_service.py",
    "backend/services/platform_registry_service.py",
    "backend/api/automation.py",
    "backend/api/scheduled_jobs.py",
    "backend/services/config_approval_service.py",
    "backend/services/scheduler_service.py",
    "backend/services/automation_service.py",
    "backend/engine/orchestrator.py",
    "backend/engine/drivers/linux_driver.py",
    "backend/api/devices.py",
    "backend/services/operational_data_service.py",
    "backend/services/nsot_collection_preview_service.py",
    "backend/services/audit_service.py",
    "backend/database/schema.py",
    "backend/database/migrations/m0093_user_role_profiles.py",
    "backend/database/migrations/m0228_admin_tenant_assignment.py",
    "src/pages/UsersTab.tsx",
    "src/hooks/useAuth.ts",
    "src/App.tsx",
    "backend/tests/conftest.py",
    "backend/tests/pg_test_utils.py",
    "backend/tests/security/test_api_access_boundary.py",
    "backend/tests/security/test_audit_regressions.py",
    "backend/tests/security/test_user_tenant_assignment.py",
    "backend/tests/platform_registry/test_playbook_versions.py",
]


def git(*arguments):
    return subprocess.check_output(
        ["git", "-c", "core.quotePath=false", *arguments], cwd=WORKSPACE,
    ).decode("utf-8", errors="replace").strip()


def capture_baseline():
    baseline = {
        "captured_at": datetime.now().astimezone().isoformat(),
        "head": git("rev-parse", "HEAD"),
        "basis": "current worktree; source hashes captured at audit delivery, not an assertion of a clean HEAD checkout",
        "worktree_dirty": bool(git("status", "--short")),
        "sources": [],
    }
    for relative_path in SOURCES:
        source = WORKSPACE / relative_path
        data = source.read_bytes()
        baseline["sources"].append({
            "path": relative_path, "sha256": hashlib.sha256(data).hexdigest(),
            "line_count": len(data.decode("utf-8-sig").splitlines()),
        })
    baseline_path = EVIDENCE_DIR / "source_baseline.json"
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh-baseline", action="store_true",
        help="replace the original audit-time source hashes with hashes from the current worktree",
    )
    args = parser.parse_args()
    if args.refresh_baseline:
        capture_baseline()

    body = REPORT.read_text(encoding="utf-8")
    problems = []
    local_link_count = 0
    for label, target in re.findall(r"\[([^\]\n]+)\]\(([^)\n]+)\)", body):
        if target.startswith(("http://", "https://", "mailto:")) or target.startswith("#"):
            continue
        local_link_count += 1
        link_path = target.split("#", 1)[0]
        match = re.fullmatch(r"(.*?)(?::(\d+))?", link_path)
        path, line = match.groups()
        destination = Path(path)
        if not destination.is_absolute():
            destination = (REPORT.parent / destination).resolve()
        if not destination.is_file():
            problems.append({"label": label, "reason": "missing target", "target": target})
        elif line and int(line) > len(destination.read_text(encoding="utf-8-sig").splitlines()):
            problems.append({"label": label, "reason": "line out of range", "target": target})
    findings = re.findall(r"^### (F\d{2})：", body, re.MULTILINE)
    acceptance = re.findall(r"^\| (A\d{2}) \|", body, re.MULTILINE)
    assert findings == [f"F{number:02}" for number in range(1, 21)]
    assert acceptance == [f"A{number:02}" for number in range(1, 47)]
    checks = json.loads((EVIDENCE_DIR / "audit_checks.json").read_text(encoding="utf-8"))
    extra = json.loads((EVIDENCE_DIR / "additional_policy_probes.json").read_text(encoding="utf-8"))
    assert checks["pytest_exit_code"] == 0
    assert checks["pytest_passed"] == 76
    assert checks["dedicated_source_database_removed"] is True
    probe_count = len(checks["policy_probes"]) + len(extra["policy_probes"])
    assert probe_count == 14
    assert all(probe["reproduced"] for probe in checks["policy_probes"] + extra["policy_probes"])
    result = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "report": REPORT.relative_to(WORKSPACE).as_posix(),
        "report_sha256": hashlib.sha256(REPORT.read_bytes()).hexdigest(),
        "character_count": len(body), "source_count": len(SOURCES),
        "finding_count": len(findings), "acceptance_case_count": len(acceptance),
        "local_link_count": local_link_count, "policy_probe_count": probe_count,
        "pytest_passed": 76, "database_source_removed": True,
        "problems": problems,
    }
    (EVIDENCE_DIR / "document_checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
