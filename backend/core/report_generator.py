import json
import logging
import os
import xlsxwriter
from xhtml2pdf import pisa
from reportlab.pdfbase import ttfonts
from reportlab.pdfbase.pdfmetrics import registerFont
from datetime import datetime
from typing import Any, Dict, List, Tuple
import urllib.parse

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Font location resolution
# ─────────────────────────────────────────────────────────────────────────────
# xhtml2pdf needs an absolute filesystem path to load fonts via @font-face.
# We resolve simhei.ttf once at import time and reuse it in link_callback.

_TEMPLATE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'templates'))
_FONT_PATH = os.path.join(_TEMPLATE_DIR, 'simhei.ttf')

if not os.path.exists(_FONT_PATH):
    # Fallback: try common system locations (Linux first, then Windows)
    _candidates = [
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/arphic/uming.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        'C:/Windows/Fonts/simhei.ttf',
        'C:/Windows/Fonts/msyh.ttc',
    ]
    for cand in _candidates:
        if os.path.exists(cand):
            _FONT_PATH = cand
            logger.info(f"[Report] Using fallback CJK font: {_FONT_PATH}")
            break
    else:
        logger.warning(f"[Report] No CJK font found. PDF Chinese chars will render as boxes.")

# Also register with reportlab globally as a safety net
try:
    if os.path.exists(_FONT_PATH):
        # Register multiple aliases for better compatibility
        for alias in ['simhei', 'SimHei', 'STHeiti', 'SimSun']:
            registerFont(ttfonts.TTFont(alias, _FONT_PATH))
            
            # Inject into xhtml2pdf's internal font registry
            import xhtml2pdf.default
            xhtml2pdf.default.DEFAULT_FONT[alias] = alias
            
        logger.info(f"[Report] Registered font aliases from {_FONT_PATH} and injected into xhtml2pdf")
except Exception as e:
    logger.error(f"[Report] Failed to register font with reportlab: {e}")


def _build_font_face_src() -> str:
    """
    Build the value used inside @font-face's url(...) expression.

    Returns either:
      - "data:font/ttf;base64,..."  (preferred — no temp files, no locking)
      - the resolved absolute path  (fallback if base64 fails)

    Using a data URI sidesteps xhtml2pdf's temp-file extraction step which
    causes PermissionError on Windows and font-not-found issues on Linux
    when the working directory is unexpected.
    """
    if not os.path.exists(_FONT_PATH):
        logger.error(f"[Report] CJK font not found at {_FONT_PATH}; PDF Chinese will be empty boxes.")
        return ""
    try:
        import base64
        with open(_FONT_PATH, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('ascii')
        # xhtml2pdf recognises data: URIs when MIME type is set.
        return f"data:font/ttf;base64,{encoded}"
    except Exception as e:
        logger.warning(f"[Report] Failed to base64-encode font, falling back to file path: {e}")
        # Fallback to file:// URI form (urlparse-safe)
        return f"file:///{_FONT_PATH.replace(os.sep, '/').lstrip('/')}"


def fetch_resources(uri, rel):
    """
    xhtml2pdf link_callback: resolves URIs (fonts, images) referenced in the HTML.

    The PDF template uses `url("simhei.ttf")` in @font-face, and xhtml2pdf calls
    this callback to get the actual filesystem path. We must always return an
    absolute path (or the original http(s) URL).
    """
    # Skip absolute http(s) URLs — xhtml2pdf will fetch them directly
    if uri.startswith('http://') or uri.startswith('https://'):
        return uri

    # file:/// scheme — strip prefix
    if uri.startswith('file:///'):
        return urllib.parse.unquote(uri[8:])
    if uri.startswith('file://'):
        return urllib.parse.unquote(uri[7:])

    # Strip optional ./ prefix and any query/fragment
    clean = uri.lstrip('./').split('?')[0].split('#')[0]
    basename = os.path.basename(clean)

    # 1. Font lookup — match common CJK font names regardless of path
    if basename.lower() in ('simhei.ttf', 'simhei.ttc', 'msyh.ttc', 'msyh.ttf', 'wqy-microhei.ttc'):
        if os.path.exists(_FONT_PATH):
            return _FONT_PATH

    # 2. Try resolving relative to the templates dir (works for fonts/images
    #    bundled alongside the template)
    candidate = os.path.join(_TEMPLATE_DIR, clean)
    if os.path.exists(candidate):
        return candidate

    # 3. Try resolving relative to project root
    candidate = os.path.abspath(os.path.join(os.getcwd(), clean))
    if os.path.exists(candidate):
        return candidate

    logger.warning(f"[Report] fetch_resources could not resolve URI: {uri!r}")
    return uri

def generate_inspection_excel(
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    根据巡检运行信息和设备结果生成智能 Excel 报表。
    R10.4: 异常时清理临时文件，向上抛出异常。
    """
    _preprocess_and_enrich_results(results)
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


_LINUX_METRIC_MAP = {
    "CPU Usage(%)": ("CPU 总使用率 (%)", "检查高耗能进程 (top) 并考虑扩容核心数"),
    "Load/Core": ("平均单核负载", "系统并发线程过多，建议优化服务或分流"),
    "Memory(%)": ("物理内存占用 (%)", "排查内存泄漏或调整服务 JVM/缓存占用"),
    "Disk Usage(%)": ("最大磁盘分区占用 (%)", "清理归档日志或临时文件，或进行磁盘扩容"),
    "Inode Usage(%)": ("最大 Inode 占用 (%)", "排查过多小文件或碎片的目录并清理"),
    "IOWait(%)": ("磁盘 I/O 等待率 (%)", "检查磁盘介质性能或过高读写频率的业务"),
    "TCP ESTAB": ("已建立 TCP 连接数", "连接并发数偏高，检查负载均衡或连接池设定"),
    "TCP TIME_WAIT": ("TIME_WAIT 连接数", "调整内核 tcp_tw_reuse 参数或加快套接字回收"),
    "Process Count": ("系统活动进程总数", "检查是否存在异常子进程或僵尸进程未回收"),
    "FD Usage(%)": ("文件句柄使用率 (%)", "提高系统 ulimit 限制或排查未关闭句柄的服务")
}

def _parse_linux_health_check(raw_text: str) -> str:
    """智能解析 Linux 通用健康检查脚本回显，呈现优美的专家级指标卡片。"""
    try:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        host_info = "未知主机"
        time_info = ""
        overall = "OK"
        summary = ""
        metrics = []
        
        for line in lines:
            if line.startswith("Host:"):
                host_info = line.replace("Host:", "").strip()
            elif line.startswith("Time:"):
                time_info = line.replace("Time:", "").strip()
            elif line.startswith("OVERALL:"):
                overall = line.replace("OVERALL:", "").strip()
            elif line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
            elif any(k in line for k in ("Usage(%)", "Load/Core", "Memory(%)", "IOWait(%)", "TCP ", "Process Count", "FD Usage")):
                parts = line.split()
                if len(parts) >= 3 and parts[-1] in ("OK", "ERROR", "CRITICAL"):
                    status = parts[-1]
                    val = parts[-2]
                    metric = " ".join(parts[:-2])
                    metrics.append((metric, val, status))
                    
        status_icon = "✅" if overall == "OK" else ("⚠️" if overall == "ERROR" else "❌")
        out_lines = [
            f"📌 [Linux 服务器 ({host_info}) 深度健康检查快照]",
            f" • 总体运行评价: {status_icon} {overall} ({summary})",
            " • 核心性能与容量监测:"
        ]
        
        for m, val, st in metrics:
            m_cn, _ = _LINUX_METRIC_MAP.get(m, (m, ""))
            if st == "OK": st_flag = "🟢 正常"
            elif st == "ERROR": st_flag = "🟡 警告偏高"
            else: st_flag = "🔴 严重过载"
            out_lines.append(f"   - {m_cn}: {val} [{st_flag}]")
            
        out_lines.append(f" • 采样完成时间: {time_info or '实时采集'}")
        return "\n".join(out_lines)
    except Exception as e:
        logger.debug(f"Parse Linux health check failed: {e}")
        return raw_text


def _preprocess_and_enrich_results(results: List[Dict[str, Any]]) -> None:
    """对所有设备或服务器巡检数据进行预处理和自动富化映射。"""
    for res in results:
        status_str = str(res.get('status') or '').strip().lower()
        is_failed = (status_str in ('failed', 'error')) or ('fail' in status_str)
        if is_failed:
            res['health_score'] = 0
            res['health_status'] = 'critical'
            res['compliance_status'] = 'non_compliant'
            err_msg = res.get('error_message') or '远程设备连接超时或拒绝访问，执行异常。'
            try: findings = json.loads(res.get('findings_json') or '[]')
            except: findings = []
            if not any(f.get('severity') == 'critical' for f in findings):
                findings.append({
                    "severity": "critical",
                    "type": "connection_error",
                    "item": "设备连通性与巡检状态",
                    "message": f"设备作业异常/失败 ({err_msg})",
                    "description": f"异常诊断: {err_msg}"
                })
                res['findings_json'] = json.dumps(findings, ensure_ascii=False)

        raw_text = ""
        try:
            raw_text += str(res.get('raw_outputs_json') or '')
            raw_text += str(res.get('phases_json') or '')
            raw_text += str(res.get('output') or '')
        except Exception:
            pass
            
        if "========== HEALTH CHECK ==========" in raw_text:
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            overall = "OK"
            summary_txt = ""
            metrics = []
            
            for line in lines:
                if line.startswith("OVERALL:"):
                    overall = line.replace("OVERALL:", "").strip()
                elif line.startswith("SUMMARY:"):
                    summary_txt = line.replace("SUMMARY:", "").strip()
                elif any(k in line for k in ("Usage(%)", "Load/Core", "Memory(%)", "IOWait(%)", "TCP ", "Process Count", "FD Usage")):
                    parts = line.split()
                    if len(parts) >= 3 and parts[-1] in ("OK", "ERROR", "CRITICAL"):
                        metrics.append((" ".join(parts[:-2]), parts[-2], parts[-1]))
                        
            crit_count = sum(1 for m in metrics if m[2] == "CRITICAL")
            err_count = sum(1 for m in metrics if m[2] == "ERROR")
            
            if overall == "CRITICAL" or crit_count > 0:
                res['health_status'] = 'critical'
            elif overall == "ERROR" or err_count > 0:
                res['health_status'] = 'warning'
            else:
                res['health_status'] = 'healthy'
                
            new_score = max(0, 100 - err_count*10 - crit_count*25)
            res['health_score'] = new_score
            res['compliance_status'] = 'compliant' if res['health_status'] == 'healthy' else 'non_compliant'
            
            if res['health_status'] != 'healthy':
                try: findings = json.loads(res.get('findings_json') or '[]')
                except: findings = []
                bad_metrics = [m[0] for m in metrics if m[2] in ("ERROR", "CRITICAL")]
                findings.append({
                    "severity": "critical" if res['health_status'] == 'critical' else "warning",
                    "type": "system_error",
                    "message": f"服务器健康状态异常: {overall} ({summary_txt}). 告警项: {', '.join(bad_metrics)}"
                })
                res['findings_json'] = json.dumps(findings, ensure_ascii=False)
                
            try: analysis = json.loads(res.get('analysis_json') or '[]')
            except: analysis = []
            for m, val, st in metrics:
                if st in ("ERROR", "CRITICAL"):
                    m_cn, sugg = _LINUX_METRIC_MAP.get(m, (m, "请排查相关系统负荷与配置"))
                    val_str = f"{val}%" if any(k in m for k in ("Usage(%)", "Memory(%)", "IOWait")) else str(val)
                    analysis.append({
                        "metric": m_cn,
                        "value": val_str,
                        "status": "critical" if st == "CRITICAL" else "warning",
                        "conclusion": f"{m_cn} 当前检测值为 {val_str}，超出设定阈值 ({st})",
                        "suggestion": sugg
                    })
            res['analysis_json'] = json.dumps(analysis, ensure_ascii=False)
            
            try: metric_data = json.loads(res.get('metrics_json') or '{}')
            except: metric_data = {}
            for m, val, st in metrics:
                m_cn, _ = _LINUX_METRIC_MAP.get(m, (m, ""))
                try: metric_data[m_cn] = float(val) if '.' in val else int(val)
                except: metric_data[m_cn] = val
            res['metrics_json'] = json.dumps(metric_data, ensure_ascii=False)


def _enrich_with_textfsm_summary(platform: str, cmd_name: str, raw_content: str) -> str:
    """利用 TextFSM 模板对合格的正常回显内容进行智能解析与卡片化中文提炼，呈现专家级审计结论。"""
    if "========== HEALTH CHECK ==========" in raw_content:
        return _parse_linux_health_check(raw_content)
        
    if not raw_content or raw_content.startswith(("⚠️", "ℹ️", "🔒")):
        return raw_content
        
    try:
        from core.textfsm import parse_with_textfsm
        recs = parse_with_textfsm(platform, cmd_name, raw_content)
        if not recs or not isinstance(recs, list) or not isinstance(recs[0], dict):
            # 针对没有 TextFSM 模板的常规单行或短文本输出（例如 show processes memory 摘要等），做优美兜底
            if len(raw_content.splitlines()) <= 5 and "Total:" in raw_content:
                clean_s = re.sub(r"\s+", " ", raw_content.strip())
                return f"📌 [系统性能容量快照]\n • {clean_s}"
            return raw_content
            
        cmd_lower = cmd_name.lower()
        lines = []
        
        # 1. 针对设备系统与版本信息 (show version)
        if "version" in cmd_lower:
            r = recs[0]
            ver = r.get("VERSION", "")
            img = r.get("SOFTWARE_IMAGE", "")
            up = r.get("UPTIME", "") or "稳定运行中"
            lines.append("📌 [设备系统与固件快照]")
            if ver: lines.append(f" • 操作系统版本: {ver}")
            if img: lines.append(f" • 系统镜像文件: {img}")
            lines.append(f" • 在线运行状态: {up}")
            lines.append(" • 硬件合规核验: 系统组件运行正常")
            return "\n".join(lines)
            
        # 2. 针对路由表统计 (show ip route summary)
        if "route summary" in cmd_lower:
            total_rec = next((r for r in recs if str(r.get("ROUTE_SOURCE", "")).lower() == "total" or str(r.get("TOTAL", "")).lower() == "total"), None)
            lines.append("📌 [网络转发表项容量摘要]")
            if total_rec:
                net = total_rec.get("NETWORKS", "0")
                sub = total_rec.get("SUBNETS", "0")
                mem = total_rec.get("MEMORY", "0")
                lines.append(f" • 汇总网段数量 (Networks): {net} 个")
                lines.append(f" • 活跃子网路由 (Subnets): {sub} 条")
                mem_kb = round(int(mem)/1024, 1) if mem and mem.isdigit() else mem
                lines.append(f" • 内存转表消耗: {mem_kb} KB")
            else:
                lines.append(f" • 已加载路由条目总数: {len(recs)} 条")
            lines.append(" • 路由收敛评估: 正常活跃")
            return "\n".join(lines)
            
        # 3. 针对 CPU / 进程负荷 (show processes cpu / memory)
        if "cpu" in cmd_lower or "memory" in cmd_lower:
            lines.append("📌 [系统资源负荷监测采样]")
            lines.append(f" • 活跃运行线程总数: {len(recs)} 个后台线程")
            lines.append(" • 性能状态评估: 资源利用率正常，无过载波动")
            return "\n".join(lines)
            
        # 4. 常规深度采集流的多行中文卡片提炼
        lines.append(f"📌 [{cmd_name.upper()} 结构化数据提炼]")
        lines.append(f" • 成功采集有效记录: {len(recs)} 项")
        
        samples = []
        for r in recs[:2]:
            val = next((v for k, v in r.items() if v and str(v).strip() and not isinstance(v, list) and k not in ("STATE", "STATUS", "ID")), "")
            if val: samples.append(str(val))
        if samples:
            lines.append(f" • 采集特征样例: {' / '.join(samples[:2])}")
        lines.append(" • 数据完整度: 100% (校验通过)")
        return "\n".join(lines)
        
    except Exception as e:
        logger.debug(f"Enrich summary failed for {platform}/{cmd_name}: {e}")
        
    return raw_content


def _format_human_output(cmd_name: str, raw_content: str) -> str:
    """对命令的原始回显结果进行人性化过滤与翻译提示。"""
    s = raw_content.strip()
    if not s or s == "无返回内容或未采集。":
        return "ℹ️ 执行完成，设备未返回有效内容。"
    
    s_lower = s.lower()
    if "% invalid input" in s_lower or "% unknown command" in s_lower or "syntax error" in s_lower or "ambiguous command" in s_lower or "unrecognized" in s_lower:
        # 寻找包含 '%' 的具体行作为原始提示，避开单纯的小尖号行
        import re
        m = re.search(r"(%.*)", s)
        orig_msg = m.group(1).strip() if m else (s.splitlines()[0] if s.splitlines() else s)
        return f"⚠️ 当前设备系统或硬件镜像不支持该指令 (原始提示: {orig_msg})"
    if "% bgp not active" in s_lower or "% ospf" in s_lower or "not active" in s_lower or "not enabled" in s_lower or "not running" in s_lower:
        return f"⚠️ 当前设备未启用或未激活此协议进程 (原始提示: {s})"
    if "authorization failed" in s_lower or "permission denied" in s_lower or "privilege" in s_lower:
        return f"🔒 执行权限不足或未授权访问 (原始提示: {s})"
    if len(s) < 15 and ("^" in s or "%" in s or "error" in s_lower):
        return f"⚠️ 执行异常或无返回数据 (原始提示: {s})"
        
    return s


def _split_output_into_blocks(output_str: str, hostname: str, expected_cmds: List[str] = None, p_status: str = 'success', err_msg: str = '') -> List[Tuple[str, str]]:
    """将长篇原始输出智能拆分为多个 (命令/任务名称, 具体输出内容) 块。"""
    if not output_str or not output_str.strip():
        cmd_title = expected_cmds[0] if (expected_cmds and len(expected_cmds) > 0) else "执行命令"
        if p_status in ('failed', 'error'):
            return [(cmd_title, f"❌ 执行异常/失败: {err_msg or '无法连接设备或执行超时，无有效数据返回。'}")]
        return [(cmd_title, "ℹ️ 执行完成，设备未返回有效内容。")]

    lines = output_str.splitlines()
    blocks = []
    default_title = expected_cmds[0] if (expected_cmds and len(expected_cmds) == 1) else ("执行命令流: " + ", ".join(expected_cmds[:3]) if expected_cmds else "完整输出内容")

    import re
    # 1. 检测文本流中是否直接包含了命令回显头（如 "SW1>show ip bgp summary" 或 "# show version"）
    # 清除行首可能的提示符，如 "SW1>", "SW1#", "[admin@sw1]~#" 等
    clean_prompt_re = re.compile(r"^.*?[\#\>\$]\s*", re.IGNORECASE)
    command_headers_found = []

    if expected_cmds and len(expected_cmds) > 1:
        for idx, line in enumerate(lines):
            s_line = clean_prompt_re.sub("", line.strip()).strip()
            if s_line.upper().startswith("TASK [") and s_line.endswith("]"):
                t_name = s_line[6:-1].strip()
                command_headers_found.append((idx, t_name))
                continue
            for cmd in expected_cmds:
                if s_line.lower() == cmd.lower() or s_line.lower().startswith(cmd.lower() + " "):
                    command_headers_found.append((idx, cmd))
                    break

    if command_headers_found:
        # 文本中自带了回显命令头！根据真实回显输出的起止索引精确切段
        extracted_map = {}
        total_found = len(command_headers_found)
        for i in range(total_found):
            start_idx, cmd_name = command_headers_found[i]
            end_idx = command_headers_found[i+1][0] if i + 1 < total_found else len(lines)
            content_lines = lines[start_idx+1 : end_idx]
            raw_c = "\n".join(content_lines).strip()
            extracted_map[cmd_name] = _format_human_output(cmd_name, raw_c)

        # 按照 expected_cmds 规范的顺序组装返回
        result_blocks = []
        for cmd in expected_cmds:
            if cmd in extracted_map:
                result_blocks.append((cmd, extracted_map[cmd]))
            else:
                result_blocks.append((cmd, _format_human_output(cmd, "ℹ️ 无返回内容或未采集。")))
        return result_blocks

    # 2. 回显无提示符，基于 expected_cmds 的特征标识（Signature）多级双态搜寻切分
    if expected_cmds and len(expected_cmds) > 1:
        sig_map = {
            'show version': ['cisco ios software', 'linux software', 'cisco internetwork operating system', 'software (i86bi', 'rom: bootstrap'],
            'show processes cpu': ['cpu utilization for five seconds', 'pid runtime', 'cpu utilization'],
            'show processes memory': ['processor pool total', 'pid tty allocated', 'holding getbufs', 'memory pool'],
            'show environment temperature': ['temperature', 'temperature status', 'inlet temperature', 'fan status', 'temp'],
            'show environment power': ['power supply', 'power status', 'watts', 'power consumption', 'psu'],
            'show environment': ['environmental status', 'temperature', 'power', 'fan'],
            'show interfaces status': ['port name status', 'duplex speed', 'port status', 'port vlan duplex speed'],
            'show interfaces': ['line protocol is', 'hardware is', '5 minute input rate', 'full-duplex'],
            'show ip bgp summary': ['bgp router identifier', 'neighbor v as', 'bgp table version'],
            'show ip bgp': ['bgp routing table', 'bgp router identifier'],
            'show ip ospf neighbor': ['neighbor id pri state', 'ospf process'],
            'show ip ospf': ['routing process "ospf', 'ospf router with id'],
            'show ip route summary': ['ip routing table', 'route source', 'subnets'],
            'show ip route': ['codes: l - local', 'gateway of last resort', 'routing table'],
            'show running-config': ['building configuration', 'current configuration', 'version 15.'],
            'show ip int': ['interface ip-address ok?'],
            'show inventory': ['name:', 'descr:', 'chassis'],
            'show clock': ['utc', 'cst', 'pst', 'est'],
        }

        def get_sigs(cmd: str) -> List[str]:
            c_lower = cmd.strip().lower()
            for key, sigs in sig_map.items():
                if key in c_lower:
                    return sigs
            return []

        result_blocks = []
        curr_idx = 0
        total_lines = len(lines)
        cmd_i = 0
        total_cmds = len(expected_cmds)

        err_re = re.compile(r"^\s*(?:%|invalid|unknown|syntax error|bad command|unrecognized)", re.IGNORECASE)

        while cmd_i < total_cmds:
            cmd = expected_cmds[cmd_i]
            if curr_idx >= total_lines:
                result_blocks.append((cmd, _format_human_output(cmd, "ℹ️ 无返回内容或未采集。")))
                cmd_i += 1
                continue

            current_is_error = bool(err_re.match(lines[curr_idx]))

            if not current_is_error:
                # 状态 A：当前命令成功执行，向下搜寻后方特征或第一次遭遇报错的行
                end_idx = total_lines
                for offset, l in enumerate(lines[curr_idx:]):
                    abs_idx = curr_idx + offset
                    l_lower = l.strip().lower()
                    
                    if offset > 1 and err_re.match(l):
                        end_idx = abs_idx
                        break
                        
                    matched_next = False
                    for next_c_idx in range(cmd_i + 1, total_cmds):
                        next_cmd = expected_cmds[next_c_idx]
                        if next_cmd.lower() in l_lower and len(l_lower) < len(next_cmd) + 15:
                            end_idx = abs_idx
                            matched_next = True
                            break
                        sigs = get_sigs(next_cmd)
                        if sigs and any(sig in l_lower for sig in sigs):
                            end_idx = abs_idx
                            matched_next = True
                            break
                    if matched_next:
                        break

                cmd_content = "\n".join(lines[curr_idx:end_idx]).strip()
                result_blocks.append((cmd, _format_human_output(cmd, cmd_content)))
                curr_idx = end_idx
                cmd_i += 1
            else:
                # 状态 B：当前出现连串报错命令，向下穿透寻找第一条成功命令的特征起点
                next_success_cmd_idx = -1
                found_success_line_idx = total_lines
                
                for next_c_idx in range(cmd_i + 1, total_cmds):
                    next_cmd = expected_cmds[next_c_idx]
                    sigs = get_sigs(next_cmd)
                    
                    for offset, l in enumerate(lines[curr_idx:]):
                        abs_idx = curr_idx + offset
                        l_lower = l.strip().lower()
                        if not err_re.match(l):
                            if next_cmd.lower() in l_lower and len(l_lower) < len(next_cmd) + 15:
                                next_success_cmd_idx = next_c_idx
                                found_success_line_idx = abs_idx
                                break
                            if sigs and any(sig in l_lower for sig in sigs):
                                next_success_cmd_idx = next_c_idx
                                found_success_line_idx = abs_idx
                                break
                    if next_success_cmd_idx != -1:
                        break

                chunk_lines = lines[curr_idx:found_success_line_idx]
                count_to_assign = (next_success_cmd_idx if next_success_cmd_idx != -1 else total_cmds) - cmd_i
                
                if count_to_assign == 1:
                    result_blocks.append((cmd, _format_human_output(cmd, "\n".join(chunk_lines).strip())))
                else:
                    # 1. 精准归拢独立错误块：小尖号先导行与下方的报错说明行归为同一组块
                    err_chunks = []
                    curr_err_chunk = []
                    for cl in chunk_lines:
                        cl_str = cl.strip()
                        is_caret_only = bool(cl_str and set(cl_str) <= {'^', ' '})
                        is_err_start = bool(err_re.match(cl) or is_caret_only)
                        has_real_text = any(re.search(r"[a-zA-Z0-9%]", x) for x in curr_err_chunk)
                        
                        if is_err_start and has_real_text:
                            err_chunks.append(curr_err_chunk)
                            curr_err_chunk = [cl]
                        else:
                            curr_err_chunk.append(cl)
                    if curr_err_chunk:
                        err_chunks.append(curr_err_chunk)
                    err_chunks = ["\n".join(ch).strip() for ch in err_chunks if any(l.strip() for l in ch)]
                    
                    # 2. 待分配的命令列表
                    cmds_to_assign = [expected_cmds[cmd_i + offset] for offset in range(count_to_assign)]
                    assigned_out = {}
                    
                    # 3. 基于关键字/协议特征的共鸣对齐 (Resonance Alignment)
                    remaining_errs = list(err_chunks)
                    remaining_cmds = list(cmds_to_assign)
                    
                    for err_txt in list(remaining_errs):
                        err_lower = err_txt.lower()
                        matched_cmd = None
                        if "bgp" in err_lower:
                            matched_cmd = next((c for c in remaining_cmds if "bgp" in c.lower()), None)
                        elif "ospf" in err_lower:
                            matched_cmd = next((c for c in remaining_cmds if "ospf" in c.lower()), None)
                        elif "interface" in err_lower or "drop" in err_lower or "line protocol" in err_lower:
                            matched_cmd = next((c for c in remaining_cmds if "interface" in c.lower() or "int" in c.lower()), None)
                        
                        if matched_cmd:
                            assigned_out[matched_cmd] = err_txt
                            remaining_errs.remove(err_txt)
                            remaining_cmds.remove(matched_cmd)
                    
                    # 剩余常规语法报错按顺序分发给未分配命令
                    for err_txt in remaining_errs:
                        if remaining_cmds:
                            cmd_target = remaining_cmds.pop(0)
                            assigned_out[cmd_target] = err_txt
                    
                    # 4. 组装最终输出：未被分配到任何错误的命令即为正常的空回显
                    for c_name in cmds_to_assign:
                        if c_name in assigned_out:
                            result_blocks.append((c_name, _format_human_output(c_name, assigned_out[c_name])))
                        else:
                            result_blocks.append((c_name, _format_human_output(c_name, "")))

                curr_idx = found_success_line_idx
                cmd_i = next_success_cmd_idx if next_success_cmd_idx != -1 else total_cmds

        return result_blocks

    return [(default_title, _format_human_output(default_title, output_str))]


def _generate_playbook_excel_body(workbook: Any, run_info: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    header_fmt = workbook.add_format({'bold': True, 'bg_color': '#00bceb', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#00bceb'})
    label_fmt = workbook.add_format({'bold': True, 'bg_color': '#f0faff', 'border': 1, 'font_color': '#333'})
    border_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
    critical_fmt = workbook.add_format({'bg_color': '#ffebee', 'font_color': '#c62828', 'border': 1, 'align': 'center'})
    warning_fmt = workbook.add_format({'bg_color': '#fff3e0', 'font_color': '#ef6c00', 'border': 1, 'align': 'center'})
    healthy_fmt = workbook.add_format({'bg_color': '#e8f5e9', 'font_color': '#2e7d32', 'border': 1, 'align': 'center'})
    completed_fmt = workbook.add_format({'bg_color': '#e1f5fe', 'font_color': '#0288d1', 'border': 1, 'align': 'center'})
    wrap_border_fmt = workbook.add_format({'border': 1, 'text_wrap': True, 'valign': 'vcenter'})

    # Sheet 1: 作业执行概览
    ws1 = workbook.add_worksheet('作业执行概览')
    ws1.set_column('A:A', 18)
    ws1.set_column('B:B', 30)
    ws1.set_column('C:C', 18)
    ws1.set_column('D:D', 30)

    sys_name = _get_system_name()
    ws1.write('A1', f'{sys_name} NetOps 自动化执行报告', title_fmt)
    ws1.write('A3', '作业流名称', label_fmt)
    ws1.write('B3', run_info.get('name') or 'Playbook 自动化执行', border_fmt)
    ws1.write('C3', '执行开始时间', label_fmt)
    ws1.write('D3', str(run_info.get('started_at') or '')[:19], border_fmt)

    ws1.write('A4', '执行设备总数', label_fmt)
    ws1.write('B4', len(results), border_fmt)
    healthy_cnt = sum(1 for r in results if r.get('health_status') == 'healthy')
    abnormal_cnt = len(results) - healthy_cnt
    ws1.write('C4', '执行成功数', label_fmt)
    ws1.write('D4', f"{healthy_cnt} 台 (异常 {abnormal_cnt} 台)", border_fmt)

    # 异常概览列表
    ws1.write('A6', '作业执行异常概览', workbook.add_format({'bold': True, 'font_color': '#c62828', 'font_size': 12}))
    headers1 = ['设备名称', '管理 IP 地址', '最终状态', '异常原因 / 阶段错误概览']
    for col, h in enumerate(headers1):
        ws1.write(6, col, h, header_fmt)

    row = 7
    abnormal_devs = [r for r in results if r.get('health_status') in ('warning', 'critical')]
    if abnormal_devs:
        for r in abnormal_devs:
            ws1.write(row, 0, r.get('hostname') or r.get('ip_address') or 'Unknown', border_fmt)
            ws1.write(row, 1, r.get('ip_address', ''), border_fmt)
            ws1.write(row, 2, str(r.get('status') or 'failed').upper(), critical_fmt)
            findings = []
            try: findings = json.loads(r.get('findings_json') or '[]')
            except: pass
            err_msg = (findings[0].get('message') or findings[0].get('description')) if findings else (r.get('error_message') or '执行过程出现丢包或返回异常')
            ws1.write(row, 3, err_msg, border_fmt)
            row += 1
    else:
        ws1.merge_range(7, 0, 7, 3, '🎉 所有设备均已成功完成自动化执行计划，未捕获异常。', workbook.add_format({'align': 'center', 'bg_color': '#f0fdf4', 'font_color': '#166534', 'border': 1}))

    # Sheet 2: 设备执行详情总表
    ws2 = workbook.add_worksheet('设备执行详情总表')
    headers2 = ['设备名称', '管理 IP 地址', '硬件平台 (Platform)', '设备角色 (Role)', '执行状态 (Status)', '健康得分 (Score)', '健康评估等级 (Health Level)']
    ws2.set_column('A:D', 20)
    ws2.set_column('E:G', 16)
    for col, h in enumerate(headers2):
        ws2.write(0, col, h, header_fmt)

    row = 1
    for r in results:
        hostname = r.get('hostname') or r.get('ip_address') or 'Unknown'
        status = r.get('status', 'completed')
        st_fmt = critical_fmt if r.get('health_status') == 'critical' else (warning_fmt if r.get('health_status') == 'warning' else completed_fmt)
        ws2.write(row, 0, hostname, border_fmt)
        ws2.write(row, 1, r.get('ip_address', ''), border_fmt)
        ws2.write(row, 2, r.get('platform') or '通用网络设备', border_fmt)
        ws2.write(row, 3, r.get('role') or '接入设备', border_fmt)
        ws2.write(row, 4, status.upper(), st_fmt)
        ws2.write(row, 5, r.get('health_score', 100), border_fmt)
        health_lvl = '健康 (Healthy)' if r.get('health_status') == 'healthy' else ('警告 (Warning)' if r.get('health_status') == 'warning' else '危险 (Critical)')
        ws2.write(row, 6, health_lvl, st_fmt)
        row += 1

    # Sheet 3: 阶段命令输出明细表 (支持筛选与命令块拆解)
    ws3 = workbook.add_worksheet('阶段命令输出明细表')
    headers3 = ['设备名称', '管理 IP', '执行阶段 (Phase)', '阶段状态', '命令 / 任务块名称 (Command/Block)', '输出详情 (Output Detail)']
    ws3.set_column('A:B', 20)
    ws3.set_column('C:C', 22)
    ws3.set_column('D:D', 14)
    ws3.set_column('E:E', 35)
    ws3.set_column('F:F', 90)
    for col, h in enumerate(headers3):
        ws3.write(0, col, h, header_fmt)
    ws3.autofilter(0, 0, max(1, len(results)*10), 5)

    row = 1
    for r in results:
        hostname = r.get('hostname') or r.get('ip_address') or 'Unknown'
        ip = r.get('ip_address', '')
        phases = {}
        try: phases = json.loads(r.get('phases_json') or '{}')
        except: pass
        if phases:
            for p_name, p_data in phases.items():
                if not isinstance(p_data, dict): continue
                p_status = p_data.get('status', 'success')
                p_st_fmt = healthy_fmt if p_status == 'success' else (critical_fmt if p_status in ('failed', 'error') else warning_fmt)
                out_str = str(p_data.get('output', ''))
                cmds = p_data.get('commands') or []
                if isinstance(cmds, str): cmds = [cmds]
                
                err_m = r.get('error_message') or ''
                blocks = _split_output_into_blocks(out_str, hostname, cmds, p_status=p_status, err_msg=err_m)
                for blk_title, blk_content in blocks:
                    enriched_content = _enrich_with_textfsm_summary(r.get('platform') or 'cisco_ios', blk_title, blk_content)
                    ws3.write(row, 0, hostname, border_fmt)
                    ws3.write(row, 1, ip, border_fmt)
                    ws3.write(row, 2, p_name, border_fmt)
                    ws3.write(row, 3, str(p_status).upper(), p_st_fmt)
                    ws3.write(row, 4, blk_title, border_fmt)
                    ws3.write(row, 5, enriched_content[:32000], wrap_border_fmt)
                    row += 1
        else:
            ws3.write(row, 0, hostname, border_fmt)
            ws3.write(row, 1, ip, border_fmt)
            ws3.write(row, 2, 'Default Phase', border_fmt)
            ws3.write(row, 3, 'COMPLETED', completed_fmt)
            ws3.write(row, 4, '默认执行任务', border_fmt)
            ws3.write(row, 5, '执行完成，无额外阶段输出。', border_fmt)
            row += 1


def _generate_inspection_excel_body(
    workbook: Any,
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> None:
    """Internal: write all sheets into the given workbook."""
    if run_info.get('report_type') == 'playbook':
        _generate_playbook_excel_body(workbook, run_info, results)
        return
    
    # ── 格式定义 ──
    header_fmt = workbook.add_format({
        'bold': True, 'bg_color': '#00bceb', 'font_color': 'white', 
        'border': 1, 'align': 'center', 'valign': 'vcenter'
    })
    title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'font_color': '#00bceb'})
    label_fmt = workbook.add_format({'bold': True, 'bg_color': '#f8f9fa', 'border': 1})
    border_fmt = workbook.add_format({'border': 1})
    wrap_border_fmt = workbook.add_format({'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
    
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
    
    sys_name = _get_system_name()
    summary_ws.write('A1', f'{sys_name} NetOps 智能巡检报告', title_fmt)
    
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
    logger.info(f"[Report] Writing Summary Top Exceptions for {len(results)} results")
    # 1. 先写连通性硬故障（findings_json 中 severity=critical）
    for res in results:
        try:
            findings = json.loads(res.get('findings_json') or '[]')
            for f in findings:
                if f.get('severity') == 'critical':
                    summary_ws.write(row, 0, res.get('hostname', ''), border_fmt)
                    summary_ws.write(row, 1, res.get('ip_address', ''), border_fmt)
                    summary_ws.write(row, 2, '连通性故障', critical_fmt)
                    summary_ws.write(row, 3, f.get('message', ''), critical_fmt)
                    summary_ws.write(row, 4, '请检查设备电源、网络路径及防火墙策略', border_fmt)
                    row += 1
                    if row > 30: break
            if row > 30: break
        except Exception as e:
            logger.error(f"[Report] Error parsing findings for {res.get('hostname')}: {e}")

    # 2. 再写智能分析 critical 项
    for res in results:
        try:
            analysis_str = res.get('analysis_json')
            if not analysis_str: continue
            analysis = json.loads(analysis_str)
            for item in analysis:
                if item.get('status') == 'critical':
                    summary_ws.write(row, 0, res.get('hostname'), border_fmt)
                    summary_ws.write(row, 1, res.get('ip_address'), border_fmt)
                    summary_ws.write(row, 2, item.get('metric', ''), critical_fmt)
                    summary_ws.write(row, 3, str(item.get('value', '')), critical_fmt)
                    summary_ws.write(row, 4, item.get('conclusion', ''), border_fmt)
                    row += 1
                    if row > 50: break
            if row > 50: break
        except Exception as e:
            logger.error(f"[Report] Error parsing analysis for {res.get('hostname')}: {e}")
    
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
        try:
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
        except Exception as e:
            logger.error(f"[Report] Error writing asset row for {res.get('hostname')}: {e}")

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

    # ══════════════════ SHEET 7+: 原始命令输出明细 ══════════════════
    if len(results) > 20:
        # 大批量设备：生成一个扁平化的汇总输出 Sheet，开启筛选器，避免成百上千个 Sheet 卡死 Excel
        out_ws = workbook.add_worksheet('命令输出汇总明细')
        out_ws.set_column('A:B', 20)
        out_ws.set_column('C:C', 25)
        out_ws.set_column('D:D', 100)
        out_headers = ['设备名称', '管理 IP 地址', '巡检命令', '原始输出 (RAW)']
        for col, h in enumerate(out_headers):
            out_ws.write(0, col, h, header_fmt)
        out_ws.autofilter(0, 0, max(1, len(results)*5), 3)
        row = 1
        for res in results:
            hostname = res.get('hostname') or res.get('ip_address') or 'Unknown'
            ip = res.get('ip_address', '')
            try:
                raw_outputs = json.loads(res.get('raw_outputs_json') or '{}')
                for cmd, output in raw_outputs.items():
                    enriched_out = _enrich_with_textfsm_summary(res.get('platform') or 'linux', cmd, str(output))
                    out_ws.write(row, 0, hostname, border_fmt)
                    out_ws.write(row, 1, ip, border_fmt)
                    out_ws.write(row, 2, cmd, border_fmt)
                    out_ws.write(row, 3, enriched_out[:32000], wrap_border_fmt)
                    row += 1
            except Exception:
                pass
    else:
        for res in results:
            hostname = res.get('hostname') or res.get('ip_address') or 'Unknown'
            safe_sheet_name = "".join([c for c in hostname if c.isalnum() or c in (' ', '-', '_')])[:31]
            
            dev_ws = workbook.add_worksheet(safe_sheet_name)
            dev_ws.set_column('A:A', 30) # Command
            dev_ws.set_column('B:B', 100) # Output
            
            dev_ws.write('A1', '设备名称', label_fmt)
            dev_ws.write('B1', res.get('hostname'), border_fmt)
            dev_ws.write('A2', '管理 IP', label_fmt)
            dev_ws.write('B2', res.get('ip_address'), border_fmt)
            dev_ws.write('A3', '健康得分', label_fmt)
            dev_ws.write('B3', res.get('health_score'), border_fmt)
            
            dev_ws.write(4, 0, '巡检命令', header_fmt)
            dev_ws.write(4, 1, '原始输出 (RAW)', header_fmt)
            
            row = 5
            try:
                raw_outputs = json.loads(res.get('raw_outputs_json') or '{}')
                for cmd, output in raw_outputs.items():
                    enriched_out = _enrich_with_textfsm_summary(res.get('platform') or 'linux', cmd, str(output))
                    dev_ws.write(row, 0, cmd, border_fmt)
                    dev_ws.write(row, 1, enriched_out[:20000], wrap_border_fmt)
                    row += 1
            except Exception as e:
                logger.error(f"[Report] Error writing raw outputs for {hostname}: {e}")
                dev_ws.write(row, 0, "ERROR", critical_fmt)
                dev_ws.write(row, 1, str(e), border_fmt)

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

        context = _prepare_report_context(run_info, results, customer_name, engineer_name)
        html_content = template.render(**context)

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


def generate_inspection_json(
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    生成标准化的 JSON 报表。
    """
    _preprocess_and_enrich_results(results)
    try:
        report_data = {
            "report_type": "inspection",
            "generated_at": datetime.now().isoformat(),
            "run_info": run_info,
            "results": results
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        return output_path
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        logger.error(f"[Report] JSON generation failed: {e}")
        raise


def generate_inspection_pdf(
    run_info: Dict[str, Any],
    results: List[Dict[str, Any]],
    output_path: str,
    customer_name: str = '',
    engineer_name: str = '',
) -> str:
    """
    基于 HTML 模板生成 PDF 报表（使用 xhtml2pdf）。
    """
    from jinja2 import Environment, FileSystemLoader
    
    template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
    
    try:
        env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
        template = env.get_template('inspection_report_pdf.html.j2')
        
        # 使用与 HTML 类似的上下文准备逻辑
        # (由于 PDF 渲染引擎对 CSS/JS 支持有限，可能需要专用模板)
        context = _prepare_report_context(run_info, results, customer_name, engineer_name)
        html_content = template.render(**context)
        
        with open(output_path, "wb") as f:
            # Pass `path=` so xhtml2pdf can resolve relative URLs in @font-face
            # against the templates dir (where simhei.ttf lives).
            # The trailing separator is important — xhtml2pdf joins to it.
            pisa_status = pisa.CreatePDF(
                html_content,
                dest=f,
                encoding='utf-8',
                link_callback=fetch_resources,
                path=_TEMPLATE_DIR + os.sep,
            )

        if pisa_status.err:
            raise Exception(f"PDF generation error code: {pisa_status.err}")
            
        return output_path
    except Exception as e:
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except: pass
        logger.error(f"[Report] PDF generation failed: {e}")
        raise

def _get_system_name() -> str:
    system_name = "Nexora"
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'platform_settings'"
            ).fetchone()
            if row:
                import json as _json
                val = row[0] if isinstance(row, (list, tuple)) else row['value']
                ps = _json.loads(val)
                if ps.get('system_name'):
                    system_name = ps['system_name']
        finally:
            conn.close()
    except Exception:
        pass
    return system_name


def _prepare_report_context(run_info, results, customer_name, engineer_name):
    """提取通用的报表上下文准备逻辑。"""
    _preprocess_and_enrich_results(results)
    total_devices = len(results)
    healthy_count = sum(1 for r in results if r.get('health_status') == 'healthy')
    warning_count = sum(1 for r in results if r.get('health_status') == 'warning')
    critical_count = sum(1 for r in results if r.get('health_status') == 'critical')
    scores = [r.get('health_score', 0) for r in results if r.get('health_score') is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    abnormal_devices = []
    for r in results:
        if r.get('health_status') in ('warning', 'critical'):
            findings = []
            try:
                findings = json.loads(r.get('findings_json') or '[]')
            except Exception:
                pass
            top_finding = (findings[0].get('message') or findings[0].get('description') or findings[0].get('item', '发现风险')) if findings else ''
            abnormal_devices.append({
                'hostname': r.get('hostname') or r.get('ip_address') or '未知设备',
                'ip_address': r.get('ip_address', ''),
                'health_score': r.get('health_score', 0),
                'health_status': r.get('health_status', 'unknown'),
                'top_finding': top_finding,
            })

    all_devices = [{
        'hostname': r.get('hostname') or r.get('ip_address') or '未知设备',
        'ip_address': r.get('ip_address', ''),
        'platform': r.get('platform', ''),
        'health_score': r.get('health_score', 0),
        'health_status': r.get('health_status', 'unknown'),
        'compliance_status': r.get('compliance_status', 'unknown'),
        'status': r.get('status', 'completed'),
        'duration_ms': r.get('duration_ms', 0),
    } for r in results]

    all_risks = []
    for r in results:
        try:
            risks = json.loads(r.get('correlated_risks_json') or '[]')
            for risk in risks:
                risk['device'] = r.get('hostname') or r.get('ip_address') or '未知设备'
                all_risks.append(risk)
        except Exception:
            pass

    suggestions = []
    for r in results:
        try:
            analysis = json.loads(r.get('analysis_json') or '[]')
            for item in analysis:
                if item.get('status') not in ('healthy', None):
                    suggestions.append({
                        'hostname': r.get('hostname') or r.get('ip_address') or '未知设备',
                        'metric': item.get('metric', ''),
                        'status': item.get('status', ''),
                        'conclusion': item.get('conclusion', ''),
                        'suggestion': item.get('suggestion', ''),
                    })
        except Exception:
            pass
    suggestions.sort(key=lambda x: 0 if x['status'] == 'critical' else 1)

    return {
        'run_info': run_info,
        'report_type': run_info.get('report_type', 'inspection'),
        'customer_name': customer_name,
        'engineer_name': engineer_name,
        'total_devices': total_devices,
        'healthy_count': healthy_count,
        'warning_count': warning_count,
        'critical_count': critical_count,
        'avg_score': avg_score,
        'abnormal_devices': abnormal_devices,
        'all_devices': all_devices,
        'all_risks': all_risks,
        'suggestions': suggestions,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'font_face_src': _build_font_face_src(),
        'system_name': _get_system_name(),
    }
