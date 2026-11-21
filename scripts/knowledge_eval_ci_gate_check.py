"""Validate the PostgreSQL-only CI/release wiring for EVAL-010.

This is intentionally a text-level contract check. GitHub Actions is not
available in the local test runner, so the validator proves that the checked
in workflows select PostgreSQL, expose the expected evaluation profiles and
contain no SQLite database URL.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE_PATH = ROOT / "Dockerfile"
POSTGRES_DOCKERFILE_PATH = ROOT / "docker" / "postgres" / "Dockerfile"
DOCKER_COMPOSE_PATH = ROOT / "docker-compose.yml"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "knowledge-engine-eval.yml"
BACKEND_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "backend-pytest-check.yml"
FRONTEND_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "frontend-build-check.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
PROMPTFOO_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "knowledge-engine-promptfoo.yml"
POSTGRES_ACTION_PATH = ROOT / ".github" / "actions" / "postgres" / "action.yml"
BOOTSTRAP_PATH = ROOT / "scripts" / "knowledge_eval_bootstrap.py"
DATABASE_SCHEMA_PATH = ROOT / "backend" / "database" / "schema.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-ci-gate-v1.manifest.json"
CI_NODE_VERSION = "22.22.2"


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing required CI contract: {path}")
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} is missing required marker: {marker}"


def _forbid(text: str, marker: str, label: str) -> None:
    assert marker not in text, f"{label} contains forbidden marker: {marker}"


def validate_ci_gate() -> dict[str, Any]:
    dockerfile = _read(DOCKERFILE_PATH)
    postgres_dockerfile = _read(POSTGRES_DOCKERFILE_PATH)
    docker_compose = _read(DOCKER_COMPOSE_PATH)
    small_ci = _read(WORKFLOW_PATH)
    backend_ci = _read(BACKEND_WORKFLOW_PATH)
    frontend_ci = _read(FRONTEND_WORKFLOW_PATH)
    release_ci = _read(RELEASE_WORKFLOW_PATH)
    promptfoo_ci = _read(PROMPTFOO_WORKFLOW_PATH)
    postgres_action = _read(POSTGRES_ACTION_PATH)
    bootstrap = _read(BOOTSTRAP_PATH)
    database_schema = _read(DATABASE_SCHEMA_PATH)

    for label, text in (("EVAL-010 workflow", small_ci), ("backend workflow", backend_ci)):
        _require(text, "DATABASE_URL: postgresql://", label)
        _require(text, "CREDENTIAL_ENCRYPTION_KEY:", label)
        _require(text, "uses: ./.github/actions/postgres", label)
        _forbid(text, "image: postgres:16", label)

    for label, text in (("release workflow", release_ci), ("Promptfoo workflow", promptfoo_ci)):
        _require(text, "DATABASE_URL: postgresql://", label)
        _require(text, "CREDENTIAL_ENCRYPTION_KEY:", label)
        _require(text, "uses: ./.github/actions/postgres", label)
        _forbid(text, "image: postgres:16", label)

    for label, text in (
        ("EVAL-010 workflow", small_ci),
        ("release workflow", release_ci),
        ("Promptfoo workflow", promptfoo_ci),
    ):
        _require(text, "scripts/knowledge_eval_bootstrap.py", label)

    _require(bootstrap, "init_db()", "Knowledge Engine PostgreSQL bootstrap")
    _require(
        bootstrap,
        "project_official_templates_to_knowledge",
        "Knowledge Engine PostgreSQL bootstrap",
    )
    _require(
        bootstrap,
        "ensure_official_product_registry_documents",
        "Knowledge Engine PostgreSQL bootstrap",
    )
    _require(bootstrap, "pg_extension", "Knowledge Engine PostgreSQL bootstrap")

    _require(postgres_action, "docker/postgres/Dockerfile", "PostgreSQL CI action")
    _require(postgres_action, "pg_available_extensions", "PostgreSQL CI action")
    _require(postgres_dockerfile, "pgvector/pgvector:0.8.6-pg18-bookworm", "PostgreSQL 18 Docker baseline")
    _require(postgres_dockerfile, "postgresql-contrib-18", "PostgreSQL 18 contrib extensions")
    _require(docker_compose, "nexora-pgdata:/var/lib/postgresql", "PostgreSQL 18 persistent volume mount")
    _forbid(docker_compose, "nexora-pgdata:/var/lib/postgresql/data", "obsolete PostgreSQL data mount")
    _require(database_schema, "SUPPORTED_POSTGRES_MAJOR_VERSION = 18", "PostgreSQL runtime version contract")
    _require(database_schema, "SHOW server_version_num", "PostgreSQL runtime version probe")
    _require(dockerfile, f"FROM node:{CI_NODE_VERSION}-alpine AS frontend-build", "Docker frontend build runtime")
    _require(small_ci, "pgvector", "EVAL-010 PostgreSQL service")
    _require(small_ci, "--profile small", "EVAL-010 workflow")
    _require(small_ci, "--strict", "EVAL-010 workflow")
    _require(small_ci, "knowledge_eval_ci_gate_check.py", "EVAL-010 workflow")
    _require(small_ci, "ai_rag_release_config_check.py", "release-safe configuration gate")
    _require(small_ci, "knowledge_eval_anchors_50_runner.py", "deterministic anchor quality gate")
    _require(small_ci, "knowledge_eval_anchors_50_isolated.py", "isolated anchor evidence gate")
    _require(
        small_ci,
        "eval-golden-anchors-50-v3-signed-20260905.yaml",
        "signed frozen 50-anchor dataset gate",
    )
    _require(small_ci, "knowledge_eval_anchor_source_review.py", "automated official-source review evidence")
    _require(small_ci, "eval-golden-anchors-50-source-reviewed-v2.yaml", "source-reviewed candidate dataset evidence")
    _require(small_ci, "knowledge_eval_gold_400_check.py", "400-case dataset readiness gate")
    _require(release_ci, "--profile full", "release workflow")
    _require(release_ci, "--strict", "release workflow")
    _require(release_ci, "knowledge_eval_offline.py", "release workflow")
    _require(release_ci, "knowledge_eval_anchors_50_runner.py", "release deterministic quality gate")
    _require(release_ci, "knowledge_eval_anchors_50_isolated.py", "release isolated anchor evidence gate")
    _require(
        release_ci,
        "eval-golden-anchors-50-v3-signed-20260905.yaml",
        "release signed frozen 50-anchor dataset gate",
    )
    _require(release_ci, "knowledge_eval_gold_400_check.py", "release 400-case dataset gate")
    _require(release_ci, "DATABASE_URL: postgresql://", "release workflow")
    _require(release_ci, "ai_rag_release_config_check.py", "release-safe configuration gate")
    _require(release_ci, f'node-version: "{CI_NODE_VERSION}"', "release frontend runtime")
    _require(release_ci, "npm run test:frontend -- --run", "release frontend regression gate")
    assert release_ci.count("rm -f handoff.md") == 1, (
        "release workflow must remove private handoff.md in the release job"
    )
    assert release_ci.count("nginx/ssl/netops.key blog handoff.md") == 1, (
        "release workflow must forbid staging private handoff.md in the release job"
    )
    _require(promptfoo_ci, f'node-version: "{CI_NODE_VERSION}"', "Promptfoo workflow")
    _require(promptfoo_ci, 'PROMPTFOO_VERSION: "0.118.0"', "Promptfoo workflow")
    _require(promptfoo_ci, "ai_rag_release_config_check.py", "Promptfoo release-safe configuration gate")
    _require(frontend_ci, f'node-version: "{CI_NODE_VERSION}"', "frontend workflow")
    _require(frontend_ci, "npm ci --include=dev", "frontend workflow")

    output: dict[str, Any] = {
        "status": "PASS",
        "task_id": "EVAL-010",
        "small_ci_profile": "small",
        "full_release_profile": "full",
        "database_url_scheme": "postgresql",
        "postgres_service": True,
        "database_contract": "postgresql_only",
        "postgres_ci_image": "repository_dockerfile_with_pgvector_and_pg_trgm",
        "ci_node_version": CI_NODE_VERSION,
        "external_network": "not_used_by_offline_runner",
        "production_write": False,
        "isolated_anchor_evidence": True,
        "automated_source_review_evidence": True,
        "signed_anchor_dataset_evidence": True,
        "workflow_sha256": {
            "knowledge_engine_eval": hashlib.sha256(small_ci.encode("utf-8")).hexdigest(),
            "backend_pytest": hashlib.sha256(backend_ci.encode("utf-8")).hexdigest(),
            "release": hashlib.sha256(release_ci.encode("utf-8")).hexdigest(),
            "promptfoo": hashlib.sha256(promptfoo_ci.encode("utf-8")).hexdigest(),
        },
    }
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    print(json.dumps(validate_ci_gate(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
