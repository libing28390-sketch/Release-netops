from __future__ import annotations

import json

import pytest

from services import alert_rule_service


@pytest.mark.parametrize(
    ('rule', 'context', 'expected'),
    [
        ({'scope_type': 'global', 'scope_value': ''}, {}, True),
        ({'scope_type': 'site', 'scope_value': 'HQ'}, {'site': 'HQ'}, True),
        ({'scope_type': 'site', 'scope_value': 'hq', 'scope_match_mode': 'contains'}, {'site': 'HQ-East'}, True),
        ({'scope_type': 'site', 'scope_value': 'west', 'scope_match_mode': 'contains'}, {'site': 'HQ-East'}, False),
        ({'scope_type': 'role', 'scope_value': 'core'}, {'role': 'core'}, True),
        ({'scope_type': 'role', 'scope_value': 'core', 'scope_match_mode': 'contains'}, {'role': 'core-switch'}, True),
        ({'scope_type': 'device', 'scope_value': '192.0.2.1'}, {'ip_address': '192.0.2.1'}, True),
        ({'scope_type': 'devices', 'scope_value': '["cmdb-1", "cmdb-2"]'}, {'device_id': 'cmdb-2', 'hostname': 'edge-2', 'ip_address': '192.0.2.2'}, True),
        ({'scope_type': 'devices', 'scope_value': '["cmdb-1"]'}, {'device_id': 'cmdb-2', 'hostname': 'cmdb-1', 'ip_address': '192.0.2.1'}, False),
        ({'scope_type': 'devices', 'scope_value': 'not-json'}, {'device_id': 'cmdb-1'}, False),
        ({'scope_type': 'interface', 'scope_value': 'ge-0/0/1'}, {'interface_name': 'ge-0/0/1'}, True),
    ],
)
def test_simple_rule_scope_matching(rule, context, expected):
    assert alert_rule_service._scope_matches(rule, context) is expected


def test_composite_scope_uses_exact_and_fuzzy_and_matching():
    exact = {
        'scope_type': 'composite',
        'scope_match_mode': 'exact',
        'scope_value': json.dumps({'site': 'HQ', 'role': 'core', 'category': 'Network', 'platform': 'ios', 'interface': 'Gi0/1'}),
    }
    context = {
        'site': 'HQ',
        'role': 'core',
        'category': 'Network',
        'platform': 'ios',
        'interface_name': 'Gi0/1',
    }
    assert alert_rule_service._scope_matches(exact, context)
    assert not alert_rule_service._scope_matches(exact, {**context, 'platform': 'nxos'})

    fuzzy = {**exact, 'scope_match_mode': 'contains', 'scope_value': json.dumps({'site': 'h', 'role': 'co', 'platform': 'io', 'interface': 'Gi'})}
    assert alert_rule_service._scope_matches(fuzzy, context)
    assert not alert_rule_service._scope_matches(fuzzy, {**context, 'role': 'access'})


def test_ip_scope_is_exact_and_accepts_delimited_values():
    rule = {'scope_type': 'ip', 'scope_value': '192.0.2.1, 192.0.2.2\n192.0.2.3'}
    assert alert_rule_service._scope_matches(rule, {'ip_address': '192.0.2.2'})
    assert not alert_rule_service._scope_matches(rule, {'ip_address': '192.0.2.20'})
    assert not alert_rule_service._scope_matches({'scope_type': 'ip', 'scope_value': '[]'}, {'ip_address': '192.0.2.1'})


def test_tag_scope_reuses_nested_and_or_not_expression():
    expression = {
        'operator': 'and',
        'negated': False,
        'tag_ids': ['production'],
        'groups': [
            {'operator': 'or', 'negated': False, 'tag_ids': ['network', 'datacenter'], 'groups': []},
            {'operator': 'and', 'negated': True, 'tag_ids': ['maintenance'], 'groups': []},
        ],
    }
    rule = {'scope_type': 'tag', 'scope_value': json.dumps({'version': 2, 'expression': expression})}
    assert alert_rule_service._scope_matches(rule, {'tag_ids': {'production', 'network'}})
    assert not alert_rule_service._scope_matches(rule, {'tag_ids': {'production', 'network', 'maintenance'}})
    assert not alert_rule_service._scope_matches(rule, {'tag_ids': {'production'}})
    assert not alert_rule_service._scope_matches(rule, {})


@pytest.mark.parametrize(
    ('scope_type', 'scope_value'),
    [
        ('composite', '{}'),
        ('composite', 'not-json'),
        ('tag', '{"expression":{"operator":"and","tag_ids":[],"groups":[]}}'),
        ('tag', 'not-json'),
        ('ip', ' , ; \n '),
    ],
)
def test_invalid_or_empty_structured_scope_never_matches(scope_type, scope_value):
    assert not alert_rule_service._scope_matches(
        {'scope_type': scope_type, 'scope_value': scope_value},
        {'site': 'HQ', 'role': 'core', 'ip_address': '192.0.2.1', 'tag_ids': {'production'}},
    )
