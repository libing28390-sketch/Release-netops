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
        analysis = res.get('analysis') or []
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
