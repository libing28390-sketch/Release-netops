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


def _find_template(platform: str, command: str) -> Path | None:
    """
    按优先级查找模板文件：自定义目录 > 内置目录。
    返回找到的 Path，未找到返回 None。
    """
    filename = _template_filename(platform, command)

    # 1. 自定义目录优先
    custom_path = _CUSTOM_TEMPLATES_DIR / filename
    if custom_path.exists():
        return custom_path

    # 2. 内置目录
    builtin = _get_builtin_templates_dir()
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


def parse_with_textfsm(platform: str, command: str, output: str) -> list[dict[str, Any]]:
    """
    带自定义目录优先级的 TextFSM 解析。
    先查 data/textfsm_templates/，再查 ntc_templates 内置目录。
    返回解析后的记录列表，失败返回空列表。
    """
    import textfsm

    # ── R3.4: 增强数据清洗，移除命令回显与 Nexora 标记 ────────────────
    cleaned_lines = []
    # 移除以 # 开头的行（Nexora 内部命令标记）以及常见的空行
    for line in output.splitlines():
        trimmed = line.strip()
        # 排除以 # 开头的标记行
        if trimmed.startswith('#'): continue
        # 排除包含该命令本身的行（回显清除）
        if command.lower() in trimmed.lower() and len(trimmed) < len(command) + 5:
            continue
        cleaned_lines.append(line)
    
    clean_output = '\n'.join(cleaned_lines).strip()
    # 如果清洗后为空，则使用原输出（保守策略）
    if not clean_output:
        clean_output = output

    # 设备命令错误回显（功能未启用 / 命令不支持等）——无需解析，直接返回空，
    # 避免 TextFSM 状态机对错误文本抛 State Error，制造误导性的 WARNING 日志。
    err_line = _looks_like_device_error(clean_output)
    if err_line:
        logger.info(
            'Device returned an unsupported/disabled response for %s/%s: %s',
            platform, command, err_line,
        )
        return []

    template_path = _find_template(platform, command)
    if template_path:
        try:
            with open(template_path, encoding='utf-8') as f:
                fsm = textfsm.TextFSM(f)
            result = fsm.ParseTextToDicts(clean_output)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning('TextFSM parse failed for %s/%s: %s', platform, command, e)

    # 回退到 ntc_templates parse_output（兼容旧逻辑）
    try:
        from ntc_templates.parse import parse_output
        parsed = parse_output(platform=platform, command=command, data=clean_output)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def parse_with_template_content(template_content: str, output: str) -> list[dict[str, Any]]:
    """
    使用给定的模板内容（字符串）直接解析输出。
    用于前端在线测试功能。
    """
    import textfsm
    try:
        fsm = textfsm.TextFSM(io.StringIO(template_content))
        result = fsm.ParseTextToDicts(output)
        return result if isinstance(result, list) else []
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
        'cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd', 'cisco_fxos',
        'cisco_wlc', 'cisco_viptela', 'cisco_s300', 'cisco_s200', 'cisco_apic',
        'huawei_vrp', 'huawei_vrpv8', 'huawei_smartax', 'huawei_ont',
        'hp_comware', 'h3c_comware',
        'juniper_junos', 'juniper_screenos',
        'arista_eos',
        'paloalto_panos',
        'fortinet',
        'checkpoint_gaia',
        'hillstone_stoneos',
        'ruijie_os',
        'zte_zxros',
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
