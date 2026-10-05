"""Keep monitoring retention and disk safeguards aligned across deploy inputs."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def example_values():
    return {
        key.strip(): value.strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }


@pytest.mark.parametrize(
    "service,flag,variable,expected",
    [
        ("victoriametrics", "retentionPeriod", "VM_RETENTION_PERIOD", "30d"),
        (
            "victoriametrics",
            "storage.minFreeDiskSpaceBytes",
            "VM_MIN_FREE_DISK_SPACE_BYTES",
            str(10 * 1024**3),
        ),
        ("vmagent", "remoteWrite.maxDiskUsagePerURL", "VMAGENT_MAX_DISK_USAGE", "1GB"),
    ],
)
def test_compose_defaults_match_example_disk_safeguards(service, flag, variable, expected):
    commands = COMPOSE["services"][service]["command"]
    entries = [entry for entry in commands if entry.startswith(f"-{flag}=")]
    assert entries == [f"-{flag}=${{{variable}:-{expected}}}"]
    assert example_values()[variable] == expected


def test_storage_safeguards_remain_environment_overridable():
    overrides = {
        "VM_RETENTION_PERIOD": "45d",
        "VM_MIN_FREE_DISK_SPACE_BYTES": str(20 * 1024**3),
        "VMAGENT_MAX_DISK_USAGE": "2GB",
    }
    commands = COMPOSE["services"]["victoriametrics"]["command"] + COMPOSE["services"]["vmagent"]["command"]
    expanded = [
        re.sub(r"\$\{(\w+):-([^}]+)\}", lambda match: overrides.get(match[1], match[2]), entry)
        for entry in commands
    ]
    assert "-retentionPeriod=45d" in expanded
    assert f"-storage.minFreeDiskSpaceBytes={20 * 1024**3}" in expanded
    assert "-remoteWrite.maxDiskUsagePerURL=2GB" in expanded


def test_storage_safeguards_preserve_existing_persistent_volumes():
    assert "nexora-vmdata:/storage" in COMPOSE["services"]["victoriametrics"]["volumes"]
    assert "nexora-vmagent-queue:/var/lib/vmagent" in COMPOSE["services"]["vmagent"]["volumes"]
    assert COMPOSE["services"]["victoriametrics"]["image"].endswith(":v1.103.0")
    assert COMPOSE["services"]["vmagent"]["image"].endswith(":v1.103.0")


@pytest.mark.parametrize("line_ending", ["\n", "\r\n"])
def test_documented_env_update_preserves_other_values_and_backs_up(tmp_path, line_ending):
    original = line_ending.join([
        "POSTGRES_PASSWORD=test-only value with spaces",
        "VM_RETENTION_PERIOD=90d",
        "VM_RETENTION_PERIOD=60d",
        "VMAGENT_MAX_DISK_USAGE=10GB",
        "# preserve this comment",
        "",
    ]).encode("utf-8")
    (tmp_path / ".env").write_bytes(original)
    guide = (ROOT / "docs/modules/realtime/features/monitoring/存储保留与磁盘保护.md").read_text(encoding="utf-8")
    script = re.search(r"python3 - <<'PY'\n(.*?)\nPY\n", guide, re.DOTALL)
    assert script is not None
    result = subprocess.run(
        [sys.executable, "-c", script[1]], cwd=tmp_path, capture_output=True, text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    updated = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=test-only value with spaces" in updated
    assert "# preserve this comment" in updated
    assert updated.count("VM_RETENTION_PERIOD=") == 1
    assert "VM_RETENTION_PERIOD=30d" in updated
    assert "VM_MIN_FREE_DISK_SPACE_BYTES=10737418240" in updated
    assert "VMAGENT_MAX_DISK_USAGE=1GB" in updated
    backups = list(tmp_path.glob(".env.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
