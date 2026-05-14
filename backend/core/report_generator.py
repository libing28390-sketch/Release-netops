import json
import logging
import os
import xlsxwriter
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

def generate_inspection_excel(
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    根据巡检运行信息和设备结果生成智能 Excel 报表。
    R10.4: 异常时清理临时文件，向上抛出异常。
    """
    workbook = None
    try:
        workbook = xlsxwriter.Workbook(output_path)
        _generate_inspection_excel_body(workbook, run_info, results)
        workbook.close()
        return output_path
    except Exception as e:
        # R10.4: 报表生成异常 — 清理已创建的临时文件
        try:
            if workbook is not None:
                try:
                    workbook.close()
                except Exception:
                    pass
        finally:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    logger.info(f"[Report] Cleaned up partial Excel file: {output_path}")
                except Exception as cleanup_err:
                    logger.error(f"[Report] Failed to remove partial file {output_path}: {cleanup_err}")
        logger.error(f"[Report] Excel generation failed: {e}")
        raise


def _generate_inspection_excel_body(
    workbook: Any,
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> None:
    """Internal: write all sheets into the given workbook."""
    
    # ── 格式定义 ──
    header_fmt = workbook.add_format({
        'bold': True, 'bg_color': '#00bceb', 'font_color': 'white', 
        'border': 1, 'align': 'center', 'valign': 'vcenter'
    })
    title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#00bceb'})
    label_fmt = workbook.add_format({'bold': True, 'bg_color': '#f8f9fa', 'border': 1})
    border_fmt = workbook.add_format({'border': 1})
    
    # 严重程度格式
    critical_fmt = workbook.add_format({'bg_color': '#ffebee', 'font_color': '#c62828', 'border': 1})
    warning_fmt = workbook.add_format({'bg_color': '#fff3e0', 'font_color': '#ef6c00', 'border': 1})
    healthy_fmt = workbook.add_format({'bg_color': '#e8f5e9', 'font_color': '#2e7d32', 'border': 1})
    
    # ══════════════════ SHEET 1: 概览 (Dashboard) ══════════════════
    summary_ws = workbook.add_worksheet('巡检概览')
    summary_ws.set_column('A:A', 15)
    summary_ws.set_column('B:B', 30)
    summary_ws.set_column('C:C', 15)
    summary_ws.set_column('D:D', 30)
    
    summary_ws.write('A1', 'Nexora NetOps 智能巡检报告', title_fmt)
    
    summary_ws.write('A3', '任务名称', label_fmt)
    summary_ws.write('B3', run_info.get('name') or '例行巡检')
    summary_ws.write('C3', '巡检时间', label_fmt)
    summary_ws.write('D3', run_info.get('started_at') or '')
    
    summary_ws.write('A4', '设备总数', label_fmt)
    summary_ws.write('B4', run_info.get('total_devices', 0))
    summary_ws.write('C4', '健康度', label_fmt)
    summary_ws.write('D4', f"{run_info.get('avg_health_score', 100):.1f}%")
    
    # 汇总结论
    analysis_sum = json.loads(run_info.get('analysis_summary_json') or '{}')
    summary_ws.write('A6', '分析结论', label_fmt)
    summary_ws.merge_range('B6:D6', analysis_sum.get('conclusion', '未发现明显异常。'), border_fmt)
    
    # Top 异常列表标题（含连通性硬故障 + 智能分析 critical 项）
    summary_ws.write('A8', '严重异常 Top 列表', workbook.add_format({'bold': True, 'font_color': '#c62828'}))
    headers = ['设备名称', 'IP 地址', '异常类型', '当前值 / 描述', '诊断分析与建议']
    for col, h in enumerate(headers):
        summary_ws.write(8, col, h, header_fmt)

    row = 9
    # 1. 先写连通性硬故障（findings_json 中 severity=critical）
    for res in results:
        findings = json.loads(res.get('findings_json') or '[]')
        for f in findings:
            if f.get('severity') == 'critical':
                summary_ws.write(row, 0, res.get('hostname', ''), border_fmt)
                summary_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
                summary_ws.write(row, 2, '连通性故障', critical_fmt)
                summary_ws.write(row, 3, f.get('message', ''), critical_fmt)
                summary_ws.write(row, 4, '请检查设备电源、网络路径及防火墙策略', border_fmt)
                row += 1
                if row > 30:
                    break
        if row > 30:
            break
    # 2. 再写智能分析 critical 项
    for res in results:
        analysis = json.loads(res.get('analysis_json') or '[]')
        for item in analysis:
            if item.get('status') == 'critical':
                summary_ws.write(row, 0, res.get('hostname'), border_fmt)
                summary_ws.write(row, 1, res.get('ip_address'), border_fmt)
                summary_ws.write(row, 2, item.get('metric', ''), critical_fmt)
                summary_ws.write(row, 3, item.get('value', ''), critical_fmt)
                summary_ws.write(row, 4, item.get('conclusion', ''), border_fmt)
                row += 1
                if row > 50:
                    break
        if row > 50:
            break
    
    # ══════════════════ SHEET 2: 连通性 & 硬故障异常明细 (Findings) ══════════════════
    # 数据来源：findings_json（Ping/SSH 失败、采集异常等硬故障）
    # R6.5: 包含异常类型列
    findings_ws = workbook.add_worksheet('异常明细')
    findings_headers = ['设备名称', '管理 IP', '平台', '站点', '异常类型', '严重程度', '异常描述', 'Ping', 'SSH']
    findings_ws.set_column('A:B', 18)
    findings_ws.set_column('C:D', 14)
    findings_ws.set_column('E:F', 12)
    findings_ws.set_column('G:G', 50)
    findings_ws.set_column('H:I', 8)

    # 异常类型中文映射
    _TYPE_LABELS = {
        'connectivity_error': '连通性异常',
        'auth_error': '认证异常',
        'command_error': '命令执行异常',
        'parse_error': '解析异常',
        'data_error': '数据异常',
        'system_error': '系统异常',
    }

    for col, h in enumerate(findings_headers):
        findings_ws.write(0, col, h, header_fmt)

    row = 1
    for res in results:
        findings = json.loads(res.get('findings_json') or '[]')
        if not findings:
            continue
        for finding in findings:
            severity = finding.get('severity', 'warning')
            sev_fmt = critical_fmt if severity == 'critical' else warning_fmt
            # R6.5: 异常类型（中文），旧格式无 type 字段显示「历史记录」
            exc_type = finding.get('type', '')
            type_label = _TYPE_LABELS.get(exc_type, '历史记录') if exc_type else '历史记录'
            findings_ws.write(row, 0, res.get('hostname', ''), border_fmt)
            findings_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
            findings_ws.write(row, 2, res.get('platform', ''), border_fmt)
            findings_ws.write(row, 3, res.get('site', ''), border_fmt)
            findings_ws.write(row, 4, type_label, border_fmt)
            findings_ws.write(row, 5, severity.upper(), sev_fmt)
            findings_ws.write(row, 6, finding.get('message', ''), border_fmt)
            findings_ws.write(row, 7, '✓' if res.get('ping_ok') else '✗', healthy_fmt if res.get('ping_ok') else critical_fmt)
            findings_ws.write(row, 8, '✓' if res.get('ssh_ok') else '✗', healthy_fmt if res.get('ssh_ok') else critical_fmt)
            row += 1

    # ══════════════════ SHEET 3: 异常指标分析明细 (Analysis) ══════════════════
    # 数据来源：analysis_json（智能分析阈值超标项）
    detail_ws = workbook.add_worksheet('异常指标分析明细')
    detail_headers = ['设备名称', '管理 IP', '巡检指标', '当前值', '状态', '诊断结论', '建议操作']
    detail_ws.set_column('A:B', 15)
    detail_ws.set_column('C:D', 12)
    detail_ws.set_column('E:E', 10)
    detail_ws.set_column('F:G', 40)
    
    for col, h in enumerate(detail_headers):
        detail_ws.write(0, col, h, header_fmt)
        
    row = 1
    for res in results:
        analysis = json.loads(res.get('analysis_json') or '[]')
        for item in analysis:
            if item['status'] != 'healthy':
                status_fmt = critical_fmt if item['status'] == 'critical' else warning_fmt
                detail_ws.write(row, 0, res.get('hostname'), border_fmt)
                detail_ws.write(row, 1, res.get('ip_address'), border_fmt)
                detail_ws.write(row, 2, item['metric'], border_fmt)
                detail_ws.write(row, 3, item['value'], status_fmt)
                detail_ws.write(row, 4, item['status'].upper(), status_fmt)
                detail_ws.write(row, 5, item['conclusion'], border_fmt)
                detail_ws.write(row, 6, item['suggestion'], border_fmt)
                row += 1

    # ══════════════════ SHEET 4: 设备资产汇总 (R6.1, R8.6) ══════════════════
    asset_ws = workbook.add_worksheet('设备资产汇总')
    asset_headers = ['设备名称', '管理 IP', '平台', '站点', '角色', '健康评分', '健康状态', '合规状态', '巡检时间']
    asset_ws.set_column('A:B', 18)
    asset_ws.set_column('C:E', 12)
    asset_ws.set_column('F:F', 10)
    asset_ws.set_column('G:I', 12)
    for col, h in enumerate(asset_headers):
        asset_ws.write(0, col, h, header_fmt)
    row = 1
    for res in results:
        score = res.get('health_score')
        status = res.get('health_status', 'unknown')
        status_f = critical_fmt if status == 'critical' else (warning_fmt if status == 'warning' else healthy_fmt)
        asset_ws.write(row, 0, res.get('hostname', ''), border_fmt)
        asset_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
        asset_ws.write(row, 2, res.get('platform', ''), border_fmt)
        asset_ws.write(row, 3, res.get('site', ''), border_fmt)
        asset_ws.write(row, 4, res.get('role', ''), border_fmt)
        asset_ws.write(row, 5, score if score is not None else '', status_f)
        asset_ws.write(row, 6, status, status_f)
        asset_ws.write(row, 7, res.get('compliance_status', 'unknown'), border_fmt)
        asset_ws.write(row, 8, res.get('checked_at', ''), border_fmt)
        row += 1

    # ══════════════════ SHEET 5: 指标横向对比 (R6.2) ══════════════════
    metrics_ws = workbook.add_worksheet('指标横向对比')
    # Collect all metric keys across all devices
    all_metric_keys = set()
    for res in results:
        try:
            m = json.loads(res.get('metrics_json') or '{}')
            for k, v in m.items():
                if not isinstance(v, dict) and not k.endswith('_last') and not k.endswith('_change_pct'):
                    all_metric_keys.add(k)
        except Exception:
            pass
    metric_keys_sorted = sorted(all_metric_keys)
    # Headers
    metrics_ws.write(0, 0, '设备名称', header_fmt)
    metrics_ws.write(0, 1, '管理 IP', header_fmt)
    for col, mk in enumerate(metric_keys_sorted, start=2):
        metrics_ws.write(0, col, mk, header_fmt)
    metrics_ws.set_column(0, 1, 18)
    # Data rows
    row = 1
    for res in results:
        metrics_ws.write(row, 0, res.get('hostname', ''), border_fmt)
        metrics_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
        try:
            m = json.loads(res.get('metrics_json') or '{}')
        except Exception:
            m = {}
        for col, mk in enumerate(metric_keys_sorted, start=2):
            val = m.get(mk)
            if isinstance(val, dict):
                metrics_ws.write(row, col, f"ERR: {val.get('error', '')}"[:50], critical_fmt)
            elif val is not None:
                metrics_ws.write(row, col, val, border_fmt)
            else:
                metrics_ws.write(row, col, '', border_fmt)
        row += 1

    # ══════════════════ SHEET 6: 整改建议 (R6.3, R6.4) ══════════════════
    suggest_ws = workbook.add_worksheet('整改建议')
    suggest_headers = ['设备名称', '管理 IP', '指标名称', '当前值', '状态', '诊断结论', '建议操作', '优先级']
    suggest_ws.set_column('A:B', 16)
    suggest_ws.set_column('C:D', 14)
    suggest_ws.set_column('E:E', 10)
    suggest_ws.set_column('F:G', 40)
    suggest_ws.set_column('H:H', 10)
    for col, h in enumerate(suggest_headers):
        suggest_ws.write(0, col, h, header_fmt)
    row = 1
    # R6.4: 先写关联风险
    for res in results:
        try:
            risks = json.loads(res.get('correlated_risks_json') or '[]')
        except Exception:
            risks = []
        for risk in risks:
            suggest_ws.write(row, 0, res.get('hostname', ''), border_fmt)
            suggest_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
            suggest_ws.write(row, 2, f"【组合风险】{risk.get('rule_name', '')}", critical_fmt)
            suggest_ws.write(row, 3, str(risk.get('triggered_metrics', '')), border_fmt)
            suggest_ws.write(row, 4, risk.get('severity', 'warning').upper(), critical_fmt)
            suggest_ws.write(row, 5, risk.get('description', ''), border_fmt)
            suggest_ws.write(row, 6, risk.get('suggestion', ''), border_fmt)
            suggest_ws.write(row, 7, '紧急' if risk.get('severity') == 'critical' else '重要', border_fmt)
            row += 1
    # 再写单指标异常
    for res in results:
        analysis = json.loads(res.get('analysis_json') or '[]')
        for item in analysis:
            if item.get('status') not in ('healthy', None):
                status_f = critical_fmt if item['status'] == 'critical' else warning_fmt
                suggest_ws.write(row, 0, res.get('hostname', ''), border_fmt)
                suggest_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
                suggest_ws.write(row, 2, item.get('metric', ''), border_fmt)
                suggest_ws.write(row, 3, str(item.get('value', '')), status_f)
                suggest_ws.write(row, 4, item['status'].upper(), status_f)
                suggest_ws.write(row, 5, item.get('conclusion', ''), border_fmt)
                suggest_ws.write(row, 6, item.get('suggestion', ''), border_fmt)
                suggest_ws.write(row, 7, '紧急' if item['status'] == 'critical' else '重要', border_fmt)
                row += 1

    # ══════════════════ SHEET 7+: 按设备生成明细 (Device Details) ══════════════════
    for res in results:
        hostname = res.get('hostname') or res.get('ip_address') or 'Unknown'
        # 移除非法字符并限制长度
        safe_sheet_name = "".join([c for c in hostname if c.isalnum() or c in (' ', '-', '_')])[:31]
        
        dev_ws = workbook.add_worksheet(safe_sheet_name)
        dev_ws.set_column('A:A', 30) # Command
        dev_ws.set_column('B:B', 100) # Output
        
        # 设备信息头
        dev_ws.write('A1', '设备名称', label_fmt)
        dev_ws.write('B1', res.get('hostname'), border_fmt)
        dev_ws.write('A2', '管理 IP', label_fmt)
        dev_ws.write('B2', res.get('ip_address'), border_fmt)
        dev_ws.write('A3', '健康得分', label_fmt)
        dev_ws.write('B3', res.get('health_score'), border_fmt)
        
        # 命令输出表头
        dev_ws.write(4, 0, '巡检命令', header_fmt)
        dev_ws.write(4, 1, '原始输出 (RAW)', header_fmt)
        
        row = 5
        raw_outputs = json.loads(res.get('raw_outputs_json') or '{}')
        for cmd, output in raw_outputs.items():
            dev_ws.write(row, 0, cmd, border_fmt)
            dev_ws.write(row, 1, str(output)[:20000], border_fmt)
            row += 1

    # End of body — workbook.close() is called by caller


# ─────────────────────────────────────────────────────────────────────────────
# HTML Report Generation (Task 9.2, R7)
# ─────────────────────────────────────────────────────────────────────────────

def generate_inspection_html(
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
    output_path: str,
    customer_name: str = '',
    engineer_name: str = '',
) -> str:
    """
    使用 Jinja2 模板生成 HTML 巡检报表。
    R10.4: 异常时清理临时文件。
    """
    from jinja2 import Environment, FileSystemLoader
    import os

    template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')

    try:
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
        template = env.get_template('inspection_report.html.j2')

        # Prepare template context
        total_devices = len(results)
        healthy_count = sum(1 for r in results if r.get('health_status') == 'healthy')
        warning_count = sum(1 for r in results if r.get('health_status') == 'warning')
        critical_count = sum(1 for r in results if r.get('health_status') == 'critical')
        scores = [r.get('health_score', 0) for r in results if r.get('health_score') is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        # Abnormal devices
        abnormal_devices = []
        for r in results:
            if r.get('health_status') in ('warning', 'critical'):
                findings = json.loads(r.get('findings_json') or '[]')
                top_finding = findings[0].get('message', '') if findings else ''
                abnormal_devices.append({
                    'hostname': r.get('hostname', ''),
                    'ip_address': r.get('ip_address', ''),
                    'health_score': r.get('health_score', 0),
                    'health_status': r.get('health_status', 'unknown'),
                    'top_finding': top_finding,
                })

        # All devices summary
        all_devices = [{
            'hostname': r.get('hostname', ''),
            'ip_address': r.get('ip_address', ''),
            'platform': r.get('platform', ''),
            'health_score': r.get('health_score', 0),
            'health_status': r.get('health_status', 'unknown'),
            'compliance_status': r.get('compliance_status', 'unknown'),
        } for r in results]

        # Correlated risks
        all_risks = []
        for r in results:
            try:
                risks = json.loads(r.get('correlated_risks_json') or '[]')
                for risk in risks:
                    risk['device'] = r.get('hostname', r.get('ip_address', ''))
                    all_risks.append(risk)
            except Exception:
                pass

        # Suggestions
        suggestions = []
        for r in results:
            analysis = json.loads(r.get('analysis_json') or '[]')
            for item in analysis:
                if item.get('status') not in ('healthy', None):
                    suggestions.append({
                        'hostname': r.get('hostname', ''),
                        'metric': item.get('metric', ''),
                        'status': item.get('status', ''),
                        'conclusion': item.get('conclusion', ''),
                        'suggestion': item.get('suggestion', ''),
                    })
        # Sort: critical first
        suggestions.sort(key=lambda x: 0 if x['status'] == 'critical' else 1)

        generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        html_content = template.render(
            run_info=run_info,
            customer_name=customer_name,
            engineer_name=engineer_name,
            total_devices=total_devices,
            healthy_count=healthy_count,
            warning_count=warning_count,
            critical_count=critical_count,
            avg_score=avg_score,
            abnormal_devices=abnormal_devices,
            all_devices=all_devices,
            all_risks=all_risks,
            suggestions=suggestions,
            generated_at=generated_at,
        )

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        return output_path

    except Exception as e:
        # R10.4: 清理临时文件
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        logger.error(f"[Report] HTML generation failed: {e}")
        raise
