import json
import logging
import math
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

def analyze_device_inspection(
    device_info: Dict[str, Any],
    metrics: Dict[str, Any],
    inspection_items: List[Dict[str, Any]],
    historical_metrics: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    针对单台设备的巡检结果进行智能分析。
    返回分析项列表，每项包含：指标、状态、结论、建议。
    """
    analysis_results = []
    component_codes = {0: 'ok', 1: 'warning', 2: 'failed', 3: 'unknown'}
    unknown_states = {'', 'unknown', 'unavailable', 'not_collected', 'not collected', 'n/a', 'na', 'null', 'none', '--'}
    healthy_states = {'normal', 'ok', 'up', 'true', '1', 'running', 'operational', 'ready', 'active'}
    failure_states = {'fail', 'failed', 'failure', 'error', 'down', 'offline', 'alarm', 'false', '0'}

    def _number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def _crossed(value: Any, threshold: Any, direction: Any) -> bool:
        actual = _number(value)
        boundary = _number(threshold)
        if actual is None or boundary is None:
            return False
        return actual < boundary if str(direction or 'above').casefold() == 'below' else actual >= boundary

    def _status_value(value: Any, component_state: bool) -> str:
        if isinstance(value, bool):
            return 'ok' if value else 'failed'
        number = _number(value)
        if number is not None:
            if component_state and number.is_integer() and int(number) in component_codes:
                return component_codes[int(number)]
            if number.is_integer():
                return str(int(number))
        normalized = str(value or '').strip().casefold()
        if component_state and normalized in {'0', '1', '2', '3'}:
            return component_codes[int(normalized)]
        return normalized

    def _expected_matches(value: Any, expected: Any, allow_substring: bool) -> bool:
        actual_text = str(value or '').strip().casefold()
        expected_text = str(expected or '').strip().casefold()
        if not expected_text or actual_text in unknown_states:
            return False
        if actual_text == expected_text:
            return True
        if not allow_substring or expected_text not in actual_text:
            return False
        prefix = actual_text.split(expected_text, 1)[0].strip()
        return not (
            prefix in {'un', 'not', 'no', 'non'}
            or prefix.endswith(('not', 'no', 'non'))
        )

    for item in inspection_items:
        key = item.get('check_key')
        if not key or key not in metrics:
            continue

        val = metrics[key]
        if val is None or isinstance(val, dict):
            continue

        if str(metrics.get(f'{key}_status') or '').strip().upper() in {
            'NOT_COLLECTED', 'UNCHECKED', 'UNAVAILABLE', 'NOT_APPLICABLE',
        }:
            continue

        name = item.get('name_zh') or item.get('name') or key
        unit = str(item.get('unit') or '').strip()
        warn = item.get('warning_threshold')
        crit = item.get('critical_threshold')
        parse_type = str(item.get('parse_type') or 'numeric').casefold()
        direction = str(item.get('threshold_direction') or 'above').casefold()
        metric_status = str(metrics.get(f'{key}_status') or '').strip().upper()
        status = "healthy"
        value_text = f"{val}{(' ' + unit) if unit else ''}"
        conclusion = f"指标正常: {value_text}"
        suggestion = ""

        if parse_type == 'status':
            component_state = (
                str(item.get('method') or '').casefold() == 'snmp'
                and str(key).casefold().endswith(('_fan', '_psu'))
            )
            normalized = _status_value(val, component_state)
            if metric_status in {'NOT_COLLECTED', 'UNCHECKED', 'UNAVAILABLE', 'NOT_APPLICABLE'} or normalized in unknown_states:
                continue
            if metric_status == 'WARNING':
                status = 'warning'
            elif metric_status in {'ERROR', 'CRITICAL'}:
                status = 'critical' if component_state else 'warning'
            elif metric_status == 'SUCCESS':
                status = 'healthy'
            elif normalized == 'warning':
                status = 'warning'
            elif normalized in {'failed', 'fail', 'failure'}:
                status = 'critical' if component_state else 'warning'
            else:
                expected = item.get('expected_value')
                has_expected = str(expected or '').strip().casefold() not in unknown_states
                if has_expected:
                    matches = (
                        normalized == _status_value(expected, component_state)
                        if component_state
                        else _expected_matches(
                            val,
                            expected,
                            str(item.get('category') or '').casefold() == 'compliance',
                        )
                    )
                    if not matches:
                        status = 'warning'
                elif normalized in healthy_states:
                    status = 'healthy'
                elif normalized in failure_states:
                    status = 'critical' if component_state else 'warning'
                else:
                    status = 'warning'

            if status != 'healthy':
                conclusion = f"状态异常: 实际 {val}，期望 {item.get('expected_value') or '正常'}"
                suggestion = f"请检查 {name} 的状态与采集来源。"
        else:
            evaluated_value = val
            if parse_type == 'diff':
                change_pct = metrics.get(f'{key}_change_pct')
                if change_pct is None and historical_metrics and key in historical_metrics:
                    previous = _number(historical_metrics.get(key))
                    current = _number(val)
                    if previous is not None and previous > 0 and current is not None:
                        change_pct = abs(current - previous) / previous * 100.0
                if change_pct is None:
                    evaluated_value = None
                else:
                    evaluated_value = change_pct

            if evaluated_value is not None:
                evaluated_unit = '%' if parse_type == 'diff' else unit
                evaluated_text = f"{evaluated_value}{(' ' + evaluated_unit) if evaluated_unit else ''}"
                threshold_relation = '低于' if direction == 'below' else '达到或超过'
                if _crossed(evaluated_value, crit, direction):
                    status = "critical"
                    conclusion = f"指标严重超标: {evaluated_text} ({threshold_relation}阈值 {crit}{(' ' + evaluated_unit) if evaluated_unit else ''})"
                    suggestion = f"请立即检查设备 {name} 负载或状态。"
                elif _crossed(evaluated_value, warn, direction):
                    status = "warning"
                    conclusion = f"指标达到告警线: {evaluated_text} ({threshold_relation}阈值 {warn}{(' ' + evaluated_unit) if evaluated_unit else ''})"
                    suggestion = f"建议关注 {name} 变化趋势。"

        # 2. Historical trend context; it never overrides a status item or an
        # already established threshold state.
        if parse_type != 'status' and historical_metrics and key in historical_metrics:
            last_val = _number(historical_metrics[key])
            current_val = _number(val)
            if current_val is not None and last_val is not None and last_val > 0:
                change = (current_val - last_val) / last_val * 100.0
                if abs(change) > 20:
                    trend = "上升" if change > 0 else "下降"
                    conclusion += f" (较上次{trend} {abs(change):.1f}%)"
                    if status == "healthy" and abs(change) > 50:
                        status = "warning"
                        conclusion = f"指标波动剧烈: {value_text} (较上次{trend} {abs(change):.1f}%)"
                        suggestion = "指标波动剧烈，建议排查是否存在潜在风险。"

        analysis_results.append({
            "metric": name,
            "key": key,
            "value": val,
            "unit": unit,
            "status": status,
            "conclusion": conclusion,
            "suggestion": suggestion
        })

    return analysis_results

def summarize_run_analysis(device_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    汇总整次巡检任务的分析结果。
    """
    total_anomalies = 0
    critical_count = 0
    warning_count = 0
    common_issues = {}
    
    for res in device_results:
        analysis = json.loads(res.get('analysis_json') or '[]')
        for item in analysis:
            if item['status'] != 'healthy':
                total_anomalies += 1
                if item['status'] == 'critical':
                    critical_count += 1
                else:
                    warning_count += 1
                
                # 统计常见问题
                m_name = item['metric']
                common_issues[m_name] = common_issues.get(m_name, 0) + 1
                
    # 找出 Top 3 问题指标
    top_issues = sorted(common_issues.items(), key=lambda x: x[1], reverse=True)[:3]
    
    summary = {
        "total_anomalies": total_anomalies,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "top_issues": [{"metric": k, "count": v} for k, v in top_issues],
        "conclusion": f"本次巡检发现 {total_anomalies} 项异常，其中严重 {critical_count} 项。主要问题集中在: " + 
                     (", ".join([f"{i['metric']}({i['count']}台)" for i in [{"metric": k, "count": v} for k, v in top_issues]]))
                     if total_anomalies > 0 else "全网设备运行状态良好，未发现明显异常。"
    }
    
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Correlation Rule Engine (Task 5.2, R4.1–R4.3)
# ─────────────────────────────────────────────────────────────────────────────

def correlate_risk_patterns(
    metrics: Dict[str, Any],
    rules: List[Dict[str, Any]],
    historical_metrics: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """
    对单台设备的 metrics 执行所有关联规则匹配。

    Args:
        metrics: 设备当前指标字典 {check_key: value}
        rules: 关联规则列表（从数据库加载），每条含 conditions_json, name_zh, severity, suggestion 等
        historical_metrics: 可选的上一次巡检指标（用于 change_pct 类条件）

    Returns:
        触发的关联风险列表：
        [{rule_name, description, severity, suggestion, triggered_metrics}]
    """
    if not rules or not metrics:
        return []

    triggered: List[Dict[str, Any]] = []

    for rule in rules:
        # 跳过禁用规则
        if not rule.get('enabled', 1):
            continue

        conditions_raw = rule.get('conditions_json', '[]')
        if isinstance(conditions_raw, str):
            try:
                conditions = json.loads(conditions_raw)
            except (json.JSONDecodeError, TypeError):
                continue
        else:
            conditions = conditions_raw

        if not conditions:
            continue

        # 检查所有条件是否满足
        all_satisfied = True
        triggered_metrics: Dict[str, Any] = {}

        for cond in conditions:
            metric_key = cond.get('metric', '')
            op = cond.get('op', '>')
            threshold = cond.get('value')

            if threshold is None:
                all_satisfied = False
                break

            # 获取指标值
            actual_value = metrics.get(metric_key)

            # 如果指标值是 error 结构 {value: None, error: ...}，视为不满足
            if isinstance(actual_value, dict):
                all_satisfied = False
                break

            if actual_value is None:
                all_satisfied = False
                break

            # 尝试数值比较
            try:
                actual_num = float(actual_value)
                threshold_num = float(threshold)
            except (TypeError, ValueError):
                # 非数值比较（== / !=）
                if op == '==':
                    if str(actual_value) != str(threshold):
                        all_satisfied = False
                        break
                elif op == '!=':
                    if str(actual_value) == str(threshold):
                        all_satisfied = False
                        break
                else:
                    all_satisfied = False
                    break
                triggered_metrics[metric_key] = actual_value
                continue

            # 数值比较
            satisfied = False
            if op == '>':
                satisfied = actual_num > threshold_num
            elif op == '>=':
                satisfied = actual_num >= threshold_num
            elif op == '<':
                satisfied = actual_num < threshold_num
            elif op == '<=':
                satisfied = actual_num <= threshold_num
            elif op == '==':
                satisfied = actual_num == threshold_num
            elif op == '!=':
                satisfied = actual_num != threshold_num
            else:
                satisfied = False

            if not satisfied:
                all_satisfied = False
                break

            triggered_metrics[metric_key] = actual_value

        if all_satisfied:
            triggered.append({
                'rule_name': rule.get('name_zh') or rule.get('name', ''),
                'description': rule.get('description', ''),
                'severity': rule.get('severity', 'warning'),
                'suggestion': rule.get('suggestion', ''),
                'triggered_metrics': triggered_metrics,
            })

    return triggered
