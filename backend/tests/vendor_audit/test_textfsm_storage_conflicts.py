import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest
from fastapi import HTTPException

from api import textfsm_templates as textfsm_api
from core import textfsm as textfsm_core


def _template(field: str) -> str:
    return f"""# nexora-action-code: get_version
Value {field} (\\S+)

Start
  ^${{{field}}}$$ -> Record
"""


def _create_body(filename: str, content: str) -> dict[str, str]:
    return {'filename': filename, 'content': content}


def _update_body(content: str, expected_content: str, source: str) -> dict[str, str]:
    return {
        'content': content,
        'expected_hash': sha256(expected_content.encode('utf-8')).hexdigest(),
        'expected_source': source,
    }


def test_huawei_legacy_catalog_prefers_canonical_and_save_cleans_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: None)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)
    canonical = tmp_path / 'huawei_vrp5_show_version.textfsm'
    legacy = tmp_path / 'huawei_vrp_show_version.textfsm'
    canonical.write_text(_template('CANONICAL'), encoding='utf-8')
    legacy.write_text(_template('LEGACY'), encoding='utf-8')

    item = next(
        entry for entry in textfsm_core.list_templates()
        if entry['filename'] == canonical.name
    )
    assert item['action_code'] == 'get_version'
    assert textfsm_core.get_template_content(canonical.name) == (
        _template('CANONICAL'), 'custom'
    )

    textfsm_core.save_custom_template('huawei_vrp_show_version.textfsm', _template('UPDATED'))
    assert canonical.read_text(encoding='utf-8') == _template('UPDATED')
    assert not legacy.exists()


def test_template_catalog_cache_refreshes_after_atomic_update_and_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: None)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)
    filename = 'cisco_ios_show_version.textfsm'

    assert textfsm_core.list_templates() == []
    textfsm_core.save_custom_template(filename, _template('VERSION'))
    created = next(item for item in textfsm_core.list_templates() if item['filename'] == filename)
    assert created['source'] == 'custom'
    assert created['action_code'] == 'get_version'

    textfsm_core.save_custom_template(filename, _template('UPDATED'), action_code='get_cpu')
    updated = next(item for item in textfsm_core.list_templates() if item['filename'] == filename)
    assert updated['action_code'] == 'get_cpu'

    assert textfsm_core.delete_custom_template(filename) is True
    assert textfsm_core.list_templates() == []

    external_filename = 'cisco_ios_show_interface_brief.textfsm'
    (tmp_path / external_filename).write_text(_template('PORT'), encoding='utf-8')
    time.sleep(textfsm_core._TEMPLATE_CATALOG_CACHE_TTL_SECONDS + 0.01)
    external_item = next(item for item in textfsm_core.list_templates() if item['filename'] == external_filename)
    assert external_item['action_code'] == 'get_version'


def test_delete_custom_template_removes_every_huawei_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    canonical = tmp_path / 'huawei_vrp5_show_version.textfsm'
    legacy = tmp_path / 'huawei_vrp_show_version.textfsm'
    canonical.write_text(_template('CANONICAL'), encoding='utf-8')
    legacy.write_text(_template('LEGACY'), encoding='utf-8')

    assert textfsm_core.delete_custom_template(legacy.name) is True
    assert not canonical.exists()
    assert not legacy.exists()


def test_create_rejects_existing_custom_but_allows_builtin_override(tmp_path, monkeypatch):
    builtin = tmp_path / 'builtin'
    custom = tmp_path / 'custom'
    builtin.mkdir()
    custom.mkdir()
    filename = 'huawei_vrp5_show_version.textfsm'
    (builtin / filename).write_text(_template('BUILTIN'), encoding='utf-8')
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', custom)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: builtin)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)

    result = textfsm_api.api_create_template(
        _create_body(filename, _template('CUSTOM')),
        _user={},
    )
    assert result['success'] is True
    assert textfsm_core.get_template_content(filename) == (_template('CUSTOM'), 'custom')

    with pytest.raises(HTTPException) as error:
        textfsm_api.api_create_template(
            _create_body(filename, _template('SECOND')),
            _user={},
        )
    assert error.value.status_code == 409


def test_template_detail_returns_content_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: None)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)
    content = _template('VERSION')
    textfsm_core.save_custom_template('cisco_ios_show_version.textfsm', content)

    result = textfsm_api.api_get_template('cisco_ios_show_version.textfsm', _user={})
    assert result['data']['content_hash'] == sha256(content.encode('utf-8')).hexdigest()
    assert result['data']['source'] == 'custom'


def test_put_checks_hash_and_allows_builtin_to_become_custom(tmp_path, monkeypatch):
    builtin = tmp_path / 'builtin'
    custom = tmp_path / 'custom'
    builtin.mkdir()
    custom.mkdir()
    filename = 'cisco_ios_show_version.textfsm'
    old_content = _template('VERSION')
    new_content = _template('UPDATED')
    (builtin / filename).write_text(old_content, encoding='utf-8')
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', custom)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: builtin)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)

    result = textfsm_api.api_update_template(
        filename,
        _update_body(new_content, old_content, 'builtin'),
        _user={},
    )
    assert result['success'] is True
    assert textfsm_core.get_template_content(filename) == (new_content, 'custom')


def test_put_rejects_stale_body_and_deleted_custom_even_if_builtin_hash_matches(tmp_path, monkeypatch):
    builtin = tmp_path / 'builtin'
    custom = tmp_path / 'custom'
    builtin.mkdir()
    custom.mkdir()
    filename = 'cisco_ios_show_version.textfsm'
    original = _template('VERSION')
    updated = _template('UPDATED')
    (builtin / filename).write_text(original, encoding='utf-8')
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', custom)
    monkeypatch.setattr(textfsm_core, '_get_builtin_templates_dir', lambda: builtin)
    monkeypatch.setattr(textfsm_core, '_get_packaged_templates_dir', lambda: None)
    textfsm_core.save_custom_template(filename, original)

    textfsm_api.api_update_template(
        filename,
        _update_body(updated, original, 'custom'),
        _user={},
    )
    with pytest.raises(HTTPException) as stale_error:
        textfsm_api.api_update_template(
            filename,
            _update_body(original, original, 'custom'),
            _user={},
        )
    assert stale_error.value.status_code == 409
    assert textfsm_core.get_template_content(filename) == (updated, 'custom')

    textfsm_core.delete_custom_template(filename)
    with pytest.raises(HTTPException) as deleted_error:
        textfsm_api.api_update_template(
            filename,
            _update_body(updated, original, 'custom'),
            _user={},
        )
    assert deleted_error.value.status_code == 409
    assert textfsm_core.get_template_content(filename) == (original, 'builtin')


def test_atomic_write_failure_keeps_previous_template(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)
    original = _template('VERSION')
    textfsm_core.save_custom_template('cisco_ios_show_version.textfsm', original)

    def fail_replace(*_args):
        raise OSError('replace failed')

    monkeypatch.setattr(textfsm_core.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='replace failed'):
        textfsm_core.save_custom_template(
            'cisco_ios_show_version.textfsm',
            _template('UPDATED'),
        )

    assert textfsm_core.get_template_content('cisco_ios_show_version.textfsm') == (
        original, 'custom'
    )
    assert not list(tmp_path.glob('*.tmp'))


def test_concurrent_create_has_one_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(textfsm_core, '_CUSTOM_TEMPLATES_DIR', tmp_path)

    def create(field: str):
        try:
            return textfsm_api.api_create_template(
                _create_body('cisco_ios_show_version.textfsm', _template(field)),
                _user={},
            )
        except HTTPException as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, ('VERSION_A', 'VERSION_B')))

    assert sum(isinstance(result, dict) and result['success'] for result in results) == 1
    conflicts = [result for result in results if isinstance(result, HTTPException)]
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409
