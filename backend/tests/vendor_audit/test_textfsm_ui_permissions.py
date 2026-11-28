from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api import textfsm_templates as textfsm_templates_api  # noqa: E402


def _list_templates_for(user):
    return textfsm_templates_api.api_list_templates(
        platform='',
        vendor='',
        platform_family='',
        version='',
        exact_platform=False,
        search='',
        source='',
        page=1,
        page_size=10,
        _user=user,
    )


def test_template_list_returns_effective_controls_for_operator_and_viewer(monkeypatch):
    monkeypatch.setattr(textfsm_templates_api, 'list_templates', lambda **_kwargs: [])

    operator = _list_templates_for({'role': 'Operator'})
    viewer = _list_templates_for({'role': 'Viewer'})

    assert operator['data']['permissions'] == {
        'can_create': True,
        'can_edit': True,
        'can_test': True,
        'can_delete': False,
    }
    assert viewer['data']['permissions'] == {
        'can_create': False,
        'can_edit': False,
        'can_test': False,
        'can_delete': False,
    }


def test_template_list_keeps_delete_control_administrator_only(monkeypatch):
    monkeypatch.setattr(textfsm_templates_api, 'list_templates', lambda **_kwargs: [])

    result = _list_templates_for({'role': 'Administrator'})

    assert result['data']['permissions'] == {
        'can_create': True,
        'can_edit': True,
        'can_test': True,
        'can_delete': True,
    }
