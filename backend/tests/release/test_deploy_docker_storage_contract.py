from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy-docker.sh"
ENV_EXAMPLE = ROOT / ".env.example"
DOCKER_DOC = ROOT / "docs" / "deploy" / "docker.md"
BASH = Path(r"C:\Program Files\Git\bin\bash.exe") if Path(r"C:\Program Files\Git\bin\bash.exe").exists() else Path("bash")


def _run_storage_contract(tmp_path: Path, storage_value: str) -> dict[str, object]:
    """Run the deploy script's real dotenv and Compose selection helpers."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_bytes(
        b"STORAGE_BACKEND="
        + storage_value.encode("utf-8")
        + b"\r\nNETOPS_REDIS_ENABLED=0\r\n"
    )
    harness = f"""
source {shlex.quote(SCRIPT.as_posix())}
COMPOSE_PROJECT_NAME=nexora
COMPOSE_FILES=()
printf 'normalized=%s\\n' "$(env_value STORAGE_BACKEND)"
printf 'is_s3=%s\\n' "$(storage_backend_is_s3 && printf yes || printf no)"
printf 'services_begin\\n'
compose_service_args
printf 'services_end\\n'
docker() {{
    printf 'docker_call'
    printf ' <%s>' "$@"
    printf '\\n'
}}
compose config --quiet
"""
    environment = os.environ.copy()
    environment["NETOPS_DOCKER_SCRIPT_SOURCE_ONLY"] = "1"
    try:
        result = subprocess.run(
            [str(BASH), "-c", harness, "storage-contract"],
            cwd=tmp_path,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AssertionError(
            f"deploy helper failed for {storage_value!r}:\n{exc.stdout}\n{exc.stderr}"
        ) from exc

    lines = result.stdout.splitlines()
    services_start = lines.index("services_begin") + 1
    services_end = lines.index("services_end")
    docker_line = next(line for line in lines if line.startswith("docker_call"))
    return {
        "normalized": next(line.split("=", 1)[1] for line in lines if line.startswith("normalized=")),
        "is_s3": next(line.split("=", 1)[1] for line in lines if line.startswith("is_s3=")),
        "services": lines[services_start:services_end],
        "docker_call": docker_line,
    }


def test_storage_backend_normalizes_dotenv_format_and_selects_profile(tmp_path):
    s3_values = [
        "s3",
        " s3 ",
        "'s3'",
        '"s3"',
        "  ' S3 '  ",
        ' \t"S3"\t\r',
    ]
    for index, value in enumerate(s3_values):
        result = _run_storage_contract(tmp_path / f"s3-{index}", value)
        assert result["normalized"].lower() == "s3"
        assert result["is_s3"] == "yes"
        assert "seaweedfs" in result["services"]
        assert "--profile" in result["docker_call"]
        assert "object-storage" in result["docker_call"]

    local_result = _run_storage_contract(tmp_path / "local", " \" local \" \r")
    assert local_result["normalized"] == "local"
    assert local_result["is_s3"] == "no"
    assert "seaweedfs" not in local_result["services"]
    assert "--profile" not in local_result["docker_call"]
    assert "object-storage" not in local_result["docker_call"]


def test_s3_examples_use_the_compose_network_and_document_required_settings():
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    docker_doc = DOCKER_DOC.read_text(encoding="utf-8")

    assert "S3_ENDPOINT_URL=http://seaweedfs:8333" in env_example
    assert "S3_ENDPOINT_URL" in docker_doc
    assert "S3_BUCKET" in docker_doc
    assert "S3_ACCESS_KEY_ID" in docker_doc
    assert "S3_SECRET_ACCESS_KEY" in docker_doc
    assert "docker compose up" in docker_doc
    assert "--profile object-storage" in docker_doc


def test_compose_startup_recovers_after_transient_netops_health_failure(tmp_path):
    script = SCRIPT.read_text(encoding="utf-8")
    assert "start_compose_services build" in script
    assert "start_compose_services offline" in script

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text("STORAGE_BACKEND=local\n", encoding="utf-8")
    harness = f"""
source {shlex.quote(SCRIPT.as_posix())}
compose_calls=0
compose() {{
    if [[ "$1" == "up" ]]; then
        compose_calls=$((compose_calls + 1))
        printf 'compose_up_%s' "$compose_calls"
        printf ' <%s>' "$@"
        printf '\\n'
        [[ "$compose_calls" -gt 1 ]]
        return
    fi
    if [[ "$1" == "ps" ]]; then
        printf 'fake-netops-id\\n'
        return 0
    fi
    return 1
}}
docker() {{
    [[ "$1" == "inspect" ]] || return 1
    printf 'healthy\\n'
}}
start_compose_services build db netops
"""
    environment = os.environ.copy()
    environment["NETOPS_DOCKER_SCRIPT_SOURCE_ONLY"] = "1"
    environment["NETOPS_STARTUP_RECOVERY_TIMEOUT_SECONDS"] = "4"
    result = subprocess.run(
        [str(BASH), "-c", harness, "startup-recovery-contract"],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout
    first_call = next(line for line in output.splitlines() if line.startswith("compose_up_1"))
    second_call = next(line for line in output.splitlines() if line.startswith("compose_up_2"))
    assert "--force-recreate" in first_call
    assert "--no-build" in second_call
    assert "<--pull> <never>" in second_call
    assert "--force-recreate" not in second_call
    assert "Startup recovery: netops health=healthy" in output
    assert "retrying Compose startup without rebuilding or pulling images" in output
