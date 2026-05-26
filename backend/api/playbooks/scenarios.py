# -*- coding: utf-8 -*-
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from database import get_db_connection
from .builtin_scenarios import BUILTIN_SCENARIOS

logger = logging.getLogger("api.playbooks.scenarios")

def _render_template(template: str, variables: dict) -> str:
    """Render playbook command templates using Jinja2 sandbox (safe, no eval)."""
    from jinja2.sandbox import SandboxedEnvironment
    env = SandboxedEnvironment()
    try:
        tmpl = env.from_string(template)
        return tmpl.render(**variables)
    except Exception:
        # Fallback: simple variable substitution only
        text = template
        for k, v in variables.items():
            text = text.replace('{{' + k + '}}', str(v))
        import re
        text = re.sub(r'\{%.*?%\}', '', text)
        text = re.sub(r'\{\{.*?\}\}', '', text)
        return text.strip()



def _render_phase_commands(phase_templates: list, variables: dict) -> list[str]:
    """Render a list of command templates into actual commands."""
    commands = []
    for tmpl in phase_templates:
        rendered = _render_template(tmpl, variables)
        # If the rendered block looks like a shell script, don't split it
        if rendered.strip().startswith('#!'):
            commands.append(rendered)
        else:
            for line in rendered.split('\n'):
                line = line.rstrip()
                if line:
                    commands.append(line)
    return commands


def _load_custom_scenarios() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT data_json FROM custom_scenarios ORDER BY created_at DESC').fetchall()
        scenarios: list[dict] = []
        for row in rows:
            try:
                scenario = json.loads(row['data_json'])
                if isinstance(scenario, dict):
                    scenario['is_custom'] = True
                    scenarios.append(scenario)
            except Exception:
                continue
        return scenarios
    finally:
        conn.close()


def _all_scenarios() -> list[dict]:
    return [*BUILTIN_SCENARIOS, *_load_custom_scenarios()]

