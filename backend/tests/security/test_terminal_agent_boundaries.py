from __future__ import annotations

import importlib.util
import io
import json
import ssl
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('terminal_agent_security', Path(__file__).parents[3] / 'scripts' / 'terminal_agent.py')
agent = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agent
spec.loader.exec_module(agent)


def test_agent_default_origin_policy_rejects_remote_backends(monkeypatch):
    monkeypatch.delenv('NEXORA_AGENT_ALLOWED_ORIGINS', raising=False)
    assert agent._backend_origin('http://127.0.0.1:5010/dashboard') == 'http://127.0.0.1:5010'
    with pytest.raises(PermissionError):
        agent._backend_origin('https://attacker.example')
    monkeypatch.setenv('NEXORA_AGENT_ALLOWED_ORIGINS', 'https://netops.example')
    assert agent._backend_origin('https://netops.example/path') == 'https://netops.example'


@pytest.mark.parametrize('filename', ['cmd.exe', 'powershell.exe', 'launcher.cmd', 'launcher.bat'])
def test_agent_rejects_arbitrary_program_paths(tmp_path, filename):
    path = tmp_path / filename
    path.write_text('test fixture; never execute')
    with pytest.raises(PermissionError):
        agent._resolve_executable('putty', str(path))
    valid = tmp_path / 'putty.exe'
    valid.write_text('test fixture; never execute')
    assert agent._resolve_executable('putty', str(valid)) == str(valid.resolve())


@pytest.mark.parametrize('origin,backend', [
    ('https://attacker.example', 'https://netops.example'),
    ('https://netops.example', 'https://other.example'),
])
def test_agent_checks_browser_origin_before_token_exchange(monkeypatch, origin, backend):
    monkeypatch.setenv('NEXORA_AGENT_ALLOWED_ORIGINS', 'https://netops.example,https://other.example')
    monkeypatch.setattr(agent, '_exchange_token', lambda *a: pytest.fail('Untrusted browser reached token exchange'))
    payload = json.dumps({'backend_url': backend, 'session_token': 'synthetic', 'client': 'putty'}).encode()
    handler = object.__new__(agent.AgentHandler)
    handler.path = '/v1/terminal/launch'
    handler.headers = {'Origin': origin, 'Content-Length': str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    responses = []
    handler._send = lambda status, body: responses.append((status, body))
    handler.do_POST()
    assert responses[0][0] == 400
    assert responses[0][1]['success'] is False


def test_agent_verifies_backend_tls_by_default(monkeypatch):
    monkeypatch.setenv('NEXORA_AGENT_ALLOWED_ORIGINS', 'https://netops.example')
    monkeypatch.delenv('NEXORA_AGENT_TLS_VERIFY', raising=False)
    seen = []
    def response(request, *, timeout, context):
        seen.append(context)
        return nullcontext(io.BytesIO(b'{"success":true}'))
    monkeypatch.setattr(agent, 'urlopen', response)
    agent._exchange_token('https://netops.example', 'synthetic')
    agent._web_json_request('https://netops.example/api/test', {})
    assert all(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname for context in seen)
    assert len(seen) == 2


@pytest.mark.parametrize('details', [
    {'ip': '192.0.2.1', 'user': '-oProxyCommand=bad', 'port': 22},
    {'ip': '-bad', 'user': 'operator', 'port': 22},
    {'ip': '192.0.2.1', 'user': 'operator', 'port': 70000},
])
def test_agent_rejects_ssh_option_injection(monkeypatch, details):
    monkeypatch.setattr(agent.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Invalid connection spawned process'))
    with pytest.raises(ValueError):
        agent._launch_client('standard', 'ssh', details)


def test_agent_passes_password_as_one_argument(monkeypatch):
    calls = []
    monkeypatch.setattr(agent.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    password = 'synthetic" & command'
    agent._launch_client('putty', 'putty.exe', {'ip': '192.0.2.1', 'user': 'operator', 'password': password, 'port': 22})
    assert calls[0][0][0][-1] == password
    assert not calls[0][1].get('shell')
