import pytest

from api.playbooks import routes


def test_playbook_platform_aliases_normalize_huawei_variants():
    expected = {
        "huawei": "huawei_vrp",
        "huawei_vrpv8": "huawei_vrp",
        "vrp": "huawei_vrp",
        "ce": "huawei_vrp",
        "ce_vrp": "huawei_vrp",
        "ne": "huawei_vrp",
    }

    for alias, canonical in expected.items():
        assert routes._normalize_playbook_platform(alias) == canonical


@pytest.mark.asyncio
async def test_preview_playbook_uses_canonical_huawei_template(monkeypatch):
    monkeypatch.setattr(
        routes,
        "_all_scenarios",
        lambda: [
            {
                "id": "hw-test",
                "platform_phases": {
                    "huawei_vrp": {
                        "pre_check": ["display version"],
                        "execute": ["display current-configuration"],
                        "post_check": [],
                        "rollback": [],
                    }
                },
            }
        ],
    )

    result = await routes.preview_playbook(
        {
            "scenario_id": "hw-test",
            "platform": "huawei_vrpv8",
            "variables": {},
        }
    )

    assert result["requested_platform"] == "huawei_vrpv8"
    assert result["platform"] == "huawei_vrp"
    assert result["pre_check"] == ["display version"]
    assert result["execute"] == ["display current-configuration"]
