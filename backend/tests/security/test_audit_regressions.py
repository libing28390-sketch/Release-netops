"""Regression coverage for authentication, privilege and code-execution boundaries."""
from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from api import setup, system, users
from ai.prompts.renderer import prompt_renderer
from ai.security.permissions import require_ai_permission
from core import rbac
from database import get_db_connection


def _session(make_user, *, role='Operator', mfa_enabled=False):
    actor = make_user('security_actor', role=role, mfa_enabled=mfa_enabled)
    users._store_session('audit-token', dict(actor, id=actor['user_id']))
    return actor, Request({'type': 'http', 'method': 'POST', 'path': '/',
                           'headers': [(b'authorization', b'Bearer audit-token')]})


@pytest.mark.parametrize('header', ['', 'Bearer invalid-token'])
def test_ai_anonymous_cannot_reach_privileged_handler(isolated_db, header):
    app = FastAPI()

    @app.post('/protected')
    def protected(user=Depends(require_ai_permission('ai.prompt.manage'))):
        pytest.fail('Unauthenticated request reached privileged handler')

    response = TestClient(app).post('/protected', headers={'Authorization': header})
    assert response.status_code == 401


def test_ai_role_checks_preserve_admin_and_deny_viewer(make_user):
    _session(make_user, role='Viewer')
    app = FastAPI()

    @app.get('/protected')
    def protected(user=Depends(require_ai_permission('ai.prompt.manage'))):
        return {'username': user['username']}

    client = TestClient(app)
    headers = {'Authorization': 'Bearer audit-token'}
    assert client.get('/protected', headers=headers).status_code == 403
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET role = 'Administrator' WHERE username = 'security_actor'")
        conn.commit()
    assert client.get('/protected', headers=headers).status_code == 200


def test_prompt_template_cannot_execute_python(monkeypatch):
    import os
    invoked = []
    monkeypatch.setattr(os, 'popen', lambda *args: invoked.append(args))
    payload = "{{ cycler.__init__.__globals__.os.popen('security-probe').read() }}"
    assert prompt_renderer.render(payload, {}) == payload
    assert not invoked
    assert prompt_renderer.render('{% for item in items %}{{ item }} {% endfor %}', {'items': ['a', 'b']}) == 'a b '


def test_sessions_use_current_identity_and_role(make_user):
    actor, _ = _session(make_user, role='Administrator')
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET role = 'Viewer', username = 'renamed_actor' WHERE id = ?", (actor['user_id'],))
        conn.commit()
    session = users.validate_session_token('audit-token')
    assert session['role'] == 'Viewer'
    assert session['username'] == 'renamed_actor'


@pytest.mark.parametrize('state', ['disabled', 'deleted', 'expired'])
def test_invalidated_sessions_are_rejected(make_user, state):
    actor, _ = _session(make_user)
    with get_db_connection() as conn:
        if state == 'deleted':
            conn.execute('DELETE FROM users WHERE id = ?', (actor['user_id'],))
        elif state == 'disabled':
            conn.execute("UPDATE users SET status = 'disabled' WHERE id = ?", (actor['user_id'],))
        else:
            conn.execute('UPDATE sessions SET created_at = ? WHERE token = ?', (time.time() - users._SESSION_TTL - 1024, 'audit-token'))
        conn.commit()
    assert users.validate_session_token('audit-token') is None


def test_profile_update_cannot_grant_approval_or_forge_actor(make_user, monkeypatch):
    actor, request = _session(make_user)
    events = []
    monkeypatch.setattr(users, 'log_audit_event', lambda **event: events.append(event))
    result = asyncio.run(users.update_user(actor['user_id'], request, {
        'username': 'admin', 'role': 'Administrator', 'role_profile': 'System Administrator',
        'change_groups': ['final_approver'], 'group_name': 'administrators',
        'actor_username': 'admin', 'actor_role': 'Administrator', 'display_name': 'New Name',
    }))
    assert result['username'] == actor['username']
    assert result['role'] == 'Operator'
    assert result['role_profile'] == ''
    assert result['change_groups'] == []
    assert result['group_name'] == ''
    assert result['display_name'] == 'New Name'
    assert events[-1]['actor_username'] == actor['username']
    assert events[-1]['actor_role'] == 'Operator'


@pytest.mark.parametrize('route', ['profile', 'setup'])
def test_password_change_revokes_other_sessions(make_user, route):
    actor, request = _session(make_user)
    users._store_session('stolen-token', dict(actor, id=actor['user_id']))
    if route == 'profile':
        asyncio.run(users.update_user(actor['user_id'], request, {'old_password': 'x', 'password': 'StrongNew!234'}))
    else:
        setup.setup_change_password(setup.ChangePasswordBody(current_password='x', new_password='StrongNew!234'),
                                    users.validate_session_token('audit-token'))
    assert users.validate_session_token('stolen-token') is None
    assert users.validate_session_token('audit-token') is not None


def test_authorization_denies_on_database_error(monkeypatch):
    import database
    def unavailable():
        raise RuntimeError('simulated database outage')
    monkeypatch.setattr(database, 'get_db_connection', unavailable)
    assert not rbac.authorize_resource({'user_id': 'actor', 'role': 'Operator'}, 'command', 'execute')
    assert not rbac.authorize_resource({'user_id': 'actor', 'role': 'Operator', 'role_profile': 'Automation Operator'}, 'command', 'execute')
    assert not rbac.authorize_resource({'role': 'Administrator', 'role_profile': 'unknown-profile'}, 'command', 'execute')


def test_mfa_setup_does_not_disclose_or_replace_enabled_secret(make_user):
    actor, request = _session(make_user, mfa_enabled=True)
    with pytest.raises(HTTPException) as error:
        users.mfa_setup(request)
    assert error.value.status_code == 409
    from backend.tests.conftest import current_test_totp
    replacement = users.generate_totp_secret()
    with pytest.raises(HTTPException) as error:
        users.mfa_enable(request, {'secret': replacement, 'code': current_test_totp(replacement)})
    assert error.value.status_code == 409
    with get_db_connection() as conn:
        assert conn.execute('SELECT mfa_secret FROM users WHERE id = ?', (actor['user_id'],)).fetchone()['mfa_secret'] == actor['mfa_secret']


def test_mfa_ticket_stops_after_five_guesses(make_user, monkeypatch):
    actor, request = _session(make_user, mfa_enabled=True)
    monkeypatch.setattr(users, '_temp_mfa_tokens', {'ticket': {'username': actor['username'], 'expires_at': time.time() + 300}})
    monkeypatch.setattr(users, 'verify_totp', lambda *a, **kw: False)
    for _ in range(5):
        with pytest.raises(HTTPException) as error:
            asyncio.run(users.mfa_verify(request, {'temp_token': 'ticket', 'code': '000000'}))
        assert error.value.status_code == 401
    assert 'ticket' not in users._temp_mfa_tokens
    with pytest.raises(HTTPException) as error:
        asyncio.run(users.mfa_verify(request, {'temp_token': 'ticket', 'code': '000000'}))
    assert error.value.status_code == 400


def _asset():
    with get_db_connection() as conn:
        conn.execute("INSERT INTO physical_assets (id, asset_type, hostname, management_ip, created_at, updated_at) VALUES ('audit-asset', 'server', 'audit-host', '192.0.2.10', '2026-09-11', '2026-09-11')")
        conn.commit()


def _credentials(monkeypatch):
    monkeypatch.setattr(system, 'resolve_device_credentials', lambda data: {'normal_username': 'netuser', 'normal_password': 'synthetic-password'})


def test_terminal_viewer_cannot_mint_credential_token(make_user):
    _, request = _session(make_user, role='Viewer')
    with pytest.raises(HTTPException) as error:
        asyncio.run(system.launch_terminal({'host': '192.0.2.10', 'app_type': 'putty'}, request))
    assert error.value.status_code == 403


def test_terminal_never_launches_server_process_and_token_is_single_use(make_user, monkeypatch):
    _, request = _session(make_user)
    _asset()
    _credentials(monkeypatch)
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('API launched a server process'))
    result = asyncio.run(system.launch_terminal({'host': '192.0.2.10', 'app_type': 'putty', 'path': __file__}, request))
    assert result['success'] and result['client_side']
    assert 'password' not in result
    # Concurrent redemption must yield credentials to exactly one caller.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: asyncio.run(system.exchange_token(result['session_token'])), range(2)))
    assert sum(bool(item['success']) for item in results) == 1
    assert next(item for item in results if item['success'])['password'] == 'synthetic-password'


def test_terminal_respects_explicit_resource_scope(make_user, monkeypatch):
    actor, request = _session(make_user)
    _asset()
    _credentials(monkeypatch)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at) VALUES ('audit-scope', ?, 'command', 'site', 'other-site', ?, '2026-09-11')",
                     (actor['user_id'], json.dumps(['execute'])))
        conn.commit()
    with pytest.raises(HTTPException) as error:
        asyncio.run(system.launch_terminal({'host': '192.0.2.10', 'app_type': 'putty'}, request))
    assert error.value.status_code == 403


def test_bootstrap_creates_default_admin_password(isolated_db, monkeypatch):
    from database.schema import _ensure_initial_administrator
    import bcrypt
    with get_db_connection() as conn:
        conn.execute('DELETE FROM users')
        monkeypatch.delenv('INITIAL_ADMIN_PASSWORD', raising=False)
        _ensure_initial_administrator(conn.cursor(), '2026-09-11')
        password_hash = conn.execute("SELECT password FROM users WHERE username = 'admin'").fetchone()['password']
        assert bcrypt.checkpw(b'admin', password_hash.encode())
        assert asyncio.run(users._verify_password('admin', password_hash))


def test_bootstrap_preserves_valid_admin_password_and_repairs_invalid_hash(isolated_db):
    from database.schema import _ensure_initial_administrator
    import bcrypt
    with get_db_connection() as conn:
        custom_hash = bcrypt.hashpw(b'ChangedByUser!234', bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password = ? WHERE username = 'admin'", (custom_hash,))
        _ensure_initial_administrator(conn.cursor(), '2026-09-11')
        assert conn.execute("SELECT password FROM users WHERE username = 'admin'").fetchone()['password'] == custom_hash

        conn.execute("UPDATE users SET password = 'legacy-custom-password' WHERE username = 'admin'")
        _ensure_initial_administrator(conn.cursor(), '2026-09-11')
        assert conn.execute("SELECT password FROM users WHERE username = 'admin'").fetchone()['password'] == 'legacy-custom-password'

        malformed_hash = '$2b$' + ('!' * 56)
        conn.execute("UPDATE users SET password = ? WHERE username = 'admin'", (malformed_hash,))
        _ensure_initial_administrator(conn.cursor(), '2026-09-11')
        repaired_hash = conn.execute("SELECT password FROM users WHERE username = 'admin'").fetchone()['password']
        assert bcrypt.checkpw(b'admin', repaired_hash.encode())


def test_bootstrap_creates_admin_when_other_users_exist(isolated_db, monkeypatch):
    from database.schema import _ensure_initial_administrator
    import bcrypt
    with get_db_connection() as conn:
        conn.execute("DELETE FROM users")
        conn.execute(
            "INSERT INTO users (id, username, password, role, status, created_at) "
            "VALUES ('existing-user', 'existing-user', 'legacy-password', 'Operator', 'active', '2026-09-11')"
        )
        monkeypatch.delenv('INITIAL_ADMIN_PASSWORD', raising=False)
        _ensure_initial_administrator(conn.cursor(), '2026-09-11')
        password_hash = conn.execute("SELECT password FROM users WHERE username = 'admin'").fetchone()['password']
        assert bcrypt.checkpw(b'admin', password_hash.encode())
        assert conn.execute("SELECT 1 FROM users WHERE username = 'existing-user'").fetchone()


def test_database_reset_uses_default_admin_without_password_env(monkeypatch):
    from database import reset
    target = reset.DatabaseTarget('postgresql', 'localhost', 5432, 'test-target', 'tester')
    monkeypatch.setattr(reset, 'inspect_target', lambda: target)
    monkeypatch.setattr(reset, '_reset_postgresql_schema', lambda *args: 0)
    monkeypatch.setattr(reset, '_initialize_and_verify', lambda _target: {'table_count': 1, 'migration_count': 1})
    monkeypatch.delenv('INITIAL_ADMIN_PASSWORD', raising=False)
    result = reset.reset_database('test-target', backup=False)
    assert result['ok'] is True
    assert result['verification']['migration_count'] == 1
