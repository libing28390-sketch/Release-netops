import json
import logging
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
    
    for item in inspection_items:
        key = item.get('check_key')
        if not key or key not in metrics:
            continue
            
        val = metrics[key]
        if val is None or isinstance(val, dict): # Skip errors
            continue
            
        name = item.get('name_zh') or item.get('name') or key
        warn = item.get('warning_threshold')
        crit = item.get('critical_threshold')
        
        status = "healthy"
        conclusion = f"指标正常: {val}"
        suggestion = ""
        
        # 1. 阈值判断
        if isinstance(val, (int, float)):
            if crit is not None and val >= float(crit):
                status = "critical"
                conclusion = f"指标严重超标: {val} (阈值 {crit})"
                suggestion = f"请立即检查设备 {name} 负载或状态。"
            elif warn is not None and val >= float(warn):
                status = "warning"
                conclusion = f"指标达到告警线: {val} (阈值 {warn})"
                suggestion = f"建议关注 {name} 变化趋势。"
                
        # 2. 历史对比判断 (如果提供了历史数据)
        if historical_metrics and key in historical_metrics:
            last_val = historical_metrics[key]
            if isinstance(val, (int, float)) and isinstance(last_val, (int, float)) and last_val > 0:
                change_pct = (val - last_val) / last_val * 100.0
                if abs(change_pct) > 20: # 变化超过 20% 记录一下
                    trend = "上升" if change_pct > 0 else "下降"
                    conclusion += f" (较上次{trend} {abs(change_pct):.1f}%)"
                    if status == "healthy" and abs(change_pct) > 50:
                        status = "warning"
                        conclusion = f"指标波动剧烈: {val} (较上次{trend} {abs(change_pct):.1f}%)"
                        suggestion = "指标波动剧烈，建议排查是否存在潜在风险。"

        # 3. 结果合并
        analysis_results.append({
            "metric": name,
            "key": key,
            "value": val,
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
