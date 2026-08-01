from api.playbooks.builtin_scenarios import (
    BUILTIN_SCENARIOS,
    PLATFORMS,
    PLATFORM_SAVE_COMMANDS,
    PLATFORM_SHOW_RUNNING,
)
from api.playbooks.scenarios import (
    _normalize_playbook_platform,
    resolve_platform_phases,
)


def _domestic_inspection():
    return next(item for item in BUILTIN_SCENARIOS if item["id"] == "domestic-readonly-inspection")


def test_domestic_platforms_are_exposed_as_builtin_platforms():
    assert {"ruijie_rgos", "zte_zxros", "maipu", "dptech_conplat_fw"}.issubset(PLATFORMS)


def test_domestic_platform_aliases_resolve_to_their_own_family():
    expected = {
        "ruijie_os": "ruijie_rgos",
        "zxros": "zte_zxros",
        "mypower": "maipu",
        "dptech_ios": "dptech_conplat",
    }
    for alias, canonical in expected.items():
        assert _normalize_playbook_platform(alias) == canonical


def test_domestic_inspection_is_read_only_and_never_uses_cisco_phases():
    scenario = _domestic_inspection()
    assert scenario["variables"] == []
    for platform in scenario["supported_platforms"]:
        phases, resolved = resolve_platform_phases(scenario["platform_phases"], platform)
        assert resolved == platform
        assert phases["execute"] == []
        assert all(
            command.lower().startswith("show ")
            for command in phases["pre_check"]
        )


def test_domestic_snapshot_and_save_commands_are_explicit():
    assert PLATFORM_SAVE_COMMANDS["ruijie_rgos"] == "write"
    assert PLATFORM_SAVE_COMMANDS["zte_zxros"] == "write"
    assert PLATFORM_SAVE_COMMANDS["maipu"] is None
    assert PLATFORM_SAVE_COMMANDS["dptech_conplat_fw"] is None
    for platform in ("ruijie_rgos", "zte_zxros", "maipu", "dptech_conplat_fw"):
        assert PLATFORM_SHOW_RUNNING[platform] == "show running-config"
