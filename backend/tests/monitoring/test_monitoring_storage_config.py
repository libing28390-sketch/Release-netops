"""Keep monitoring retention and disk safeguards aligned across deploy inputs."""

import re
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
    if variable == "VM_MIN_FREE_DISK_SPACE_BYTES":
        environment = COMPOSE["services"][service]["environment"]
        assert f"{variable}=${{{variable}:-{expected}}}" in environment
        supervisor = (ROOT / "monitoring/victoriametrics/supervisor.sh").read_text(encoding="utf-8")
        assert f'"-storage.minFreeDiskSpaceBytes=$launch_threshold"' in supervisor
        assert example_values()[variable] == expected
        return

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
    vm_environment = COMPOSE["services"]["victoriametrics"]["environment"]
    threshold_entry = next(item for item in vm_environment if item.startswith("VM_MIN_FREE_DISK_SPACE_BYTES="))
    expanded_threshold = re.sub(
        r"\$\{(\w+):-([^}]+)\}",
        lambda match: overrides.get(match[1], match[2]),
        threshold_entry,
    )
    assert expanded_threshold == f"VM_MIN_FREE_DISK_SPACE_BYTES={20 * 1024**3}"
    assert "-remoteWrite.maxDiskUsagePerURL=2GB" in expanded


def test_storage_safeguards_preserve_existing_persistent_volumes():
    assert "nexora-vmdata:/storage" in COMPOSE["services"]["victoriametrics"]["volumes"]
    assert "nexora-vmagent-queue:/var/lib/vmagent" in COMPOSE["services"]["vmagent"]["volumes"]
    assert COMPOSE["services"]["victoriametrics"]["image"].endswith(":v1.103.0")
    assert COMPOSE["services"]["vmagent"]["image"].endswith(":v1.103.0")


def test_storage_docs_explain_frontend_runtime_threshold_and_restart():
    guide = (ROOT / "docs/modules/realtime/features/monitoring/存储保留与磁盘保护.md").read_text(encoding="utf-8")
    assert "监控 → 采集器" in guide
    assert "保存并确认后" in guide
    assert "向 VictoriaMetrics 进程发送 SIGTERM" in guide
    assert "nexora-vm-runtime" in guide
    assert "VM_MIN_FREE_DISK_SPACE_BYTES" in guide
    assert "权限为 `0600`" in guide
    assert "install_vm_storage_env_sync.sh" in guide


def test_host_env_sync_does_not_mount_the_full_env_file_into_netops():
    netops_volumes = COMPOSE["services"]["netops"].get("volumes", [])
    assert not any(str(volume).startswith("./.env:") or str(volume).startswith(".env:") for volume in netops_volumes)
    assert (ROOT / "scripts/monitoring/sync_vm_storage_env.py").is_file()
    assert (ROOT / "scripts/monitoring/install_vm_storage_env_sync.sh").is_file()

    helper = (ROOT / "scripts/monitoring/sync_vm_storage_env.py").read_text(encoding="utf-8")
    assert 'ENV_KEY = b"VM_MIN_FREE_DISK_SPACE_BYTES"' in helper
    assert "os.replace(temporary, path)" in helper
