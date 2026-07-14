"""
core/textfsm.py — TextFSM 模板管理引擎
========================================
支持双目录合并策略：
  1. data/textfsm_templates/  ← 用户自定义（优先级高，可通过前端管理）
  2. ntc_templates/templates/ ← 官方内置（只读，不修改）

同名模板时，自定义目录优先。
"""
from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_CUSTOM_TEMPLATES_DIR = _PROJECT_ROOT / "data" / "textfsm_templates"

# ── 默认命令采集样本映射 ───────────────────────────────────────────
TEMPLATE_DEFAULT_SAMPLES = {
    'huawei_vrp_display_memory_usage.textfsm': (
        "Memory utilization statistics at 2026-07-14 10:06:07-08:00\n"
        "System Total Memory Is: 171493452 bytes\n"
        "Total Memory Used Is: 123510940 bytes\n"
        "Memory Using Percentage Is: 72%"
    ),
    'huawei_vrp_display_cpu_usage.textfsm': (
        "CPU Usage Stat. Cycle: 10 (Second)\n"
        "CPU utilization for ten seconds: 11.9%\n"
        "one minute: 12.0%\n"
        "five minutes: 12.0%"
    ),
    'hp_comware_display_memory.textfsm': (
        "System Total Memory(bytes): 431869088\n"
        "Total Used Memory(bytes): 71963156\n"
        "Used Rate: 16%"
    ),
    'hp_comware_display_cpu_usage.textfsm': (
        "Unit CPU usage:\n"
        "      Slot 1 CPU 0: 14%\n"
        "      Slot 2 CPU 0:  8%"
    ),
    'hp_comware_display_device.textfsm': (
        "Slot No. Brd Type             Brd Status   Subslot Num  Sft Ver           Patch Ver\n"
        "1        LSW1GT24PSC0         Normal       0            V700R001C01       None"
    ),
    'hp_comware_display_fan.textfsm': (
        "Fan 1 State: Normal\n"
        "Fan 2 State: Absent"
    ),
    'huawei_vrp_display_fan.textfsm': (
        "Slot  FanID  Status  Speed\n"
        "1     1      Normal  60%\n"
        "1     2      Absent  -"
    )
}


def _get_builtin_templates_dir() -> Path | None:
    """获取 ntc_templates 内置模板目录。"""
    try:
        import ntc_templates
        d = Path(ntc_templates.__file__).parent / "templates"
        return d if d.is_dir() else None
    except ImportError:
        return None


def configure_ntc_templates() -> str | None:
    """
    解析 ntc-templates 安装路径并导出 NET_TEXTFSM 环境变量。
    同时确保自定义模板目录存在。
    """
    # 确保自定义目录存在
    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    existing = os.environ.get('NET_TEXTFSM', '').strip()
    if existing and os.path.isdir(existing):
        os.environ['CUSTOM_TEXTFSM'] = str(_CUSTOM_TEMPLATES_DIR)
        return existing

    builtin = _get_builtin_templates_dir()
    if builtin:
        os.environ['NET_TEXTFSM'] = str(builtin)
        os.environ['CUSTOM_TEXTFSM'] = str(_CUSTOM_TEMPLATES_DIR)
        logger.info('TextFSM: builtin=%s, custom=%s', builtin, _CUSTOM_TEMPLATES_DIR)
        return str(builtin)

    logger.warning('ntc-templates not installed; only custom templates will be available')
    os.environ['CUSTOM_TEXTFSM'] = str(_CUSTOM_TEMPLATES_DIR)
    return None


def _template_filename(platform: str, command: str) -> str:
    """
    将 platform + command 转换为标准模板文件名。
    规则：{platform}_{command_words_joined_by_underscore}.textfsm
    例如：cisco_ios + 'show processes cpu' → cisco_ios_show_processes_cpu.textfsm
    """
    cmd_part = re.sub(r'[^a-zA-Z0-9]+', '_', command.strip().lower()).strip('_')
    return f"{platform}_{cmd_part}.textfsm"


def _legacy_template_filename(platform: str, command: str) -> str:
    """Return the ntc-templates naming form that preserves command hyphens."""
    cmd_part = re.sub(r'\s+', '_', command.strip().lower())
    return f"{platform}_{cmd_part}.textfsm"


def _template_filename_variants(platform: str, command: str) -> list[str]:
    """Return current custom naming first, then legacy NTC naming."""
    names = [_template_filename(platform, command)]
    legacy = _legacy_template_filename(platform, command)
    if legacy not in names:
        names.append(legacy)
    return names


def _find_template(platform: str, command: str) -> Path | None:
    """
    按优先级查找模板文件：自定义目录 > 内置目录。
    返回找到的 Path，未找到返回 None。
    """
    builtin = _get_builtin_templates_dir()
    for filename in _template_filename_variants(platform, command):

    # 1. 自定义目录优先
        custom_path = _CUSTOM_TEMPLATES_DIR / filename
        if custom_path.exists():
            return custom_path

    # 2. 内置目录
        if builtin:
            builtin_path = builtin / filename
            if builtin_path.exists():
                return builtin_path

    return None


# 设备命令错误回显特征（小写匹配）：命令不支持 / 功能未启用 / 权限不足等。
# 这类输出不是有效数据，喂给 TextFSM 会触发 State Error，应直接判定为空结果。
_DEVICE_ERROR_KEYWORDS = (
    'invalid input',
    'incomplete command',
    'ambiguous command',
    'unrecognized command',
    'unknown command',
    'not enabled',
    'syntax error',
    'command not found',
    'permission denied',
    'authorization failed',
    'wrong parameter',
    'too many parameters',
    'no such',
    'is not supported',
    'unsupported command',
)


def _looks_like_device_error(output: str) -> str | None:
    """检测设备返回的命令错误回显（如 `%SNMP agent not enabled`、`% Invalid input`）。

    仅在输出较短时判定，避免误伤正常的长输出。匹配则返回该错误行（供日志使用），
    否则返回 None。
    """
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines or len(lines) > 5:
        return None
    for ln in lines:
        low = ln.lower()
        # Cisco 以 % 开头、华为/H3C 以 Error: 开头的多为命令级错误回显
        if ln.startswith('%') or low.startswith('error:'):
            return ln
        if any(kw in low for kw in _DEVICE_ERROR_KEYWORDS):
            return ln
    return None


_HUAWEI_H3C_COMMAND_MAPPING = [
    (re.compile(r'^dis(?:play)?\s+cpu(?:-usage)?\b', re.I), 'display cpu-usage'),
    (re.compile(r'^dis(?:play)?\s+mem(?:ory)?(?:-usage)?\b', re.I), 'display memory-usage'),
    (re.compile(r'^dis(?:play)?\s+memory\b', re.I), 'display memory'),  # For HP Comware
    (re.compile(r'^dis(?:play)?\s+ip\s+routing-table\s+stat(?:istics)?\b', re.I), 'display ip routing-table statistics'),
    (re.compile(r'^dis(?:play)?\s+port\s+vlan\b', re.I), 'display port vlan'),
    (re.compile(r'^dis(?:play)?\s+int(?:erface)?\s+br(?:ief)?\b', re.I), 'display interface brief'),
    (re.compile(r'^dis(?:play)?\s+arp(?:\s+all)?\b', re.I), 'display arp all'),
    (re.compile(r'^dis(?:play)?\s+mac-address\b', re.I), 'display mac-address'),
    (re.compile(r'^dis(?:play)?\s+dev(?:ice)?\b', re.I), 'display device'),
    (re.compile(r'^dis(?:play)?\s+temp(?:erature)?\b', re.I), 'display temperature'),
    (re.compile(r'^dis(?:play)?\s+env(?:ironment)?\b', re.I), 'display environment'),
    (re.compile(r'^dis(?:play)?\s+bfd\s+session\b', re.I), 'display bfd session'),
    (re.compile(r'^dis(?:play)?\s+fan\s+verbose\b', re.I), 'display fan verbose'),
    (re.compile(r'^dis(?:play)?\s+fan\b', re.I), 'display fan'),
    (re.compile(r'^dis(?:play)?\s+pow(?:er)?\b', re.I), 'display power'),
    (re.compile(r'^dis(?:play)?\s+stack\b', re.I), 'display stack'),
    (re.compile(r'^dis(?:play)?\s+irf\b', re.I), 'display irf'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?(?:\s+diag(?:nosis)?)?\s+int(?:erface)?\b', re.I), 'display transceiver interface'),
    (re.compile(r'^dis(?:play)?\s+link-aggregation\s+verbose\b', re.I), 'display link-aggregation verbose'),
]

_COMPATIBLE_PLATFORMS = {
    'cisco_xe': ['cisco_ios'],
    'huawei_vrpv8': ['huawei_vrp'],
    'huawei_smartax': ['huawei_vrp'],
    'huawei_ont': ['huawei_vrp'],
    'huawei_usg': ['huawei_vrp'],
    'h3c_comware': ['hp_comware'],
    'hp_comware': ['h3c_comware'],
    'h3c_comware9': ['h3c_comware'],
}

_STANDARD_FIELDS_MAPPING = {
    'INTF': 'INTERFACE',
    'PORT': 'INTERFACE',
    'LOCAL_INTERFACE': 'INTERFACE',
    'IFNAME': 'INTERFACE',
    'IP': 'IP_ADDRESS',
    'IPADDR': 'IP_ADDRESS',
    'IP_ADDR': 'IP_ADDRESS',
    'ADDRESS': 'IP_ADDRESS',
    'MAC': 'MAC_ADDRESS',
    'MACADDR': 'MAC_ADDRESS',
    'HARDWARE_ADDRESS': 'MAC_ADDRESS',
    'STATE': 'STATUS',
    'LINK_STATUS': 'STATUS',
    'OPER_STATUS': 'STATUS',
}

def _parse_xml_to_dicts(xml_str: str) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_str)
        records = []
        def traverse(node, current_record=None):
            if current_record is None:
                current_record = {}
            children = list(node)
            if not children:
                if node.text and node.text.strip():
                    current_record[node.tag] = node.text.strip()
            else:
                row_data = {}
                has_sub_records = False
                for child in children:
                    if len(child) > 0:
                        has_sub_records = True
                    elif child.text and child.text.strip():
                        row_data[child.tag] = child.text.strip()
                if row_data and not has_sub_records:
                    records.append(row_data)
                for child in children:
                    traverse(child)
        traverse(root)
        return records
    except Exception:
        return []

def smart_parse_cli(
    output: str,
    command: str,
    platform: str | None = None,
    version: str | None = None,
    model: str | None = None
) -> dict[str, Any]:
    """
    智能结构化 CLI 解析引擎。
    按优先级：原生 XML/JSON -> 本地自定义模板 -> 内置 NTC 模板 -> 兼容退级模板。
    包含数据清洗、命令标准化、置信度打分与字段映射归一化。
    """
    import json
    
    # 1. 数据清洗与预处理
    # 剥离 ANSI 颜色代码
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_text = ansi_escape.sub('', output)
    
    cleaned_lines = []
    # 剥离分页提示符、Nexora标记和命令行提示符
    prompt_patterns = [
        re.compile(r'^\[[A-Za-z0-9_\-\.]+\]\s*$'),
        re.compile(r'^[A-Za-z0-9_\-\.]+#\s*$'),
        re.compile(r'^[A-Za-z0-9_\-\.]+(?:\(config[^\)]*\))?#\s*$'),
    ]
    # 仅针对华为、华三和锐捷等设备剥离 <> 提示符，避免对 Junos XML 产生误伤
    if platform and ('huawei' in platform.lower() or 'comware' in platform.lower() or 'ruijie' in platform.lower()):
        prompt_patterns.append(re.compile(r'^<[A-Za-z0-9_\-\.]+>\s*$'))
        
    for line in clean_text.splitlines():
        trimmed = line.strip()
        # 官方 Command Reference 经常把提示符和命令回显写在同一行，
        # 例如 ``<HUAWEI> display version`` 或 ``<Sysname> display memory``。
        # 先剥离提示符前缀，再由下面的命令回显规则丢弃整行，避免把提示符
        # 喂给内置 NTC 模板触发 State Error。
        if platform and ('huawei' in platform.lower() or 'comware' in platform.lower() or 'hp_comware' in platform.lower()):
            prompt_prefix = re.match(
                r'^(?:<[^>\r\n]+>|\[[^\]\r\n]+\]|[^\s#]+#)\s+',
                trimmed,
            )
            if prompt_prefix:
                trimmed = trimmed[prompt_prefix.end():].strip()
                line = trimmed
        if trimmed.startswith('#'):
            continue  # Nexora 内部指令标记
        if platform and 'huawei' in platform.lower() and re.match(
            r'^huawei\s+versatile\s+routing\s+platform\s+software\s*$',
            trimmed,
            re.I,
        ):
            # Huawei 官方回显在不同 VRP 文档中使用 HUAWEI/Huawei 两种大小写；
            # 该 banner 不承载结构化字段，跳过它即可兼容未修改的 NTC 模板。
            continue
        if '--more--' in trimmed.lower():
            continue  # 分页符
        if command.lower() in trimmed.lower() and len(trimmed) < len(command) + 5:
            continue  # 剥离命令行回显
        if any(pat.match(trimmed) for pat in prompt_patterns):
            continue  # 剥离命令行提示符
        cleaned_lines.append(line)
        
    # Keep indentation inside the first output line; many vendor templates
    # intentionally require the leading whitespace used by official examples.
    clean_output = '\n'.join(cleaned_lines).strip('\r\n')
    if not clean_output:
        clean_output = output.strip()
        
    # 2. 检测设备返回的命令错误（功能未启用、不支持等）
    err_line = _looks_like_device_error(clean_output)
    if err_line:
        logger.info('Device returned error/disabled for %s/%s: %s', platform, command, err_line)
        return {
            'success': False,
            'platform': platform,
            'command': command,
            'template': None,
            'template_source': None,
            'confidence': 0.0,
            'candidate_rows': 0,
            'matched_rows': 0,
            'data': [],
            'message': f"设备返回错误回显: {err_line}"
        }
        
    # 3. 命令标准化
    normalized_command = command.strip()
    is_normalized = False
    if platform and ('huawei' in platform.lower() or 'comware' in platform.lower()):
        if 'comware' in platform.lower() and re.match(r'^dis(?:play)?\s+mem(?:ory)?\b', normalized_command, re.I):
            if normalized_command.lower() != 'display memory':
                is_normalized = True
            normalized_command = 'display memory'
        elif 'huawei' in platform.lower() and re.match(r'^dis(?:play)?\s+mem(?:ory)?(?:-usage)?\b', normalized_command, re.I):
            if normalized_command.lower() != 'display memory-usage':
                is_normalized = True
            normalized_command = 'display memory-usage'
        else:
            for regex, canonical in _HUAWEI_H3C_COMMAND_MAPPING:
                if regex.match(normalized_command):
                    if normalized_command.lower() != canonical.lower():
                        is_normalized = True
                    normalized_command = canonical
                    break

                
    # 4. 原生 XML / JSON 解析拦截
    # Juniper 设备的 XML 格式支持
    if platform == 'juniper_junos' and (clean_output.startswith('<') or clean_output.startswith('<?xml')):
        records = _parse_xml_to_dicts(clean_output)
        if records:
            return {
                'success': True,
                'platform': platform,
                'command': normalized_command,
                'template': 'native_xml_parser',
                'template_source': 'junos_xml',
                'confidence': 1.0,
                'candidate_rows': len(records),
                'matched_rows': len(records),
                'data': records,
                'message': '解析成功 (XML 原生解析)'
            }
            
    # NX-OS / Arista EOS JSON 支持
    if platform in ('cisco_nxos', 'arista_eos') and (clean_output.startswith('{') or clean_output.startswith('[')):
        try:
            parsed_json = json.loads(clean_output)
            records = parsed_json if isinstance(parsed_json, list) else [parsed_json]
            return {
                'success': True,
                'platform': platform,
                'command': normalized_command,
                'template': 'native_json_parser',
                'template_source': 'cisco_json',
                'confidence': 1.0,
                'candidate_rows': len(records),
                'matched_rows': len(records),
                'data': records,
                'message': '解析成功 (JSON 原生解析)'
            }
        except Exception:
            pass
            
    # 5. 优先级模板选择与查找
    # 5. 优先级模板选择与查找（收集候选文件列表）
    candidates = []
    if platform:
        builtin_dir = _get_builtin_templates_dir()
        for filename in _template_filename_variants(platform, normalized_command):
            custom_path = _CUSTOM_TEMPLATES_DIR / filename
            if custom_path.exists():
                candidates.append((custom_path, platform, 'custom'))
                break
            if builtin_dir:
                builtin_path = builtin_dir / filename
                if builtin_path.exists():
                    candidates.append((builtin_path, platform, 'builtin'))
                    break

    if platform in _COMPATIBLE_PLATFORMS:
        for compat_p in _COMPATIBLE_PLATFORMS[platform]:
            builtin_dir = _get_builtin_templates_dir()
            for filename in _template_filename_variants(compat_p, normalized_command):
                custom_path = _CUSTOM_TEMPLATES_DIR / filename
                if custom_path.exists():
                    candidates.append((custom_path, compat_p, 'custom'))
                    break
                if builtin_dir:
                    builtin_path = builtin_dir / filename
                    if builtin_path.exists():
                        candidates.append((builtin_path, compat_p, 'builtin'))
                        break

    # 6. 依次执行 TextFSM 解析并评分，成功匹配记录则直接返回
    for template_path, matched_platform, template_source in candidates:
        try:
            import textfsm
            with open(template_path, encoding='utf-8') as f:
                fsm = textfsm.TextFSM(f)
            result = fsm.ParseTextToDicts(clean_output)
            matched_rows = len(result)
            if matched_rows == 0:
                continue  # 如果该模板匹配到的记录行为空，说明不匹配当前回显格式，继续尝试下一个候选模板
                
            # 计算置信度与覆盖率
            from services.textfsm_builder_service import find_header_index
            header_idx = find_header_index(clean_output.splitlines())
            
            candidate_lines = []
            separator_re = re.compile(r"^[\s\-=_+|]{5,}$")
            for idx, line in enumerate(clean_output.splitlines()):
                line_str = line.strip()
                if not line_str: continue
                if separator_re.match(line_str): continue
                if any(pat.match(line_str) for pat in prompt_patterns): continue
                if header_idx is not None and idx <= header_idx: continue
                candidate_lines.append(line_str)
                
            candidate_rows = len(candidate_lines)
            
            # 置信度初始打分
            if candidate_rows > 0:
                coverage = min(1.0, matched_rows / candidate_rows)
            else:
                coverage = 1.0 if matched_rows > 0 else 0.0
                
            confidence = coverage
            if matched_platform != platform:
                confidence *= 0.9  # 平台退级兼容扣分
            if is_normalized:
                confidence *= 0.95  # 命令标准化扣分
                
            confidence = round(max(0.0, min(1.0, confidence)), 2)
            
            # 7. 字段映射标准化
            normalized_records = []
            for record in result:
                norm_record = {}
                for k, v in record.items():
                    norm_key = _STANDARD_FIELDS_MAPPING.get(k.upper(), k.upper())
                    norm_record[norm_key] = v
                normalized_records.append(norm_record)
                
            normalized_records = post_process_parsed_records(normalized_records)
                
            return {
                'success': True,
                'platform': platform,
                'command': normalized_command,
                'template': template_path.name,
                'template_source': template_source,
                'confidence': confidence,
                'candidate_rows': candidate_rows,
                'matched_rows': matched_rows,
                'data': normalized_records,
                'message': '解析成功'
            }
        except Exception as e:
            logger.warning('TextFSM parse failed for candidate %s (%s): %s', template_path.name, template_source, e)
            continue
            
    # 7. 全失败回退到 ntc_templates 原生 parse_output
    try:
        from ntc_templates.parse import parse_output
        parsed = parse_output(platform=platform, command=normalized_command, data=clean_output)
        if isinstance(parsed, list):
            return {
                'success': True,
                'platform': platform,
                'command': normalized_command,
                'template': 'ntc_templates_parse_output',
                'template_source': 'builtin',
                'confidence': 0.9,  # 默认回退 0.9
                'candidate_rows': len(parsed),
                'matched_rows': len(parsed),
                'data': parsed,
                'message': '解析成功 (NTC 原生解析)'
            }
    except Exception:
        pass
        
    return {
        'success': False,
        'platform': platform,
        'command': command,
        'template': None,
        'template_source': None,
        'confidence': 0.0,
        'candidate_rows': 0,
        'matched_rows': 0,
        'data': [],
        'message': '未找到匹配的解析模板，且未匹配到任何原生解析通道'
    }

def parse_with_textfsm(platform: str, command: str, output: str) -> list[dict[str, Any]]:
    """
    带自定义目录优先级的 TextFSM 解析。
    先查 data/textfsm_templates/，再查 ntc_templates 内置目录。
    返回解析后的记录列表，失败返回空列表。
    """
    res = smart_parse_cli(output=output, command=command, platform=platform)
    return res.get('data') or []


def post_process_parsed_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    对解析结果进行单位转换和值同步。
    例如：在 bytes 格式和 MB 格式之间进行换算，或复制内存使用率。
    """
    for record in records:
        # 1. 字节 ➔ MB 换算
        if record.get('SYSTEM_TOTAL_MEMORY') and not record.get('TOTAL_MEMORY_MB'):
            try:
                bytes_val = float(record['SYSTEM_TOTAL_MEMORY'])
                record['TOTAL_MEMORY_MB'] = str(round(bytes_val / (1024 * 1024)))
            except Exception:
                pass
        
        # 2. 内存使用百分比复制
        if record.get('MEMORY_USING_PERCENTAGE') and not record.get('MEMORY_USING_PCT'):
            record['MEMORY_USING_PCT'] = record['MEMORY_USING_PERCENTAGE']
            
        # 3. MB ➔ 字节反向换算
        if record.get('TOTAL_MEMORY_MB') and not record.get('SYSTEM_TOTAL_MEMORY'):
            try:
                mb_val = float(record['TOTAL_MEMORY_MB'])
                record['SYSTEM_TOTAL_MEMORY'] = str(round(mb_val * 1024 * 1024))
            except Exception:
                pass
                
        # 4. 反向复制内存使用百分比
        if record.get('MEMORY_USING_PCT') and not record.get('MEMORY_USING_PERCENTAGE'):
            record['MEMORY_USING_PERCENTAGE'] = record['MEMORY_USING_PCT']
            
    return records


def parse_with_template_content(template_content: str, output: str) -> list[dict[str, Any]]:
    """
    使用给定的模板内容（字符串）直接解析输出。
    用于前端在线测试功能。
    """
    import textfsm
    try:
        fsm = textfsm.TextFSM(io.StringIO(template_content))
        result = fsm.ParseTextToDicts(output)
        if isinstance(result, list):
            result = post_process_parsed_records(result)
            return result
        return []
    except textfsm.TextFSMTemplateError as e:
        raise ValueError(f"模板语法错误: {e}") from e
    except Exception as e:
        raise ValueError(f"解析失败: {e}") from e


# ── 模板管理 CRUD ─────────────────────────────────────────────────────

def list_templates(platform_filter: str = '', search: str = '') -> list[dict[str, Any]]:
    """
    列出所有可用模板（内置 + 自定义），标注来源。
    自定义模板同名时覆盖内置模板（source='custom'）。
    """
    templates: dict[str, dict[str, Any]] = {}

    # 1. 先加载内置模板
    builtin = _get_builtin_templates_dir()
    if builtin:
        for f in sorted(builtin.glob('*.textfsm')):
            info = _parse_template_filename(f.name)
            if info:
                templates[f.name] = {**info, 'source': 'builtin', 'filename': f.name}

    # 2. 自定义模板覆盖（或新增）
    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(_CUSTOM_TEMPLATES_DIR.glob('*.textfsm')):
        info = _parse_template_filename(f.name)
        if info:
            templates[f.name] = {**info, 'source': 'custom', 'filename': f.name}

    result = list(templates.values())

    # 排序：按文件名升序，确保分页稳定性
    result.sort(key=lambda x: x.get('filename', '').lower())

    # 过滤
    if platform_filter:
        result = [t for t in result if t.get('platform', '').lower() == platform_filter.lower()]
    if search:
        s = search.lower()
        result = [t for t in result if s in t.get('filename', '').lower() or s in t.get('command', '').lower()]

    return result


def _template_platform_candidates(platform: str) -> list[str]:
    """Return the exact template platform and safe parser-compatible fallbacks."""
    raw = str(platform or '').strip().lower()
    aliases = {
        'huawei': 'huawei_vrp',
        'vrp': 'huawei_vrp',
        'vrp5': 'huawei_vrp',
        'vrp8': 'huawei_vrpv8',
        'h3c': 'h3c_comware',
        'comware': 'h3c_comware',
        'comware5': 'hp_comware',
        'comware7': 'h3c_comware',
        'comware9': 'h3c_comware9',
        'cisco': 'cisco_ios',
        'ios': 'cisco_ios',
        'iosxe': 'cisco_xe',
    }
    normalized = aliases.get(raw, raw)
    candidates = [normalized] if normalized else []
    candidates.extend(_COMPATIBLE_PLATFORMS.get(normalized, []))
    return list(dict.fromkeys(candidates))


def _command_tokens(value: str) -> list[str]:
    """Split CLI words while treating hyphenated words as equivalent."""
    return [part for part in re.split(r'[^a-z0-9]+', str(value or '').lower()) if part]


def _fuzzy_command_score(query: str, command: str) -> int:
    """Score an abbreviated, ordered CLI query against a template command."""
    query_tokens = _command_tokens(query)
    command_tokens = _command_tokens(command)
    if not query_tokens or not command_tokens:
        return 0
    if not command_tokens[0].startswith(query_tokens[0]):
        return 0

    exact_matches = 0
    if len(query_tokens) > len(command_tokens):
        return 0
    for index, query_token in enumerate(query_tokens):
        candidate = command_tokens[index]
        if candidate == query_token:
            exact_matches += 1
        elif not candidate.startswith(query_token):
            return 0

    return 1000 + exact_matches * 40 + len(query_tokens) * 10 - len(command_tokens)


def list_template_suggestions(platform: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Find available TextFSM commands for one asset platform.

    Every returned command comes from a real built-in or custom template;
    compatible platform entries are considered only after the exact platform.
    """
    normalized_query = str(query or '').strip()
    if len(normalized_query) < 2:
        return []

    platform_candidates = _template_platform_candidates(platform)
    if not platform_candidates:
        return []
    platform_rank = {item: index for index, item in enumerate(platform_candidates)}
    templates = [
        item for item in list_templates()
        if item.get('platform', '').lower() in platform_rank
    ]

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for item in templates:
        command = str(item.get('command') or '').strip()
        score = _fuzzy_command_score(normalized_query, command)
        if score:
            ranked.append((score, platform_rank.get(item.get('platform', '').lower(), 99), item))

    best_by_command: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for entry in ranked:
        command_key = str(entry[2].get('command') or '').lower()
        previous = best_by_command.get(command_key)
        if previous is None or (entry[1], entry[0]) < (previous[1], previous[0]):
            best_by_command[command_key] = entry

    ranked = sorted(
        best_by_command.values(),
        key=lambda entry: (-entry[0], entry[1], len(str(entry[2].get('command') or ''))),
    )[:max(1, min(int(limit or 8), 20))]
    return [
        {
            'platform': item.get('platform', ''),
            'command': item.get('command', ''),
            'filename': item.get('filename', ''),
            'source': item.get('source', ''),
            'score': score,
        }
        for score, _platform_rank, item in ranked
    ]


def _parse_template_filename(filename: str) -> dict[str, Any] | None:
    """
    从文件名解析 platform 和 command。
    文件名格式：{platform}_{command}.textfsm
    """
    if not filename.endswith('.textfsm'):
        return None
    stem = filename[:-len('.textfsm')]

    # 已知平台前缀列表（按长度降序匹配，避免 cisco_ios 被 cisco 截断）
    known_platforms = [
        'cisco_ios', 'cisco_xe', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd', 'cisco_fxos',
        'cisco_wlc', 'cisco_viptela', 'cisco_s300', 'cisco_s200', 'cisco_apic',
        'huawei_vrp', 'huawei_vrpv8', 'huawei_smartax', 'huawei_ont',
        'hp_comware', 'h3c_comware', 'h3c_comware9',
        'juniper_junos', 'juniper_screenos',
        'arista_eos',
        'paloalto_panos',
        'fortinet',
        'checkpoint_gaia',
        'hillstone_stoneos',
        'ruijie_os',
        'ruijie_rgos',
        'zte_zxros',
        'maipu',
        'dcn_dcnos',
        'dptech_conplat',
        'fiberhome_fengine',
        'linux',
        'alcatel_aos', 'alcatel_sros',
        'aruba_aoscx', 'aruba_os',
        'brocade_fastiron', 'brocade_netiron',
        'dell_force10', 'dell_os10',
        'extreme_exos',
        'f5_ltm', 'f5_tmsh',
        'mikrotik_routeros',
        'nokia_sros',
        'vyatta_vyos',
    ]

    for platform in sorted(known_platforms, key=len, reverse=True):
        if stem.startswith(platform + '_'):
            command_part = stem[len(platform) + 1:]
            command = command_part.replace('_', ' ')
            return {'platform': platform, 'command': command, 'stem': stem}

    # 未知平台：取第一段作为 platform
    parts = stem.split('_', 1)
    if len(parts) == 2:
        return {'platform': parts[0], 'command': parts[1].replace('_', ' '), 'stem': stem}

    return {'platform': stem, 'command': '', 'stem': stem}


def get_template_content(filename: str) -> tuple[str, str]:
    """
    获取模板内容。返回 (content, source)。
    source: 'custom' | 'builtin'
    """
    # 安全检查：只允许 .textfsm 文件名，不允许路径穿越
    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    custom_path = _CUSTOM_TEMPLATES_DIR / filename
    if custom_path.exists():
        return custom_path.read_text(encoding='utf-8'), 'custom'

    builtin = _get_builtin_templates_dir()
    if builtin:
        builtin_path = builtin / filename
        if builtin_path.exists():
            return builtin_path.read_text(encoding='utf-8'), 'builtin'

    raise FileNotFoundError(f"模板不存在: {filename}")


def save_custom_template(filename: str, content: str) -> dict[str, Any]:
    """
    保存自定义模板到 data/textfsm_templates/。
    会先验证模板语法。
    """
    import textfsm

    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    # 验证语法
    try:
        textfsm.TextFSM(io.StringIO(content))
    except textfsm.TextFSMTemplateError as e:
        raise ValueError(f"模板语法错误: {e}") from e

    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = _CUSTOM_TEMPLATES_DIR / filename
    path.write_text(content, encoding='utf-8')

    info = _parse_template_filename(filename) or {}
    return {
        'filename': filename,
        'platform': info.get('platform', ''),
        'command': info.get('command', ''),
        'source': 'custom',
        'size': len(content),
    }


def delete_custom_template(filename: str) -> bool:
    """删除自定义模板（只能删自定义的，不能删内置的）。"""
    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    path = _CUSTOM_TEMPLATES_DIR / filename
    if path.exists():
        path.unlink()
        return True
    return False


def get_supported_platforms() -> list[str]:
    """返回所有有模板的平台列表（去重排序）。"""
    platforms = set()
    for t in list_templates():
        p = t.get('platform', '')
        if p:
            platforms.add(p)
    return sorted(platforms)
