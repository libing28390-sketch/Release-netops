# -*- coding: utf-8 -*-
import json
import uuid
import logging
import re
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
    # Keep explicit parser/platform keys intact.  Resolution below can still
    # fall back from huawei_vrpv8 to the Huawei VRP family when needed.
    'vrp': 'huawei_vrp',
    'vrp5': 'huawei_vrp',
    'vrpv5': 'huawei_vrp',
    'vrp8': 'huawei_vrpv8',
    'vrpv8': 'huawei_vrpv8',
    'ce': 'huawei_vrp',
    'ce_vrp': 'huawei_vrp',
    'ne': 'huawei_vrp',
    'h3c': 'h3c_comware',
    'h3c_comware_v3': 'h3c_comware',
    'comware': 'h3c_comware',
    'juniper': 'juniper_junos',
    'junos': 'juniper_junos',
    'arista': 'arista_eos',
    'eos': 'arista_eos',
    'ruijie': 'ruijie_rgos',
    'rgos': 'ruijie_rgos',
    'ruijie_os': 'ruijie_rgos',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    'maipu_network': 'maipu',
    'maipu_mypower': 'maipu',
    'mypower': 'maipu',
    'dptech': 'dptech_conplat',
    'dptech_ios': 'dptech_conplat',
    'dptech_conplat_fw': 'dptech_conplat_fw',
}

_PHASE_NAMES = frozenset({'pre_check', 'execute', 'post_check', 'rollback'})
_ACTION_CODE_RE = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
_STEP_TYPE_RE = re.compile(r'^[a-z][a-z0-9_]{1,31}$')
_CONDITION_FIELD_RE = re.compile(r'^[a-z][a-z0-9_.-]{0,63}$')
MAX_PLAYBOOK_STEPS = 200
MAX_PLAYBOOK_REPEAT = 10
MAX_ACTION_PARAMETERS = 32
MAX_CONTROL_FLOW_DEPTH = 4
MAX_CONDITION_VALUE_LENGTH = 256
MAX_NOTIFICATION_TITLE_LENGTH = 120
MAX_NOTIFICATION_MESSAGE_LENGTH = 2_000
_SUPPORTED_STEP_TYPES = frozenset({'action', 'branch', 'notification', 'approval'})
_NOTIFICATION_SEVERITIES = frozenset({'critical', 'major', 'warning', 'info', 'low'})
_NOTIFICATION_FIELDS = frozenset({'type', 'title', 'message', 'severity'})
_APPROVAL_FIELDS = frozenset({'type', 'title', 'message', 'required_role'})
_APPROVAL_ROLES = frozenset({'Administrator'})
_CONDITION_SOURCES = frozenset({'variables', 'device'})
_CONDITION_OPERATORS = frozenset({
    'equals', 'not_equals', 'contains', 'starts_with', 'ends_with',
    'in', 'not_in', 'exists', 'not_exists',
})
_SAFE_DEVICE_CONDITION_FIELDS = frozenset({
    'id', 'hostname', 'ip_address', 'vendor', 'platform', 'site_id',
    'site', 'device_group_id', 'status', 'asset_type',
})


def _validate_condition(condition: object, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(condition, dict):
        errors.append({'path': path, 'code': 'INVALID_BRANCH_CONDITION'})
        return
    source = str(condition.get('source') or '').strip()
    field = str(condition.get('field') or '').strip()
    operator = str(condition.get('operator') or '').strip()
    if source not in _CONDITION_SOURCES:
        errors.append({'path': f'{path}.source', 'code': 'INVALID_CONDITION_SOURCE'})
    if not _CONDITION_FIELD_RE.fullmatch(field):
        errors.append({'path': f'{path}.field', 'code': 'INVALID_CONDITION_FIELD'})
    elif source == 'device' and field not in _SAFE_DEVICE_CONDITION_FIELDS:
        errors.append({'path': f'{path}.field', 'code': 'UNSAFE_DEVICE_CONDITION_FIELD'})
    if operator not in _CONDITION_OPERATORS:
        errors.append({'path': f'{path}.operator', 'code': 'INVALID_CONDITION_OPERATOR'})
        return
    value = condition.get('value')
    if operator in {'exists', 'not_exists'}:
        return
    if operator in {'in', 'not_in'}:
        if not isinstance(value, list) or not value or len(value) > 32:
            errors.append({'path': f'{path}.value', 'code': 'INVALID_CONDITION_VALUES'})
            return
        values = value
    else:
        values = [value]
    for item in values:
        if isinstance(item, (dict, list, tuple, set)) or item is None:
            errors.append({'path': f'{path}.value', 'code': 'INVALID_CONDITION_VALUE'})
            continue
        if len(str(item)) > MAX_CONDITION_VALUE_LENGTH:
            errors.append({'path': f'{path}.value', 'code': 'CONDITION_VALUE_TOO_LONG'})


def _validate_notification_step(step: dict, path: str, errors: list[dict[str, str]]) -> int:
    unexpected = set(step) - _NOTIFICATION_FIELDS
    if unexpected:
        errors.append({'path': path, 'code': 'INVALID_NOTIFICATION_FIELDS'})
    severity = str(step.get('severity') or '').strip().lower()
    if severity not in _NOTIFICATION_SEVERITIES:
        errors.append({'path': f'{path}.severity', 'code': 'INVALID_NOTIFICATION_SEVERITY'})
    for field, limit in (
        ('title', MAX_NOTIFICATION_TITLE_LENGTH),
        ('message', MAX_NOTIFICATION_MESSAGE_LENGTH),
    ):
        value = step.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append({'path': f'{path}.{field}', 'code': 'INVALID_NOTIFICATION_TEXT'})
        elif len(value) > limit or '\x00' in value:
            errors.append({'path': f'{path}.{field}', 'code': 'NOTIFICATION_TEXT_LIMIT_EXCEEDED'})
    return 1


def _validate_approval_step(step: dict, path: str, errors: list[dict[str, str]], depth: int, phase_name: str | None) -> int:
    unexpected = set(step) - _APPROVAL_FIELDS
    if unexpected:
        errors.append({'path': path, 'code': 'INVALID_APPROVAL_FIELDS'})
    if depth > 0:
        errors.append({'path': path, 'code': 'APPROVAL_STEP_MUST_BE_TOP_LEVEL'})
    if phase_name not in {'pre_check', 'execute'}:
        errors.append({'path': path, 'code': 'APPROVAL_PHASE_UNSUPPORTED'})
    required_role = str(step.get('required_role') or 'Administrator').strip()
    if required_role not in _APPROVAL_ROLES:
        errors.append({'path': f'{path}.required_role', 'code': 'INVALID_APPROVAL_ROLE'})
    for field, limit in (('title', MAX_NOTIFICATION_TITLE_LENGTH), ('message', MAX_NOTIFICATION_MESSAGE_LENGTH)):
        value = step.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append({'path': f'{path}.{field}', 'code': 'INVALID_APPROVAL_TEXT'})
        elif len(value) > limit or '\x00' in value:
            errors.append({'path': f'{path}.{field}', 'code': 'APPROVAL_TEXT_LIMIT_EXCEEDED'})
    return 1


def _validate_controlled_step(
    step: object,
    path: str,
    errors: list[dict[str, str]],
    depth: int,
    phase_name: str | None = None,
) -> int:
    if isinstance(step, str):
        errors.append({'path': path, 'code': 'RAW_COMMAND_DISABLED'})
        return 0
    if not isinstance(step, dict):
        errors.append({'path': path, 'code': 'INVALID_ACTION_STEP'})
        return 0

    step_type = str(step.get('type') or 'action').strip()
    if not _STEP_TYPE_RE.fullmatch(step_type) or step_type not in _SUPPORTED_STEP_TYPES:
        errors.append({'path': f'{path}.type', 'code': 'UNSUPPORTED_STEP_TYPE'})
        return 0

    if step_type == 'notification':
        return _validate_notification_step(step, path, errors)

    if step_type == 'approval':
        return _validate_approval_step(step, path, errors, depth, phase_name)

    if step_type == 'branch':
        if depth >= MAX_CONTROL_FLOW_DEPTH:
            errors.append({'path': path, 'code': 'CONTROL_FLOW_DEPTH_EXCEEDED'})
        _validate_condition(step.get('condition'), f'{path}.condition', errors)
        then_steps = step.get('then')
        else_steps = step.get('else', [])
        if not isinstance(then_steps, list):
            errors.append({'path': f'{path}.then', 'code': 'INVALID_BRANCH_STEPS'})
            then_steps = []
        if not isinstance(else_steps, list):
            errors.append({'path': f'{path}.else', 'code': 'INVALID_BRANCH_STEPS'})
            else_steps = []
        return 1 + sum(
            _validate_controlled_step(child, f'{path}.{branch_name}[{index}]', errors, depth + 1, phase_name)
            for branch_name, branch_steps in (('then', then_steps), ('else', else_steps))
            for index, child in enumerate(branch_steps)
        )

    action_code = str(step.get('action_code') or '').strip()
    if not _ACTION_CODE_RE.fullmatch(action_code):
        errors.append({'path': path, 'code': 'INVALID_ACTION_STEP'})
        return 0
    parameters = step.get('parameters')
    if parameters is not None and not isinstance(parameters, dict):
        errors.append({'path': path, 'code': 'INVALID_ACTION_PARAMETERS'})
    elif isinstance(parameters, dict) and len(parameters) > MAX_ACTION_PARAMETERS:
        errors.append({'path': path, 'code': 'ACTION_PARAMETER_LIMIT_EXCEEDED'})
    repeat = step.get('repeat', 1)
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        errors.append({'path': path, 'code': 'INVALID_REPEAT_COUNT'})
        repeat = 1
    elif repeat > MAX_PLAYBOOK_REPEAT:
        errors.append({'path': path, 'code': 'REPEAT_LIMIT_EXCEEDED'})
    return repeat


def validate_controlled_phases(phases: object) -> list[dict[str, str]]:
    """Validate bounded registry actions and deterministic branch steps."""
    errors: list[dict[str, str]] = []
    step_count = 0

    if not isinstance(phases, dict):
        return [{'path': 'phases', 'code': 'INVALID_PHASES'}]

    def visit_catalog(catalog: dict, path: str) -> None:
        nonlocal step_count
        for key, value in catalog.items():
            child_path = f'{path}.{key}'
            if key in _PHASE_NAMES:
                if not isinstance(value, list):
                    errors.append({'path': child_path, 'code': 'INVALID_PHASE_LIST'})
                    continue
                for index, step in enumerate(value):
                    step_count += _validate_controlled_step(step, f'{child_path}[{index}]', errors, 0, key)
            elif isinstance(value, dict):
                # Platform phase catalogs use one additional object layer
                # (for example ``{"cisco_ios": {"execute": [...]}}``).
                # Recurse through catalog metadata, never through step bodies.
                visit_catalog(value, child_path)

    visit_catalog(phases, 'phases')

    if step_count > MAX_PLAYBOOK_STEPS:
        errors.append({'path': 'phases', 'code': 'PLAYBOOK_STEP_LIMIT_EXCEEDED'})
    return errors


def extract_approval_steps(phases: object) -> list[dict[str, str]]:
    """Return top-level approval gates with stable paths for an execution."""
    approvals: list[dict[str, str]] = []

    def visit_catalog(catalog: object, path: str) -> None:
        if not isinstance(catalog, dict):
            return
        for key, value in catalog.items():
            child_path = f'{path}.{key}'
            if key in _PHASE_NAMES:
                if not isinstance(value, list):
                    continue
                for index, step in enumerate(value):
                    if not isinstance(step, dict) or str(step.get('type') or '').strip() != 'approval':
                        continue
                    approvals.append({
                        'step_path': f'{child_path}[{index}]',
                        'title': str(step.get('title') or '').strip()[:MAX_NOTIFICATION_TITLE_LENGTH],
                        'message': str(step.get('message') or '').strip()[:MAX_NOTIFICATION_MESSAGE_LENGTH],
                        'required_role': str(step.get('required_role') or 'Administrator').strip(),
                    })
            elif isinstance(value, dict):
                visit_catalog(value, child_path)

    visit_catalog(phases, 'phases')
    return approvals


def _condition_matches(condition: dict, *, variables: dict | None = None, device: dict | None = None) -> bool:
    """Evaluate the bounded branch condition grammar without dynamic code."""
    source = str(condition.get('source') or '').strip()
    field = str(condition.get('field') or '').strip()
    operator = str(condition.get('operator') or '').strip()
    context = variables if source == 'variables' else device if source == 'device' else {}
    exists = isinstance(context, dict) and field in context and context.get(field) is not None
    actual = context.get(field) if isinstance(context, dict) else None
    if operator == 'exists':
        result = exists
    elif operator == 'not_exists':
        result = not exists
    elif operator in {'in', 'not_in'}:
        values = condition.get('value') if isinstance(condition.get('value'), list) else []
        result = actual in values
        if operator == 'not_in':
            result = not result
    else:
        expected = condition.get('value')
        actual_text = '' if actual is None else str(actual)
        expected_text = '' if expected is None else str(expected)
        if operator == 'equals':
            result = actual_text == expected_text
        elif operator == 'not_equals':
            result = actual_text != expected_text
        elif operator == 'contains':
            result = expected_text in actual_text
        elif operator == 'starts_with':
            result = actual_text.startswith(expected_text)
        elif operator == 'ends_with':
            result = actual_text.endswith(expected_text)
        else:
            result = False
    return not result if bool(condition.get('negate')) else result


def select_controlled_steps(
    steps: object,
    *,
    variables: dict | None = None,
    device: dict | None = None,
    depth: int = 0,
) -> list:
    """Select bounded branch paths while preserving legacy non-action steps."""
    if not isinstance(steps, list):
        return []
    selected: list = []
    for step in steps:
        if not isinstance(step, dict) or str(step.get('type') or 'action').strip() != 'branch':
            selected.append(step)
            continue
        if depth >= MAX_CONTROL_FLOW_DEPTH:
            continue
        branch_name = 'then' if _condition_matches(step.get('condition') or {}, variables=variables, device=device) else 'else'
        selected.extend(select_controlled_steps(
            step.get(branch_name) or [],
            variables=variables,
            device=device,
            depth=depth + 1,
        ))
    return selected

_PLAYBOOK_PLATFORM_FALLBACKS: dict[str, tuple[str, ...]] = {
    'cisco_xe': ('cisco_ios',),
    'huawei_vrpv8': ('huawei_vrp',),
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
        # Controlled Playbook steps may reference a logical action instead of
        # carrying a raw command. The engine executes those through the
        # platform registry; they must not be rendered as shell text.
        if isinstance(tmpl, dict) and tmpl.get('action_code'):
            continue
        if not isinstance(tmpl, str):
            continue
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


def _load_custom_scenarios(tenant_id: str | None = None) -> list[dict]:
    conn = get_db_connection()
    try:
        if tenant_id:
            rows = conn.execute(
                'SELECT data_json FROM custom_scenarios WHERE tenant_id IS NULL OR tenant_id = ? ORDER BY created_at DESC',
                (tenant_id,),
            ).fetchall()
        else:
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


def _all_scenarios(tenant_id: str | None = None) -> list[dict]:
    return [*BUILTIN_SCENARIOS, *_load_custom_scenarios(tenant_id)]

