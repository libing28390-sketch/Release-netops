from backend.tests.pg_test_utils import postgresql_test_driver
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core import textfsm as textfsm_core  # noqa: E402
from api import textfsm_templates as textfsm_templates_api  # noqa: E402
from core.textfsm import (  # noqa: E402
    _parse_template_filename,
    _template_catalog_metadata,
    _template_platform_candidates,
    canonical_template_filename,
    get_template_content,
    resolve_textfsm_platform,
    resolve_textfsm_template_namespace,
    save_custom_template,
)
from database.migrations.m0102_concrete_system_template_scopes import (  # noqa: E402
    _scope_templates,
)


PLANNED_PLATFORM_METADATA = {
    'huawei_vrp5': ('huawei', 'huawei_vrp', 'v5'),
    'huawei_vrp8': ('huawei', 'huawei_vrp', 'v8'),
    'huawei_vrp_unknown': ('huawei', 'huawei_vrp', 'unknown'),
    'h3c_comware_v3': ('h3c', 'h3c_comware', 'v3'),
    'h3c_comware_v5': ('h3c', 'h3c_comware', 'v5'),
    'h3c_comware_v7': ('h3c', 'h3c_comware', 'v7'),
    'h3c_comware_v9': ('h3c', 'h3c_comware', 'v9'),
    'h3c_comware_unknown': ('h3c', 'h3c_comware', 'unknown'),
    'maipu_mypower_v6': ('maipu', 'maipu_mypower', 'v6'),
    'maipu_mypower_v8': ('maipu', 'maipu_mypower', 'v8'),
    'maipu_mypower_v9': ('maipu', 'maipu_mypower', 'v9'),
    'maipu_mypower_unknown': ('maipu', 'maipu_mypower', 'unknown'),
    'ruijie_rgos_v10': ('ruijie', 'ruijie_rgos', 'v10'),
    'ruijie_rgos_v11': ('ruijie', 'ruijie_rgos', 'v11'),
    'ruijie_rgos_v12': ('ruijie', 'ruijie_rgos', 'v12'),
    'ruijie_rgos_unknown': ('ruijie', 'ruijie_rgos', 'unknown'),
    'zte_zxros': ('zte', 'zte_zxros', 'common'),
    'zte_rosng': ('zte', 'zte_rosng', 'common'),
    'zte_os_unknown': ('zte', 'zte_os_unknown', 'common'),
    'dptech_conplat': ('dptech', 'dptech_conplat', 'common'),
    'dptech_conplat_unknown': ('dptech', 'dptech_conplat_unknown', 'common'),
}


@pytest.mark.parametrize('platform, expected', PLANNED_PLATFORM_METADATA.items())
def test_planned_template_platforms_keep_stable_catalog_metadata(platform, expected):
    info = _parse_template_filename(f'{platform}_show_version.textfsm')
    assert info is not None

    metadata = _template_catalog_metadata(info)
    assert (metadata['vendor'], metadata['platform_family'], metadata['version']) == expected


@pytest.mark.parametrize('platform', PLANNED_PLATFORM_METADATA)
def test_planned_template_platforms_are_first_class_parser_candidates(platform):
    candidates = _template_platform_candidates(platform)

    assert candidates[0] == platform
    assert resolve_textfsm_platform(platform)


def test_huawei_variant_keeps_command_canonicalization_when_saved_with_new_namespace():
    info = _parse_template_filename('huawei_vrp5_display_cpu_usage.textfsm')

    assert info == {
        'platform': 'huawei_vrp5',
        'command': 'display cpu-usage',
        'stem': 'huawei_vrp5_display_cpu_usage',
        'template_variant': 'v5',
    }


def test_legacy_huawei_vrp_templates_are_exposed_and_read_as_v5(tmp_path, monkeypatch):
    builtin = tmp_path / 'builtin'
    custom = tmp_path / 'custom'
    builtin.mkdir()
    custom.mkdir()
    content = """Value VERSION (\\S+)

Start
  ^Version: ${VERSION} -> Record
"""
    (builtin / 'huawei_vrp_show_version.textfsm').write_text(content, encoding='utf-8')

    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: builtin)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', custom)

    items = textfsm_core.list_templates(platform_filter='huawei_vrp', version_filter='v5')
    item = next(entry for entry in items if entry['command'] == 'show version')

    assert item['filename'] == 'huawei_vrp5_show_version.textfsm'
    assert item['version'] == 'v5'
    assert canonical_template_filename('huawei_vrp_show_version.textfsm') == item['filename']
    assert get_template_content(item['filename']) == (content, 'builtin')


def test_saving_legacy_huawei_vrp_name_writes_the_explicit_v5_name(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    content = """Value VERSION (\\S+)

Start
  ^Version: ${VERSION} -> Record
"""

    result = save_custom_template('huawei_vrp_show_version.textfsm', content)

    assert result['filename'] == 'huawei_vrp5_show_version.textfsm'
    assert (tmp_path / 'huawei_vrp5_show_version.textfsm').exists()
    assert not (tmp_path / 'huawei_vrp_show_version.textfsm').exists()


def test_textfsm_action_options_exclude_configuration_output_actions():
    result = textfsm_templates_api.api_textfsm_action_options(
        platform='ruijie_rgos_v11',
        _user={},
    )
    action_codes = {item['action_code'] for item in result['data']}

    assert 'get_running_config' not in action_codes
    assert 'get_startup_config' not in action_codes
    assert 'get_interface_brief' in action_codes


@pytest.mark.parametrize(
    ('platform_family', 'version', 'expected'),
    [
        ('huawei_vrp', 'v5', 'huawei_vrp5'),
        ('huawei_vrp', 'v8', 'huawei_vrp8'),
        ('h3c_comware', 'v3', 'h3c_comware_v3'),
        ('h3c_comware', 'v9', 'h3c_comware_v9'),
        ('maipu_mypower', 'v8', 'maipu_mypower_v8'),
        ('ruijie_rgos', 'v12', 'ruijie_rgos_v12'),
    ],
)
def test_template_namespace_uses_explicit_family_and_version(platform_family, version, expected):
    assert resolve_textfsm_template_namespace(
        platform_family,
        platform_family=platform_family,
        version=version,
    ) == expected


def test_template_namespace_keeps_legacy_common_maipu_namespace():
    assert resolve_textfsm_template_namespace(
        'maipu_mypower',
        platform_family='maipu_mypower',
        version='common',
    ) == 'maipu'


def test_saved_template_response_exposes_version_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    content = """Value VERSION (\\S+)

Start
  ^Version: ${VERSION} -> Record
"""

    result = save_custom_template('huawei_vrp8_show_version.textfsm', content)

    assert result['platform'] == 'huawei_vrp8'
    assert result['platform_family'] == 'huawei_vrp'
    assert result['vendor'] == 'huawei'
    assert result['version'] == 'v8'


def test_create_api_uses_explicit_version_to_build_template_filename(monkeypatch):
    captured = {}

    def fake_save(filename, content, *, action_code=None):
        captured.update(filename=filename, content=content, action_code=action_code)
        return {'filename': filename, 'version': 'v8'}

    monkeypatch.setattr(textfsm_templates_api, 'save_custom_template', fake_save)

    result = textfsm_templates_api.api_create_template(
        {
            'platform': 'huawei_vrp',
            'platform_family': 'huawei_vrp',
            'version': 'v8',
            'command': 'show version',
            'content': 'template content',
        },
        _user={},
    )

    assert captured['filename'] == 'huawei_vrp8_show_version.textfsm'
    assert result['data']['version'] == 'v8'


def test_scope_templates_allocates_around_existing_legacy_identity_conflict():
    conn = postgresql_test_driver.connect()
    conn.execute(
        '''
        CREATE TABLE parser_templates (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            platform_profile_id TEXT,
            platform_code TEXT,
            template_code TEXT,
            source_filename TEXT,
            command TEXT,
            name TEXT,
            source TEXT,
            status TEXT,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT,
            lock_version INTEGER
        )
        '''
    )
    conn.execute(
        '''
        CREATE UNIQUE INDEX uq_parser_templates_system_profile_code
        ON parser_templates(platform_code, COALESCE(platform_profile_id, ''), template_code)
        WHERE tenant_id IS NULL
        '''
    )
    rows = [
        (
            'legacy-source', None, 'profile-hp', 'h3c_comware', 'LEGACY_CODE',
            'h3c_comware_v5_display_bgp_peer_ipv4_unicast.textfsm',
            'display bgp peer ipv4 unicast', 'legacy', 'SYSTEM', 'ACTIVE',
            'system', 'now', 'now', 1,
        ),
        (
            'scoped-existing', None, 'profile-hp', 'h3c_comware',
            'HP_COMWARE__H3C_COMWARE_V5_DISPLAY_BGP_PEER_IPV4',
            'hp_comware__h3c_comware_v5_display_bgp_peer_ipv4_unicast.textfsm',
            'display bgp peer ipv4 unicast', 'existing', 'SYSTEM', 'ACTIVE',
            'system', 'now', 'now', 1,
        ),
    ]
    conn.executemany(
        'INSERT INTO parser_templates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        rows,
    )

    _scope_templates(
        conn.cursor(),
        [
            {
                'platform_code': 'hp_comware',
                'parser_platform': 'h3c_comware',
            }
        ],
        {'hp_comware': 'profile-hp'},
        '2026-08-26T00:00:00+00:00',
    )

    template_codes = [
        row[0]
        for row in conn.execute(
            "SELECT template_code FROM parser_templates ORDER BY id"
        ).fetchall()
    ]
    assert len(template_codes) == 2
    assert len(set(template_codes)) == 2
    assert any(code.startswith('HP_COMWARE__H3C_COMWARE_V5_DISPLAY_BGP_PEER_IPV4_') for code in template_codes)
