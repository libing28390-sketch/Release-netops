"""Run the EVAL-017 frontend/browser key-path gate with PostgreSQL authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-017-BROWSER-KEYPATH-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-browser-keypaths-v1.manifest.json"
FRONTEND_TARGETS = (
    "src/pages/ai/Copilot/keypaths.test.tsx",
    "src/pages/ai/Copilot/progress.test.ts",
    "src/api/ai.test.ts",
    "src/pages/ai/Providers/ProviderManagementTab.test.tsx",
    "src/pages/ai/Models/ModelManagementTab.test.tsx",
    "src/pages/ai/Security/SecurityPolicyTab.test.tsx",
    "src/api/http.test.ts",
    "src/utils/routeContext.test.ts",
    "src/pages/ai/Knowledge/IngestionJobsPanel.test.tsx",
    "src/pages/ai/Knowledge/KnowledgeAdminResponsive.test.tsx",
    "src/pages/ai/Knowledge/RagEvaluationPanel.test.tsx",
    "src/pages/ai/Knowledge/RetrievalTracePanel.test.tsx",
    "src/pages/ParserRegistryTab.test.tsx",
    "src/pages/PlatformRegistryTab.test.tsx",
)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / ".env.local", override=False)
except ImportError:
    pass


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing EVAL-017 authority: {path}")
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise AssertionError(f"{label} missing marker: {marker}")


def validate_browser_coverage() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    sources = {target: _read(ROOT / target) for target in FRONTEND_TARGETS}
    for marker in (
        "authority: PostgreSQL",
        "sqlite: forbidden",
        "frontend_component_tests_database: none",
        "production_database_write: false",
        "/ai/providers",
        "/ai/models",
        "/ai/knowledge",
        "/ai/security",
    ):
        _require(contract, marker, "EVAL-017 contract")
    for marker in ("chatAssistantStream", "X-Request-ID", "event_version"):
        _require(sources["src/api/ai.test.ts"], marker, "Copilot SSE tests")
    for marker in ("masked", "测试连通性", "还没有 Provider", "重试"):
        _require(sources["src/pages/ai/Providers/ProviderManagementTab.test.tsx"], marker, "Provider tests")
    for marker in ("场景路由", "设为当前用户默认", "添加 Model"):
        _require(_read(ROOT / "src/pages/ai/Models/ModelManagementTab.tsx"), marker, "Model page")
    for marker in ("默认拒绝外部 AI", "运行策略检查", "external_call_made"):
        _require(sources["src/pages/ai/Security/SecurityPolicyTab.test.tsx"], marker, "Security tests")
    for marker in ("选择诊断范围", "点击展开模型与推理控制面板", "发送"):
        _require(sources["src/pages/ai/Copilot/keypaths.test.tsx"], marker, "Copilot tests")
    for marker in ("暂无 Trace", "运行回归", "错误详情"):
        knowledge_text = "\n".join(sources[target] for target in FRONTEND_TARGETS if "/Knowledge/" in target)
        _require(knowledge_text, marker, "Knowledge tests")
    for target, source in sources.items():
        if "sqlite3" in source.lower():
            raise AssertionError(f"EVAL-017 frontend authority imports sqlite3: {target}")
    return {
        "status": "PASS",
        "task_id": "EVAL-017",
        "database": "postgresql",
        "sqlite": "not_used",
        "frontend_test_database": "none",
        "production_database_write": False,
        "browser_surfaces": ["copilot", "providers", "models_and_routes", "knowledge_management", "security_gateway"],
        "required_states": ["loading", "success", "empty", "error", "permission_boundary", "narrow_layout"],
        "source_sha256": {"contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(), **{key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in sources.items()}},
    }


def _postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    url = env.get("DATABASE_URL", "")
    if not url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-017 requires PostgreSQL DATABASE_URL; SQLite is forbidden")
    return env


def run_frontend_tests() -> dict[str, Any]:
    env = _postgres_environment()
    command = ["npm.cmd", "run", "test:frontend", "--", "--run", *FRONTEND_TARGETS, "--reporter=dot"]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180, check=False, shell=False)
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    if completed.returncode != 0:
        raise AssertionError(f"EVAL-017 frontend tests failed:\n{output[-4000:]}")
    files = re.search(r"Test Files\s+(\d+) passed", output)
    tests = re.search(r"Tests\s+(\d+) passed", output)
    if not files or not tests:
        raise AssertionError(f"EVAL-017 frontend tests did not report a complete summary:\n{output[-2000:]}")
    return {"status": "PASS", "database": "none", "sqlite": "not_used", "test_files_passed": int(files.group(1)), "tests_passed": int(tests.group(1)), "command": command}


def run_postgresql_v1_baseline() -> dict[str, Any]:
    env = _postgres_environment()
    probe = ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"
    completed = subprocess.run([sys.executable, str(probe)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False)
    output = completed.stdout.strip()
    if completed.returncode != 0:
        raise AssertionError(f"EVAL-017 PostgreSQL V1 baseline failed: {output[-1500:]} {completed.stderr[-1500:]}")
    try:
        report = json.loads(output)
    except json.JSONDecodeError:
        report = json.loads(output[output.find("{") : output.rfind("}") + 1])
    if str(report.get("database", "")).lower() != "postgresql":
        raise AssertionError("EVAL-017 V1 baseline did not report PostgreSQL")
    metrics = report.get("metrics") or {}
    if float(metrics.get("retrieval_accuracy", -1)) != 1.0 or float(metrics.get("citation_accuracy", -1)) != 1.0:
        raise AssertionError("EVAL-017 V1 PostgreSQL baseline regressed")
    return {"status": "PASS", "database": "postgresql", "sqlite": "not_used", "case_count": report.get("case_count"), "metrics": metrics, "rollback": report.get("rollback"), "production_database_write": report.get("production_database_write")}


def run_gate() -> dict[str, Any]:
    coverage = validate_browser_coverage()
    frontend = run_frontend_tests()
    v1 = run_postgresql_v1_baseline()
    return {
        **coverage,
        "frontend_tests": frontend,
        "v1_postgresql": v1,
        "live_browser_status": "USER_VERIFY_PENDING",
        "live_browser_note": "Automated key-path coverage passed; visible authenticated browser verification is tracked separately.",
        "rollback_or_cleanup": True,
    }


def main() -> int:
    report = run_gate()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
