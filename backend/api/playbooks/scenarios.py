# -*- coding: utf-8 -*-
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from database import get_db_connection
from core.platform_utils import normalize_device_platform
from .builtin_scenarios import BUILTIN_SCENARIOS

logger = logging.getLogger("api.playbooks.scenarios")


# Playbook definitions normally use a vendor/platform family key (for example
# ``huawei_vrp``), while assets may deliberately carry a more precise parser
# key (for example ``huawei_vrpv8``).  Keep the precise key first so a future
# platform-specific phase wins, and only fall back to the compatible family
# when the scenario has no dedicated block yet.
_PLAYBOOK_PLATFORM_ALIASES: dict[str, str] = {
    'cisco': 'cisco_ios',
    'ios': 'cisco_ios',
    'iosxe': 'cisco_xe',
    'cisco_iosxe': 'cisco_xe',
    'nxos': 'cisco_nxos',
    'nexus': 'cisco_nxos',
    'huawei': 'huawei_vrp',
    'vrp': 'huawei_vrp',
    'vrp5': 'huawei_vrp',
    'vrpv5': 'huawei_vrp',
    'vrp8': 'huawei_vrpv8',
    'vrpv8': 'huawei_vrpv8',
    'ce': 'huawei_vrp',
    'ce_vrp': 'huawei_vrp',
    'ne': 'huawei_vrp',
    'h3c': 'h3c_comware',
    'comware': 'h3c_comware',
    'comware5': 'hp_comware',
    'comware7': 'h3c_comware',
    'comware9': 'h3c_comware9',
    'juniper': 'juniper_junos',
    'junos': 'juniper_junos',
    'arista': 'arista_eos',
    'eos': 'arista_eos',
    'ruijie': 'ruijie_rgos',
    'rgos': 'ruijie_rgos',
}

_PLAYBOOK_PLATFORM_FALLBACKS: dict[str, tuple[str, ...]] = {
    'cisco_xe': ('cisco_ios',),
    'huawei_vrpv8': ('huawei_vrp',),
    'hp_comware': ('h3c_comware',),
    'h3c_comware9': ('h3c_comware',),
}

_PLAYBOOK_PHASE_KEYS = {'pre_check', 'execute', 'post_check', 'rollback'}


def _normalize_playbook_platform(platform: str | None, vendor: str | None = None) -> str:
    """Normalize a stored asset platform without collapsing supported variants."""
    raw = str(platform or '').strip().lower()
    if vendor and (not raw or raw in {'generic', 'cisco', 'cisco_ios'}):
        # Asset vendor is authoritative when a legacy row contains an empty or
        # stale Cisco platform value.
        normalized = normalize_device_platform(str(vendor), raw)
    else:
        normalized = raw
    return _PLAYBOOK_PLATFORM_ALIASES.get(normalized, normalized or 'cisco_ios')


def _playbook_platform_candidates(platform: str | None, vendor: str | None = None) -> list[str]:
    """Return exact platform first, followed by safe family fallbacks."""
    normalized = _normalize_playbook_platform(platform, vendor)
    candidates = [normalized]
    candidates.extend(_PLAYBOOK_PLATFORM_FALLBACKS.get(normalized, ()))
    # Keep the raw value as a last chance for custom scenarios using an alias
    # key that is not part of the built-in catalog.
    raw = str(platform or '').strip().lower()
    if raw and raw not in candidates:
        candidates.append(raw)
    return list(dict.fromkeys(candidates))


def resolve_platform_phases(
    platform_phases: dict,
    platform: str | None,
    vendor: str | None = None,
) -> tuple[dict, str]:
    """Resolve one device's phases from a scenario platform catalog.

    A plain ``pre_check/execute/...`` dictionary is treated as a custom
    single-platform playbook.  A platform catalog never falls back to Cisco;
    an unsupported device raises ``KeyError`` so the caller can report a
    device-level failure instead of sending a wrong command.
    """
    if not isinstance(platform_phases, dict):
        raise KeyError('platform phases must be an object')
    if _PLAYBOOK_PHASE_KEYS.intersection(platform_phases):
        return platform_phases, 'custom'

    for candidate in _playbook_platform_candidates(platform, vendor):
        phases = platform_phases.get(candidate)
        if isinstance(phases, dict):
            return phases, candidate
    raise KeyError(f"No playbook phases for platform '{platform or vendor or 'unknown'}'")


def resolve_platform_value(
    values: dict,
    platform: str | None,
    vendor: str | None = None,
    default=None,
):
    """Resolve a platform-keyed auxiliary command (save/snapshot, etc.)."""
    if not isinstance(values, dict):
        return default
    for candidate in _playbook_platform_candidates(platform, vendor):
        if candidate in values:
            return values[candidate]
    return default

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

