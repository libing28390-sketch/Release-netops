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
    """
    workbook = xlsxwriter.Workbook(output_path)
    
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
    
    # Top 异常列表标题
    summary_ws.write('A8', '严重异常 Top 列表', workbook.add_format({'bold': True, 'font_color': '#c62828'}))
    headers = ['设备名称', 'IP 地址', '异常指标', '当前值', '诊断分析与建议']
    for col, h in enumerate(headers):
        summary_ws.write(8, col, h, header_fmt)
        
    row = 9
    for res in results:
        analysis = json.loads(res.get('analysis_json') or '[]')
        for item in analysis:
            if item['status'] == 'critical':
                summary_ws.write(row, 0, res.get('hostname'), border_fmt)
                summary_ws.write(row, 1, res.get('ip_address'), border_fmt)
                summary_ws.write(row, 2, item['metric'], critical_fmt)
                summary_ws.write(row, 3, item['value'], critical_fmt)
                summary_ws.write(row, 4, item['conclusion'], border_fmt)
                row += 1
                if row > 20: break # 只显示前 10 多个
    
    # ══════════════════ SHEET 2: 异常分析详情 (Anomalies) ══════════════════
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

    # ══════════════════ SHEET 3+: 按设备生成明细 (Device Details) ══════════════════
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
        
    workbook.close()
    return output_path
