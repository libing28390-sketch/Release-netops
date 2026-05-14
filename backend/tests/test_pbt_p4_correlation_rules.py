"""
P4: Correlation Rule Completeness — Exploration & Verification Tests
Task 5.1 (exploration) + Task 5.5 (verification)

Tests that:
- Positive examples (all conditions met) trigger the rule
- Negative examples (one condition missing) do NOT trigger the rule

Initially (exploration): correlate_risk_patterns may not exist → tests document expected behavior.
After implementation (verification): tests pass.
"""
import os
import json
import pytest

os.environ.setdefault("DATABASE_URL", "")


# ─────────────────────────────────────────────────────────────────────────────
# Built-in rules (matching database.py seed data)
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_RULES = [
    {
        'id': 'rule_l2_loop',
        'name': 'l2_loop_risk',
        'name_zh': '二层环路风险',
        'severity': 'critical',
        'suggestion': '立即检查 STP 状态，执行 show spanning-tree 排查环路',
        'conditions_json': json.dumps([
            {'metric': 'cpu_util', 'op': '>', 'value': 80},
            {'metric': 'intf_errors', 'op': '>', 'value': 100},
            {'metric': 'intf_flapping', 'op': '>', 'value': 3},
        ]),
        'enabled': 1,
    },
    {
        'id': 'rule_mem_leak',
        'name': 'memory_leak_risk',
        'name_zh': '内存泄漏风险',
        'severity': 'warning',
        'suggestion': '检查内存占用进程',
        'conditions_json': json.dumps([
            {'metric': 'mem_util', 'op': '>', 'value': 85},
            {'metric': 'mem_util_change_pct', 'op': '>', 'value': 10},
        ]),
        'enabled': 1,
    },
    {
        'id': 'rule_uplink_degrade',
        'name': 'uplink_degradation',
        'name_zh': '上行链路劣化风险',
        'severity': 'warning',
        'suggestion': '检查上行链路质量',
        'conditions_json': json.dumps([
            {'metric': 'uplink_util', 'op': '>', 'value': 70},
            {'metric': 'uplink_error_rate', 'op': '>', 'value': 0.1},
        ]),
        'enabled': 1,
    },
    {
        'id': 'rule_routing_unstable',
        'name': 'routing_protocol_unstable',
        'name_zh': '路由协议不稳定',
        'severity': 'critical',
        'suggestion': '检查路由协议配置',
        'conditions_json': json.dumps([
            {'metric': 'bgp_neighbor_down', 'op': '>', 'value': 0},
            {'metric': 'ospf_neighbor_down', 'op': '>', 'value': 0},
        ]),
        'enabled': 1,
    },
    {
        'id': 'rule_overheat',
        'name': 'device_overheat_risk',
        'name_zh': '设备过热风险',
        'severity': 'warning',
        'suggestion': '检查机房温度和散热系统',
        'conditions_json': json.dumps([
            {'metric': 'temperature', 'op': '>', 'value': 60},
            {'metric': 'cpu_util', 'op': '>', 'value': 70},
        ]),
        'enabled': 1,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Test data generators
# ─────────────────────────────────────────────────────────────────────────────

def _positive_metrics(rule: dict) -> dict:
    """Generate metrics that satisfy ALL conditions of a rule."""
    conditions = json.loads(rule['conditions_json'])
    metrics = {}
    for cond in conditions:
        metric = cond['metric']
        op = cond['op']
        value = cond['value']
        # Generate a value that satisfies the condition
        if op == '>':
            metrics[metric] = value + 1
        elif op == '>=':
            metrics[metric] = value
        elif op == '<':
            metrics[metric] = value - 1
        elif op == '<=':
            metrics[metric] = value
        elif op == '==':
            metrics[metric] = value
        elif op == '!=':
            metrics[metric] = value + 1 if isinstance(value, (int, float)) else 'other'
        else:
            metrics[metric] = value + 1
    return metrics


def _negative_metrics(rule: dict, missing_index: int = 0) -> dict:
    """Generate metrics that fail ONE condition (at missing_index)."""
    conditions = json.loads(rule['conditions_json'])
    metrics = {}
    for i, cond in enumerate(conditions):
        metric = cond['metric']
        op = cond['op']
        value = cond['value']
        if i == missing_index:
            # Generate a value that does NOT satisfy the condition
            if op == '>':
                metrics[metric] = value - 1  # not > value
            elif op == '>=':
                metrics[metric] = value - 1
            elif op == '<':
                metrics[metric] = value + 1
            elif op == '<=':
                metrics[metric] = value + 1
            elif op == '==':
                metrics[metric] = value + 999 if isinstance(value, (int, float)) else 'mismatch'
            elif op == '!=':
                metrics[metric] = value
            else:
                metrics[metric] = value - 1
        else:
            # Satisfy this condition
            if op == '>':
                metrics[metric] = value + 1
            elif op == '>=':
                metrics[metric] = value
            elif op == '<':
                metrics[metric] = value - 1
            elif op == '<=':
                metrics[metric] = value
            elif op == '==':
                metrics[metric] = value
            elif op == '!=':
                metrics[metric] = value + 1 if isinstance(value, (int, float)) else 'other'
            else:
                metrics[metric] = value + 1
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def _try_import_correlate():
    """Try to import correlate_risk_patterns; return None if not yet implemented."""
    try:
        from core.analysis import correlate_risk_patterns
        return correlate_risk_patterns
    except (ImportError, AttributeError):
        return None


@pytest.mark.parametrize("rule", BUILTIN_RULES, ids=[r['name_zh'] for r in BUILTIN_RULES])
def test_positive_example_triggers_rule(rule):
    """P4: Metrics satisfying ALL conditions MUST trigger the rule."""
    correlate = _try_import_correlate()
    if correlate is None:
        pytest.skip("correlate_risk_patterns not yet implemented (exploration phase)")

    metrics = _positive_metrics(rule)
    results = correlate(metrics, [rule])
    triggered_names = [r['rule_name'] for r in results]
    assert rule['name_zh'] in triggered_names or rule['name'] in triggered_names, (
        f"Rule '{rule['name_zh']}' should trigger with metrics {metrics}, got {results}"
    )


@pytest.mark.parametrize("rule", BUILTIN_RULES, ids=[r['name_zh'] for r in BUILTIN_RULES])
def test_negative_example_does_not_trigger(rule):
    """P4: Metrics missing ONE condition MUST NOT trigger the rule."""
    correlate = _try_import_correlate()
    if correlate is None:
        pytest.skip("correlate_risk_patterns not yet implemented (exploration phase)")

    conditions = json.loads(rule['conditions_json'])
    for i in range(len(conditions)):
        metrics = _negative_metrics(rule, missing_index=i)
        results = correlate(metrics, [rule])
        triggered_names = [r['rule_name'] for r in results]
        assert rule['name_zh'] not in triggered_names and rule['name'] not in triggered_names, (
            f"Rule '{rule['name_zh']}' should NOT trigger when condition {i} is not met. "
            f"Metrics: {metrics}, Results: {results}"
        )


def test_empty_rules_returns_empty():
    """P4: No rules → empty result, no error."""
    correlate = _try_import_correlate()
    if correlate is None:
        pytest.skip("correlate_risk_patterns not yet implemented (exploration phase)")

    metrics = {'cpu_util': 99, 'mem_util': 99}
    results = correlate(metrics, [])
    assert results == []


def test_disabled_rule_not_triggered():
    """P4: Disabled rules should not trigger."""
    correlate = _try_import_correlate()
    if correlate is None:
        pytest.skip("correlate_risk_patterns not yet implemented (exploration phase)")

    rule = {**BUILTIN_RULES[0], 'enabled': 0}
    metrics = _positive_metrics(rule)
    results = correlate(metrics, [rule])
    assert results == []
