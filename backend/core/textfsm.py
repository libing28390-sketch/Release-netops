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

_TEMPLATE_ACTION_METADATA_RE = re.compile(
    r'^\s*#\s*nexora[-_]action[-_]code\s*:\s*([a-z][a-z0-9_]{2,63})\s*$',
    re.IGNORECASE,
)


def template_action_code(content: str) -> str:
    """Read the optional action association embedded in a template comment."""
    for line in str(content or '').splitlines():
        match = _TEMPLATE_ACTION_METADATA_RE.match(line)
        if match:
            return match.group(1).lower()
    return ''


def _apply_template_action_metadata(content: str, action_code: str | None) -> str:
    """Add/replace the optional action association without changing the rule."""
    raw = str(content or '')
    if action_code is None:
        return raw
    lines = [line for line in raw.splitlines() if not _TEMPLATE_ACTION_METADATA_RE.match(line)]
    cleaned = '\n'.join(lines).lstrip('\n')
    normalized_action = str(action_code or '').strip().lower()
    if normalized_action:
        if not re.fullmatch(r'[a-z][a-z0-9_]{2,63}', normalized_action):
            raise ValueError('action_code 格式不正确')
        cleaned = f'# nexora-action-code: {normalized_action}\n{cleaned}'
    return f'{cleaned}\n' if cleaned else ''

# ── 路径常量 ──────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_CUSTOM_TEMPLATES_DIR = _PROJECT_ROOT / "data" / "textfsm_templates"
# Docker packages the application-default templates outside the persistent
# data volume. This keeps repository updates visible without overwriting
# templates edited or created by users in data/textfsm_templates.
_PACKAGED_TEMPLATES_DIR = _PROJECT_ROOT / "release-textfsm-templates"

# Nexora exposes one H3C/Comware parser family.  Concrete Comware generations
# are selected by the Platform Profile and, where the grammar really differs,
# by an explicit template variant such as ``h3c_comware_v3`` or
# ``h3c_comware_v9``.  ``hp_comware`` is deliberately not a TextFSM alias: it
# is only the literal Netmiko device_type at the transport adapter boundary.
TEXTFSM_PLATFORM_MAP = {
    # Planned concrete template namespaces.  These codes are kept distinct
    # on disk while resolving to the existing parser/driver families at
    # runtime.
    'huawei_vrp5': 'huawei_vrp',
    'huawei_vrp8': 'huawei_vrpv8',
    'huawei_vrp_unknown': 'huawei_vrp',
    'h3c': 'h3c_comware',
    'comware': 'h3c_comware',
    'h3c_comware': 'h3c_comware',
    'h3c_comware_v3': 'h3c_comware',
    'h3c_comware_v5': 'h3c_comware',
    'h3c_comware_v7': 'h3c_comware',
    'h3c_comware_v9': 'h3c_comware',
    'h3c_comware_unknown': 'h3c_comware',
    'ruijie': 'ruijie_rgos',
    'ruijie_os': 'ruijie_rgos',
    'ruijie_rgos': 'ruijie_rgos',
    'ruijie_rgos_v10': 'ruijie_rgos',
    'ruijie_rgos_v11': 'ruijie_rgos',
    'ruijie_rgos_v12': 'ruijie_rgos',
    'ruijie_rgos_unknown': 'ruijie_rgos',
    'dptech': 'dptech_ios',
    'dptech_ios': 'dptech_ios',
    'dptech_conplat': 'dptech_ios',
    'dptech_conplat_fw': 'dptech_ios',
    'dptech_conplat_unknown': 'dptech_ios',
    'maipu': 'maipu',
    'mypower': 'maipu',
    'maipu_mypower': 'maipu',
    'maipu_mypower_v6': 'maipu',
    'maipu_mypower_v8': 'maipu',
    'maipu_mypower_v9': 'maipu',
    'maipu_mypower_unknown': 'maipu',
    'zte': 'zte_zxros',
    'zxros': 'zte_zxros',
    '中兴 zxros': 'zte_zxros',
    'zte_zxros': 'zte_zxros',
    'zte_rosng': 'zte_zxros',
    'zte_os_unknown': 'zte_zxros',
    'raisecom': 'raisecom_ros',
    'raisecom_ros': 'raisecom_ros',
}

_PLANNED_TEMPLATE_PLATFORM_CANDIDATES = {
    'huawei_vrp5': ['huawei_vrp5', 'huawei_vrp'],
    'huawei_vrp8': ['huawei_vrp8', 'huawei_vrpv8', 'huawei_vrp'],
    'huawei_vrp_unknown': ['huawei_vrp_unknown', 'huawei_vrp'],
    # No V3-specific grammar is shipped yet.  V3 is the legacy Comware
    # generation closest to V5, so prefer the verified V5 templates before
    # falling back to the public family namespace.
    'h3c_comware_v3': ['h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware'],
    'h3c_comware_v5': ['h3c_comware_v5', 'h3c_comware'],
    'h3c_comware_v7': ['h3c_comware_v7', 'h3c_comware'],
    'h3c_comware_v9': ['h3c_comware_v9', 'h3c_comware'],
    'h3c_comware_unknown': ['h3c_comware_unknown', 'h3c_comware'],
    'maipu_mypower': ['maipu_mypower', 'maipu'],
    'maipu_mypower_v6': ['maipu_mypower_v6', 'maipu_mypower', 'maipu'],
    'maipu_mypower_v8': ['maipu_mypower_v8', 'maipu_mypower', 'maipu'],
    'maipu_mypower_v9': ['maipu_mypower_v9', 'maipu_mypower', 'maipu'],
    'maipu_mypower_unknown': ['maipu_mypower_unknown', 'maipu_mypower', 'maipu'],
    'ruijie_rgos_v10': ['ruijie_rgos_v10', 'ruijie_rgos'],
    'ruijie_rgos_v11': ['ruijie_rgos_v11', 'ruijie_rgos'],
    'ruijie_rgos_v12': ['ruijie_rgos_v12', 'ruijie_rgos'],
    'ruijie_rgos_unknown': ['ruijie_rgos_unknown', 'ruijie_rgos'],
    'zte_rosng': ['zte_rosng', 'zte_zxros'],
    'zte_os_unknown': ['zte_os_unknown', 'zte_zxros'],
    'dptech_conplat': ['dptech_conplat', 'dptech_ios'],
    'dptech_conplat_unknown': ['dptech_conplat_unknown', 'dptech_conplat', 'dptech_ios'],
}

_PLANNED_TEMPLATE_PLATFORM_VERSIONS = {
    'huawei_vrp5': 'v5',
    'huawei_vrp8': 'v8',
    'huawei_vrp_unknown': 'unknown',
    'h3c_comware_v3': 'v3',
    'h3c_comware_v5': 'v5',
    'h3c_comware_v7': 'v7',
    'h3c_comware_v9': 'v9',
    'h3c_comware_unknown': 'unknown',
    'maipu_mypower_v6': 'v6',
    'maipu_mypower_v8': 'v8',
    'maipu_mypower_v9': 'v9',
    'maipu_mypower_unknown': 'unknown',
    'ruijie_rgos_v10': 'v10',
    'ruijie_rgos_v11': 'v11',
    'ruijie_rgos_v12': 'v12',
    'ruijie_rgos_unknown': 'unknown',
}

_PLANNED_TEMPLATE_PLATFORM_BY_SELECTION = {
    ('huawei_vrp', 'v5'): 'huawei_vrp5',
    ('huawei_vrp', 'v8'): 'huawei_vrp8',
    ('huawei_vrp', 'unknown'): 'huawei_vrp_unknown',
    ('h3c_comware', 'v3'): 'h3c_comware_v3',
    ('h3c_comware', 'v5'): 'h3c_comware_v5',
    ('h3c_comware', 'v7'): 'h3c_comware_v7',
    ('h3c_comware', 'v9'): 'h3c_comware_v9',
    ('h3c_comware', 'unknown'): 'h3c_comware_unknown',
    ('maipu_mypower', 'v6'): 'maipu_mypower_v6',
    ('maipu_mypower', 'v8'): 'maipu_mypower_v8',
    ('maipu_mypower', 'v9'): 'maipu_mypower_v9',
    ('maipu_mypower', 'unknown'): 'maipu_mypower_unknown',
    ('ruijie_rgos', 'v10'): 'ruijie_rgos_v10',
    ('ruijie_rgos', 'v11'): 'ruijie_rgos_v11',
    ('ruijie_rgos', 'v12'): 'ruijie_rgos_v12',
    ('ruijie_rgos', 'unknown'): 'ruijie_rgos_unknown',
}

def resolve_textfsm_platform(platform: str | None) -> str | None:
    """Return the canonical parser platform without changing device identity."""
    raw = str(platform or '').strip().lower()
    return TEXTFSM_PLATFORM_MAP.get(raw, raw or None)


def resolve_textfsm_parser_platform(platform: str | None, version: str | None = None) -> str | None:
    """Resolve the concrete H3C grammar variant used by inventory detection.

    ``h3c_comware`` remains the public parser family stored on a device. The
    concrete V3/V5/V7/V9 grammar is selected directly from the device profile,
    while the Comware major version is the only inventory evidence strong
    enough to select a variant automatically.
    Unknown versions intentionally stay on the family key so the caller can
    require an explicit manual selection.
    """
    raw = str(platform or '').strip().lower()
    if raw in {'h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9'}:
        return raw
    if raw in {'hp_comware', 'h3c_comware9', 'h3c', 'comware', ''}:
        raw = 'h3c_comware'
    if raw != 'h3c_comware':
        return resolve_textfsm_platform(raw)

    match = re.search(r'(?<!\d)([3579])(?:\.|\b)', str(version or '').strip().lower())
    if match:
        return f'h3c_comware_v{match.group(1)}'
    return 'h3c_comware'


_HUAWEI_VRP5_FILENAME_PREFIX = 'huawei_vrp5_'
_LEGACY_HUAWEI_VRP_FILENAME_PREFIX = 'huawei_vrp_'


def _canonical_template_filename(filename: str) -> str:
    """Return the user-facing filename for a supported TextFSM template.

    Huawei VRP's unversioned NTC namespace is the V5 grammar in this catalog.
    Expose that namespace as ``huawei_vrp5_`` so the version is visible in the
    template browser, while keeping the old filename as a read-only lookup
    alias for installed NTC files and existing custom files.

    H3C templates must be named with ``h3c_comware`` (or an explicit
    ``h3c_comware_vN`` variant).  Old HP/H3C9 prefixes are not silently
    rewritten because that hides a wrong profile selection.
    """
    lowered = str(filename or '').strip().lower()
    if lowered.startswith(('hp_comware_', 'h3c_comware9_')):
        raise ValueError(
            'H3C TextFSM 模板必须使用 h3c_comware[_v3|_v5|_v7|_v9] 文件名前缀'
        )
    if (
        lowered.startswith(_LEGACY_HUAWEI_VRP_FILENAME_PREFIX)
        and not lowered.startswith('huawei_vrp_unknown_')
    ):
        suffix = str(filename)[len(_LEGACY_HUAWEI_VRP_FILENAME_PREFIX):]
        return f'{_HUAWEI_VRP5_FILENAME_PREFIX}{suffix}'
    return filename


def canonical_template_filename(filename: str) -> str:
    """Expose the stable template filename used by API responses and UI."""
    return _canonical_template_filename(filename)


def _template_filename_aliases(filename: str) -> list[str]:
    """Return the catalog filename followed by compatible on-disk aliases."""
    canonical = _canonical_template_filename(filename)
    aliases = [canonical]
    if canonical.lower().startswith(_HUAWEI_VRP5_FILENAME_PREFIX):
        suffix = canonical[len(_HUAWEI_VRP5_FILENAME_PREFIX):]
        legacy = f'{_LEGACY_HUAWEI_VRP_FILENAME_PREFIX}{suffix}'
        if legacy not in aliases:
            aliases.append(legacy)
    return aliases


def _template_catalog_file_sort_key(path: Path) -> tuple[int, str]:
    """Prefer an explicit V5 filename when both namespaces are present."""
    lowered = path.name.lower()
    is_legacy_huawei_vrp = (
        lowered.startswith(_LEGACY_HUAWEI_VRP_FILENAME_PREFIX)
        and not lowered.startswith('huawei_vrp_unknown_')
    )
    return (1 if is_legacy_huawei_vrp else 0, lowered)


# ── 默认命令采集样本映射 ───────────────────────────────────────────
# Built-in reference output is intentionally disabled. Users should paste
# the actual device output when testing a template.
TEMPLATE_DEFAULT_SAMPLES: dict[str, str] = {}


def _get_builtin_templates_dir() -> Path | None:
    """获取 ntc_templates 内置模板目录。"""
    try:
        import ntc_templates
        d = Path(ntc_templates.__file__).parent / "templates"
        return d if d.is_dir() else None
    except ImportError:
        return None


def _get_packaged_templates_dir() -> Path | None:
    """Return release-owned templates bundled into the application image."""
    return _PACKAGED_TEMPLATES_DIR if _PACKAGED_TEMPLATES_DIR.is_dir() else None


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
    # A family-level filename is the explicit ``common`` namespace.  Do not
    # silently rewrite it to V7: version selection belongs to the device
    # profile, and a versionless template must remain available as a common
    # fallback for every compatible profile.
    return f"{platform}_{cmd_part}.textfsm"


def _legacy_template_filename(platform: str, command: str) -> str:
    """Return the ntc-templates naming form that preserves command hyphens."""
    cmd_part = re.sub(r'\s+', '_', command.strip().lower())
    return f"{platform}_{cmd_part}.textfsm"


def _legacy_file_fallback_enabled() -> bool:
    """Keep legacy filename lookup explicit during the migration window."""
    return os.environ.get("LEGACY_TEXTFSM_FILE_FALLBACK_ENABLED", "1").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _template_filename_variants(platform: str, command: str) -> list[str]:
    """Return current names first, then compatible legacy NTC names."""
    commands = [command]
    # Comware V7 has a dedicated description grammar, while V5/V9 can safely
    # reuse their ordinary brief grammar when no version-specific description
    # file exists. Keep the exact command first so the dedicated V7 template is
    # selected whenever it is available.
    if str(command or '').strip().lower() == 'display interface brief description':
        commands.append('display interface brief')

    namespaces = [str(platform or '').strip().lower()]
    if namespaces[0] in {'huawei_vrp', 'huawei_vrp5'}:
        # ntc-templates and older custom files use the unversioned Huawei
        # namespace. Keep it as a lookup alias after the explicit V5 name.
        namespaces = ['huawei_vrp5', 'huawei_vrp']

    names: list[str] = []
    for namespace in namespaces:
        for candidate_command in commands:
            current = _template_filename(namespace, candidate_command)
            if current not in names:
                names.append(current)
            legacy = _legacy_template_filename(namespace, candidate_command)
            if _legacy_file_fallback_enabled() and legacy not in names:
                names.append(legacy)
    return names


def _find_template(platform: str, command: str) -> Path | None:
    """
    按优先级查找模板文件：自定义目录 > 内置目录。
    返回找到的 Path，未找到返回 None。
    """
    lookup_command = command
    # Keep direct template lookups (the playbook parse endpoint uses this
    # path before calling smart_parse_cli) aligned with the command aliases
    # understood by the parser.  VRP5 commonly reports optical diagnostics
    # as ``display transceiver verbose`` while the shared grammar is named
    # after ``display transceiver interface``.
    if platform and ('huawei' in platform.lower() or 'comware' in platform.lower()):
        for regex, canonical in _HUAWEI_H3C_COMMAND_MAPPING:
            if regex.match(str(lookup_command).strip()):
                lookup_command = canonical
                break

    packaged = _get_packaged_templates_dir()
    builtin = _get_builtin_templates_dir()
    for parser_platform in _template_platform_candidates(platform):
        for filename in _template_filename_variants(parser_platform, lookup_command):

    # 1. 自定义目录优先
            custom_path = _CUSTOM_TEMPLATES_DIR / filename
            if custom_path.exists():
                return custom_path

    # 2. 发布镜像中的模板目录
            if packaged:
                packaged_path = packaged / filename
                if packaged_path.exists():
                    return packaged_path

    # 3. 内置目录
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
    # The history graph is a separate V5 grammar. It must precede the
    # summary rule because ``display cpu-usage history`` also starts with
    # ``display cpu-usage``.
    (re.compile(r'^dis(?:play)?\s+cpu(?:-usage)?\s+history\b', re.I), 'display cpu-usage history'),
    (re.compile(r'^dis(?:play)?\s+cpu(?:-usage)?\b', re.I), 'display cpu-usage'),
    (re.compile(r'^dis(?:play)?\s+mem(?:ory)?(?:-usage)?\b', re.I), 'display memory-usage'),
    (re.compile(r'^dis(?:play)?\s+memory\b', re.I), 'display memory'),  # For HP Comware
    (re.compile(r'^dis(?:play)?\s+ip\s+routing-table\s+stat(?:istics)?\b', re.I), 'display ip routing-table statistics'),
    (re.compile(r'^dis(?:play)?\s+port\s+vlan\b', re.I), 'display port vlan'),
    # The description form must precede the generic brief form; otherwise the
    # word-boundary after ``brief`` would normalize the longer command to the
    # wrong template namespace.
    (re.compile(r'^dis(?:play)?\s+int(?:erface)?\s+br(?:ief)?\s+description\b', re.I), 'display interface brief description'),
    (re.compile(r'^dis(?:play)?\s+int(?:erface)?\s+br(?:ief)?\b', re.I), 'display interface brief'),
    (re.compile(r'^dis(?:play)?\s+arp(?:\s+all)?\b', re.I), 'display arp all'),
    (re.compile(r'^dis(?:play)?\s+ip\s+routing-table\s*$', re.I), 'display ip routing-table'),
    (re.compile(r'^dis(?:play)?\s+bgp\s+peer\s*$', re.I), 'display bgp peer'),
    (re.compile(r'^dis(?:play)?\s+bgp\s+routing-table\s*$', re.I), 'display bgp routing-table'),
    (re.compile(r'^dis(?:play)?\s+mac-address\b', re.I), 'display mac-address'),
    (re.compile(r'^dis(?:play)?\s+dev(?:ice)?\s+manuinfo\s*$', re.I), 'display device manuinfo'),
    (re.compile(r'^dis(?:play)?\s+dev(?:ice)?\b', re.I), 'display device'),
    (re.compile(r'^dis(?:play)?\s+temp(?:erature)?\b', re.I), 'display temperature'),
    (re.compile(r'^dis(?:play)?\s+env(?:ironment)?\b', re.I), 'display environment'),
    (re.compile(r'^dis(?:play)?\s+bfd\s+session\b', re.I), 'display bfd session'),
    (re.compile(r'^dis(?:play)?\s+fan\s+verbose\b', re.I), 'display fan verbose'),
    (re.compile(r'^dis(?:play)?\s+fan\b', re.I), 'display fan'),
    (re.compile(r'^dis(?:play)?\s+eth-trunk\b', re.I), 'display eth-trunk'),
    (re.compile(r'^dis(?:play)?\s+lldp\s+neighbor\s+brief\b', re.I), 'display lldp neighbor brief'),
    (re.compile(r'^dis(?:play)?\s+pow(?:er)?\b', re.I), 'display power'),
    (re.compile(r'^dis(?:play)?\s+stack\b', re.I), 'display stack'),
    (re.compile(r'^dis(?:play)?\s+irf\b', re.I), 'display irf'),
    # V5 exposes three optical-information commands beside the normal
    # interface view. Keep these before the generic transceiver rule.
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?\s+alarm\b', re.I), 'display transceiver alarm'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?\s+diag(?:nosis)?\b', re.I), 'display transceiver diagnosis'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?\s+manuinfo\b', re.I), 'display transceiver manuinfo'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?(?:\s+(?:diag(?:nosis)?|verbose))?\s+int(?:erface)?\b', re.I), 'display transceiver interface'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?\s+(?:diag(?:nosis)?|verbose)\b', re.I), 'display transceiver interface'),
    (re.compile(r'^dis(?:play)?\s+trans(?:ceiver)?\s*$', re.I), 'display transceiver interface'),
    (re.compile(r'^dis(?:play)?\s+job\b', re.I), 'display job'),
    (re.compile(r'^dis(?:play)?\s+reboot-type\b', re.I), 'display reboot-type'),
    (re.compile(r'^dis(?:play)?\s+link-aggregation\s+verbose\b', re.I), 'display link-aggregation verbose'),
]


def _parse_huawei_lldp_brief_table(output: str) -> list[dict[str, str]]:
    """Parse VRP5/VRP8 LLDP brief tables when a vendor layout drifts.

    Huawei releases use both of these layouts:
    ``Local Intf Neighbor Dev Neighbor Intf Exptime`` and
    ``Local Interface Exptime(s) Neighbor Interface Neighbor Device``.
    The parser intentionally requires numeric interface/expiry columns so
    legends and unrelated CLI lines cannot become topology edges.
    """
    records: list[dict[str, str]] = []
    layout: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {'-', '=', ' ', '\t'}:
            continue
        low = line.lower()
        if 'local intf' in low and 'neighbor dev' in low:
            layout = 'compact'
            continue
        if 'local interface' in low and 'neighbor interface' in low:
            layout = 'expanded'
            continue
        if layout is None:
            continue

        if layout == 'expanded':
            # local, expiry, remote, device (device may contain spaces)
            parts = line.split()
            if len(parts) < 4 or not parts[1].isdigit():
                continue
            local_interface, remote_interface = parts[0], parts[2]
            neighbor_name = ' '.join(parts[3:])
            expired_time = parts[1]
        else:
            # local, device (device may contain spaces), remote, expiry
            parts = line.split()
            if len(parts) < 4 or not parts[-1].isdigit():
                continue
            local_interface, remote_interface = parts[0], parts[-2]
            neighbor_name = ' '.join(parts[1:-2])
            expired_time = parts[-1]

        if not neighbor_name or not any(char.isdigit() for char in local_interface):
            continue
        if not any(char.isdigit() for char in remote_interface):
            continue
        records.append({
            'INTERFACE': local_interface,
            'NEIGHBOR_NAME': neighbor_name,
            'NEIGHBOR_INTERFACE': remote_interface,
            'EXPIRED_TIME': expired_time,
        })
    return records

_COMPATIBLE_PLATFORMS = {
    'cisco_xe': ['cisco_ios'],
    'huawei_vrp': ['huawei_vrpv8'],
    'huawei_vrpv8': ['huawei_vrp'],
    'huawei_smartax': ['huawei_vrp'],
    'huawei_ont': ['huawei_vrp'],
    'huawei_usg': ['huawei_vrp'],
    # H3C generations are selected by a concrete profile/template variant.
    # During the profile migration, however, existing devices can still carry
    # the public ``h3c_comware`` value without a bound profile.  Keep the
    # shipped V9/V5 grammars available for that legacy identity so commands
    # such as ``display link-aggregation verbose`` do not fall through to the
    # generic ntc parser (which loses the parent/member fields).
    'h3c_comware': ['h3c_comware_v9', 'h3c_comware_v5'],
    'ruijie_os': ['ruijie_rgos'],
    'dptech': ['dptech_ios', 'dptech_conplat', 'dptech_conplat_fw'],
    'dptech_conplat': ['dptech_ios', 'dptech_conplat_fw'],
    'dptech_conplat_fw': ['dptech_ios', 'dptech_conplat'],
    'dptech_ios': ['dptech_ios', 'dptech_conplat', 'dptech_conplat_fw'],
    'maipu_mypower': ['maipu'],
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
    parser_platform = resolve_textfsm_platform(platform)
    
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
        # VRP5 command captures may contain a truncated prompt (for example
        # ``<LSW6``) when the terminal output was collected at a page or
        # command boundary.  It is still a prompt fragment, not CLI data.
        prompt_patterns.append(re.compile(r'^<[A-Za-z0-9_\-\.]+>\s*$'))
        prompt_patterns.append(re.compile(r'^<[A-Za-z0-9_\-\.]+\s*$'))
        prompt_patterns.append(re.compile(r'^[A-Za-z0-9_\-\.]+>\s*$'))
        
    for line in clean_text.splitlines():
        trimmed = line.strip()
        # 官方 Command Reference 经常把提示符和命令回显写在同一行，
        # 例如 ``<HUAWEI> display version`` 或 ``<Sysname> display memory``。
        # 先剥离提示符前缀，再由下面的命令回显规则丢弃整行，避免把提示符
        # 喂给内置 NTC 模板触发 State Error。
        if platform and (
            'huawei' in platform.lower()
            or 'comware' in platform.lower()
            or 'cisco' in platform.lower()
        ):
            prompt_prefix = re.match(
                r'^(?:<[^>\r\n]+>|\[[^\]\r\n]+\]|[A-Za-z0-9][^\s#>]*[>#])\s*',
                trimmed,
            )
            if prompt_prefix:
                trimmed = trimmed[prompt_prefix.end():].strip()
                line = trimmed
        if trimmed.startswith('#'):
            continue  # Nexora 内部指令标记
        # Automation exports may wrap each command with a section marker and
        # a bracketed command heading. These are capture metadata, not output.
        if re.match(r'^---\s+.+\s+---$', trimmed):
            continue
        if re.match(r'^\[(?:dis|display)\s+.+\]$', trimmed, re.I):
            continue
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
        # Netmiko/device captures often abbreviate the echoed command (for
        # example ``<LSW6>dis ver`` for ``display version``).  Compare CLI
        # tokens by prefix so abbreviated echoes do not reach TextFSM as data.
        command_tokens = _command_tokens(command)
        echo_tokens = _command_tokens(trimmed)
        if (
            len(echo_tokens) >= 2
            and len(echo_tokens) <= len(command_tokens)
            and command_tokens
            and command_tokens[0].startswith(echo_tokens[0])
            and all(command_tokens[i].startswith(token) for i, token in enumerate(echo_tokens))
        ):
            continue
        if any(pat.match(trimmed) for pat in prompt_patterns):
            continue  # 剥离命令行提示符
        cleaned_lines.append(line)
        
    # Keep indentation inside the first output line; many vendor templates
    # intentionally require the leading whitespace used by official examples.
    clean_output = '\n'.join(cleaned_lines).strip('\r\n')
    if not clean_output:
        clean_output = output.strip()

    # ZTE ZXROS may wrap long peer-port/platform fields across adjacent lines.
    # Keep the merge in the canonical ``show lldp neighbor`` parser path so
    # the same normalization is used by topology and automation collection.
    if platform == 'zte_zxros' and command and 'show lldp neighbor' in command.lower():
        lines = clean_output.splitlines()
        processed_lines = []
        for line in lines:
            match = re.match(r'^(\s{38,44})(\S+)\s*$', line)
            if match and processed_lines:
                port_cont = match.group(2)
                prev_line = processed_lines[-1]
                parts = prev_line.split()
                if len(parts) >= 5:
                    parts[3] = parts[3] + port_cont
                    system_name = " ".join(parts[5:]) if len(parts) > 5 else ""
                    new_line = f"{parts[0]:<17} {parts[1]:<5} {parts[2]:<17} {parts[3]:<30} {parts[4]:<8} {system_name}".strip()
                    processed_lines[-1] = new_line
                    continue
            processed_lines.append(line)
        clean_output = '\n'.join(processed_lines)
        
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
    if parser_platform:
        packaged_dir = _get_packaged_templates_dir()
        builtin_dir = _get_builtin_templates_dir()
        # Keep the original profile selection for H3C variant routing.  Using
        # only the canonical parser family here would make V5/V9 devices use
        # the V7 baseline whenever the same command exists in several files.
        for template_platform in _template_platform_candidates(platform or parser_platform):
            for filename in _template_filename_variants(template_platform, normalized_command):
                custom_path = _CUSTOM_TEMPLATES_DIR / filename
                if custom_path.exists():
                    candidates.append((custom_path, template_platform, 'custom'))
                    break
                if packaged_dir:
                    packaged_path = packaged_dir / filename
                    if packaged_path.exists():
                        candidates.append((packaged_path, template_platform, 'builtin'))
                        break
                if builtin_dir:
                    builtin_path = builtin_dir / filename
                    if builtin_path.exists():
                        candidates.append((builtin_path, template_platform, 'builtin'))
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

            # ``display device manuinfo`` prints ``Subslot`` under the most
            # recent ``Slot`` heading instead of repeating the slot number.
            # Keep the nested record attached to its parent without using
            # TextFSM Filldown (which would otherwise emit a trailing empty
            # record at EOF).
            if template_path.name == 'h3c_comware_v5_display_device_manuinfo.textfsm':
                active_slot = ''
                for record in normalized_records:
                    if record.get('SLOT'):
                        active_slot = str(record['SLOT'])
                    elif record.get('SUBSLOT') and active_slot:
                        record['SLOT'] = active_slot

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
    # Huawei LLDP brief has multiple valid column orders across VRP
    # releases. Keep this fallback at the shared parser boundary so both
    # operational collection and topology discovery receive the same shape.
    if (
        parser_platform
        and ('huawei' in parser_platform.lower() or 'comware' in parser_platform.lower())
        and 'lldp neighbor' in normalized_command.lower()
        and 'brief' in normalized_command.lower()
    ):
        fallback_records = _parse_huawei_lldp_brief_table(clean_output)
        if fallback_records:
            normalized_records = post_process_parsed_records(fallback_records)
            return {
                'success': True,
                'platform': platform,
                'command': normalized_command,
                'template': 'huawei_lldp_neighbor_brief_fallback',
                'template_source': 'builtin',
                'confidence': 0.8,
                'candidate_rows': len(normalized_records),
                'matched_rows': len(normalized_records),
                'data': normalized_records,
                'message': '解析成功 (Huawei LLDP brief 兼容解析)',
            }

    try:
        from ntc_templates.parse import parse_output
        ntc_platform = (
            'hp_comware'
            if parser_platform == 'h3c_comware'
            else parser_platform
        )
        parsed = parse_output(platform=ntc_platform, command=normalized_command, data=clean_output)
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
        # H3C Comware V5 reports memory in bytes, while the V7/V9 table
        # reports it in KB. Expose one user-facing unit across all H3C
        # generations and remove the raw-unit fields from the result.
        h3c_memory_fields = (
            ('TOTAL_BYTES', 'TOTAL_MEMORY_MB', 1024 * 1024),
            ('USED_BYTES', 'USED_MEMORY_MB', 1024 * 1024),
            ('TOTAL_KB', 'TOTAL_MEMORY_MB', 1024),
            ('USED_KB', 'USED_MEMORY_MB', 1024),
            ('FREE_KB', 'FREE_MEMORY_MB', 1024),
            ('SHARED_KB', 'SHARED_MEMORY_MB', 1024),
            ('BUFFERS_KB', 'BUFFERS_MEMORY_MB', 1024),
            ('CACHED_KB', 'CACHED_MEMORY_MB', 1024),
            ('USER_FREE_KB', 'USER_FREE_MEMORY_MB', 1024),
        )
        for source_key, target_key, divisor in h3c_memory_fields:
            if source_key not in record:
                continue
            raw_value = str(record.get(source_key) or '').strip()
            if not raw_value or raw_value == '--':
                converted_value = raw_value
            else:
                try:
                    converted_value = f'{float(raw_value) / divisor:.2f} MB'
                except (TypeError, ValueError):
                    converted_value = raw_value
            record[target_key] = converted_value
            record.pop(source_key, None)

        # Keep percentage units visible in the parsed result. FREE_RATIO is
        # already captured with '%' by the V7/V9 templates, while V5's
        # USED_RATE is normalized here as a defensive fallback.
        for percent_key in ('USED_RATE', 'FREE_RATIO'):
            if percent_key not in record:
                continue
            percent_value = str(record.get(percent_key) or '').strip()
            if percent_value and percent_value != '--' and not percent_value.endswith('%'):
                record[percent_key] = f'{percent_value}%'

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

def list_templates(
    platform_filter: str = '',
    search: str = '',
    *,
    exact_platform: bool = False,
    vendor_filter: str = '',
    platform_family_filter: str = '',
    version_filter: str = '',
) -> list[dict[str, Any]]:
    """
    列出所有可用模板（内置 + 自定义），标注来源。
    自定义模板同名时覆盖内置模板（source='custom'）。
    """
    templates: dict[str, dict[str, Any]] = {}

    # 1. 先加载内置模板
    builtin = _get_builtin_templates_dir()
    if builtin:
        for f in sorted(builtin.glob('*.textfsm'), key=_template_catalog_file_sort_key):
            info = _parse_template_filename(f.name)
            if info:
                catalog_filename = _canonical_template_filename(f.name)
                templates[catalog_filename] = {
                    **_template_catalog_metadata(info),
                    'source': 'builtin',
                    'filename': catalog_filename,
                    'action_code': template_action_code(f.read_text(encoding='utf-8')),
                }

    # 2. 加载随应用打包的只读默认模板
    packaged = _get_packaged_templates_dir()
    if packaged:
        for f in sorted(packaged.glob('*.textfsm'), key=_template_catalog_file_sort_key):
            info = _parse_template_filename(f.name)
            if info:
                catalog_filename = _canonical_template_filename(f.name)
                templates[catalog_filename] = {
                    **_template_catalog_metadata(info),
                    'source': 'builtin',
                    'filename': catalog_filename,
                    'action_code': template_action_code(f.read_text(encoding='utf-8')),
                }

    # 3. 自定义模板覆盖（或新增）
    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(_CUSTOM_TEMPLATES_DIR.glob('*.textfsm'), key=_template_catalog_file_sort_key):
        info = _parse_template_filename(f.name)
        if info:
            catalog_filename = _canonical_template_filename(f.name)
            templates[catalog_filename] = {
                **_template_catalog_metadata(info),
                'source': 'custom',
                'filename': catalog_filename,
                'action_code': template_action_code(f.read_text(encoding='utf-8')),
            }

    result = list(templates.values())

    # 排序：按文件名升序，确保分页稳定性
    result.sort(key=lambda x: x.get('filename', '').lower())

    # 过滤
    if platform_filter:
        requested_raw = platform_filter.strip().lower()
        if exact_platform:
            # Exact filtering means exact public parser family.  H3C variant
            # files already report ``h3c_comware`` from the filename parser;
            # there is no hidden hp_comware/h3c_comware9 aggregation layer.
            result = [t for t in result if str(t.get('platform', '')).strip().lower() == requested_raw]
        else:
            requested_platform = resolve_textfsm_platform(platform_filter) or requested_raw
            result = [
                t for t in result
                if (resolve_textfsm_platform(t.get('platform', '')) or t.get('platform', '').lower()) == requested_platform
            ]
    if vendor_filter:
        requested_vendor = _normalize_template_vendor(vendor_filter)
        result = [
            t for t in result
            if str(t.get('vendor', '')).strip().lower() == requested_vendor
        ]
    if platform_family_filter:
        requested_family = _normalize_template_platform_family(platform_family_filter)
        result = [
            t for t in result
            if str(t.get('platform_family', '')).strip().lower() == requested_family
        ]
    if version_filter:
        requested_version = _normalize_template_version(version_filter)
        result = [
            t for t in result
            if str(t.get('version', '')).strip().lower() == requested_version
        ]
    if search:
        s = search.lower()
        result = [t for t in result if s in t.get('filename', '').lower() or s in t.get('command', '').lower()]

    return result


def _normalize_template_vendor(value: str | None) -> str:
    raw = str(value or '').strip().lower()
    aliases = {
        '华为': 'huawei',
        'huawei': 'huawei',
        '华三': 'h3c',
        'h3c': 'h3c',
        '思科': 'cisco',
        'cisco': 'cisco',
        '锐捷': 'ruijie',
        'ruijie': 'ruijie',
    }
    return aliases.get(raw, raw)


def _normalize_template_platform_family(value: str | None) -> str:
    raw = str(value or '').strip().lower()
    if raw in {'huawei_vrp5', 'huawei_vrp8', 'huawei_vrp_unknown', 'huawei_vrpv8', 'huawei_vrp'}:
        return 'huawei_vrp'
    if raw.startswith('h3c_comware'):
        return 'h3c_comware'
    if raw == 'maipu' or raw.startswith('maipu_mypower'):
        return 'maipu_mypower'
    if raw in {'ruijie', 'ruijie_os'} or raw.startswith('ruijie_rgos'):
        return 'ruijie_rgos'
    if raw in {'zte_zxros', 'zte_rosng', 'zte_os_unknown'}:
        return raw
    if raw in {'dptech', 'dptech_ios', 'dptech_conplat', 'dptech_conplat_fw'}:
        return 'dptech_conplat'
    if raw == 'dptech_conplat_unknown':
        return raw
    return resolve_textfsm_platform(raw) or raw


def _normalize_template_version(value: str | None) -> str:
    raw = str(value or '').strip().lower()
    if raw in {'generic', 'default', 'common', '通用'}:
        return 'common'
    if raw and not raw.startswith('v') and raw.isdigit():
        return f'v{raw}'
    return raw


def resolve_textfsm_template_namespace(
    platform: str | None,
    *,
    platform_family: str | None = None,
    version: str | None = None,
) -> str:
    """Resolve a template filename namespace from the editor selection.

    The UI sends both the selected platform family and version.  Keep the
    concrete namespace in the filename so the catalog can distinguish parser
    variants, while accepting legacy callers that only send ``platform``.
    """
    candidate = str(platform or '').strip().lower()
    family = _normalize_template_platform_family(platform_family or candidate)
    normalized_version = _normalize_template_version(version)

    if family and normalized_version:
        concrete = _PLANNED_TEMPLATE_PLATFORM_BY_SELECTION.get((family, normalized_version))
        if concrete:
            return concrete
        # Maipu historically used the family key for its common grammar.
        if family == 'maipu_mypower' and normalized_version == 'common':
            return 'maipu'

    return candidate or family


def _template_catalog_metadata(info: dict[str, Any]) -> dict[str, Any]:
    """Add stable hierarchy fields without changing the parser platform key."""
    platform = str(info.get('platform') or '').strip().lower()
    if platform.startswith('h3c_comware'):
        vendor = 'h3c'
        platform_family = 'h3c_comware'
    elif platform.startswith('huawei_'):
        vendor = 'huawei'
        platform_family = 'huawei_vrp' if platform in {
            'huawei_vrp', 'huawei_vrpv8', 'huawei_vrp5', 'huawei_vrp8', 'huawei_vrp_unknown',
        } else platform
    elif platform == 'maipu' or platform.startswith('maipu_mypower'):
        vendor = 'maipu'
        platform_family = 'maipu_mypower'
    elif platform in {'ruijie', 'ruijie_os', 'ruijie_rgos'} or platform.startswith('ruijie_rgos_'):
        vendor = 'ruijie'
        platform_family = 'ruijie_rgos'
    elif platform in {'dptech', 'dptech_ios', 'dptech_conplat', 'dptech_conplat_fw'}:
        vendor = 'dptech'
        platform_family = 'dptech_conplat'
    elif platform == 'dptech_conplat_unknown':
        vendor = 'dptech'
        platform_family = 'dptech_conplat_unknown'
    elif platform in {'zte_zxros', 'zte_rosng', 'zte_os_unknown'}:
        vendor = 'zte'
        platform_family = platform
    elif platform.startswith('cisco_'):
        vendor = 'cisco'
        platform_family = platform
    else:
        vendor = platform.split('_', 1)[0] if platform else ''
        platform_family = platform

    version = str(info.get('template_variant') or '').strip().lower()
    if not version:
        version = {
            'huawei_vrp': 'v5',
            'huawei_vrpv8': 'v8',
        }.get(platform, _PLANNED_TEMPLATE_PLATFORM_VERSIONS.get(platform, 'common'))

    return {
        **info,
        'vendor': vendor,
        'platform_family': platform_family,
        'version': version,
    }


# Custom template filenames use underscores because they are safe filenames,
# but several Huawei/H3C commands contain hyphens.  Replacing every underscore
# with a space therefore loses the real CLI spelling (for example
# ``display ip routing-table statistics``).  Keep this small canonical map at
# the template-index boundary so suggestions and template listings expose the
# command that should actually be sent to the device.
_TEMPLATE_COMMAND_CANONICAL: dict[str, dict[str, str]] = {
    'huawei_vrp': {
        'display cpu usage': 'display cpu-usage',
        'display memory usage': 'display memory-usage',
        'display ip routing table statistics': 'display ip routing-table statistics',
        'display ntp service status': 'display ntp-service status',
        'display eth trunk': 'display eth-trunk',
        'display mac address': 'display mac-address',
    },
    'huawei_vrpv8': {
        'display cpu usage': 'display cpu-usage',
        'display memory usage': 'display memory-usage',
        'display ip routing table statistics': 'display ip routing-table statistics',
        'display ntp service status': 'display ntp-service status',
        'display eth trunk': 'display eth-trunk',
        'display mac address': 'display mac-address',
    },
    'h3c_comware': {
        'display cpu usage': 'display cpu-usage',
        'display cpu usage history': 'display cpu-usage history',
        'display bgp routing table': 'display bgp routing-table',
        'display bgp routing table ipv4': 'display bgp routing-table ipv4',
        'display diagnostic information': 'display diagnostic-information',
        'display ip routing table': 'display ip routing-table',
        'display ip routing table statistics': 'display ip routing-table statistics',
        'display ntp service status': 'display ntp-service status',
        'display link aggregation verbose': 'display link-aggregation verbose',
        'display mac address': 'display mac-address',
        'display lldp neighbor information list': 'display lldp neighbor-information list',
        'display reboot type': 'display reboot-type',
        'display system failure': 'display system-failure',
    },
    'cisco_ios': {
        # The NTC filename uses the singular spelling, while IOS/IOS-XE exposes
        # the verified operational command with the plural ``interfaces`` form.
        'show interface transceiver': 'show interfaces transceiver',
    },
    'cisco_nxos': {
        'show ntp peer status': 'show ntp peer-status',
    },
}


def _canonical_template_command(platform: str, command: str) -> str:
    """Return the real CLI spelling represented by a template filename."""
    raw = re.sub(r'\s+', ' ', str(command or '').strip().lower())
    comparison_key = raw.replace('-', ' ')
    platform_key = str(platform or '').lower()
    if platform_key in {'huawei_vrp5', 'huawei_vrp8', 'huawei_vrp_unknown'}:
        platform_key = 'huawei_vrp'
    elif platform_key.startswith('h3c_comware_'):
        platform_key = 'h3c_comware'
    return _TEMPLATE_COMMAND_CANONICAL.get(platform_key, {}).get(comparison_key, command)


def _template_platform_candidates(platform: str) -> list[str]:
    """Return the exact H3C family/variant template namespace to inspect.

    ``h3c_comware`` is the public parser family.  Concrete system Profile
    codes select grammars that are materially different, so this mapping is
    explicit and one-way rather than a public compatibility alias list.
    """
    raw = str(platform or '').strip().lower()
    if raw in _PLANNED_TEMPLATE_PLATFORM_CANDIDATES:
        return list(_PLANNED_TEMPLATE_PLATFORM_CANDIDATES[raw])
    aliases = {
        'huawei': 'huawei_vrp',
        'vrp': 'huawei_vrp',
        'vrp5': 'huawei_vrp',
        'vrp8': 'huawei_vrpv8',
        'h3c': 'h3c_comware',
        'comware': 'h3c_comware',
        # These are stable internal Profile selectors, not public parser
        # platform values.  They route directly to the explicit grammar
        # variants used by the current built-in Profiles.
        'hp_comware': 'h3c_comware_v5',
        'h3c_comware9': 'h3c_comware_v9',
        'h3c_comware_v5': 'h3c_comware_v5',
        'h3c_comware_v7': 'h3c_comware_v7',
        'h3c_comware_v9': 'h3c_comware_v9',
        'cisco': 'cisco_ios',
        'ios': 'cisco_ios',
        'iosxe': 'cisco_xe',
        'dptech': 'dptech_ios',
        'dptech_conplat': 'dptech_ios',
        'dptech_conplat_fw': 'dptech_ios',
    }
    normalized = resolve_textfsm_platform(aliases.get(raw, raw)) or ''
    selected = aliases.get(raw, normalized)
    if selected == 'huawei_vrp5':
        return ['huawei_vrp5', 'huawei_vrp']
    if selected == 'huawei_vrp':
        # The family identity is historically VRP V5. Prefer its explicit
        # namespace, then retain the existing VRP8 compatibility fallback.
        return ['huawei_vrp5', 'huawei_vrp', 'huawei_vrpv8']
    if selected.startswith('h3c_comware_v3'):
        # V3 has no shipped, version-specific grammar yet.  Its legacy CLI
        # forms are closest to the verified V5 templates.
        return ['h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware']
    if selected.startswith('h3c_comware_v5'):
        # V5 has its own command grammars.  Do not downgrade it to the V7
        # grammar when a V5 template is missing.  A versionless template is
        # an explicit common grammar and is safe to try after the exact one.
        return ['h3c_comware_v5', 'h3c_comware']
    if selected.startswith('h3c_comware_v9'):
        # V9 has its own concrete grammar scope. Missing V9 templates must be
        # reported as unsupported instead of falling through to V7. A common
        # template is the only permitted fallback.
        return ['h3c_comware_v9', 'h3c_comware']
    if selected.startswith('h3c_comware_v7'):
        return ['h3c_comware_v7', 'h3c_comware']
    if selected == 'h3c_comware':
        # Current H3C assets are Comware V7. Keep the family key as the
        # persisted public identity, but prefer the current V7 grammar for
        # legacy family callers and then allow a common template. Bound
        # devices use an explicit V5/V7/V9 parser selector above.
        return ['h3c_comware_v7', 'h3c_comware']
    if selected == 'ruijie_rgos':
        # The legacy family value is still stored by existing devices. The
        # current built-in Ruijie profile is RGOS 12, so preserve that
        # backwards-compatible parser path without letting the explicit
        # ``unknown`` profile silently select a release grammar.
        return ['ruijie_rgos_v12', 'ruijie_rgos']
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
    A concrete H3C variant only sees its own grammar plus explicitly common
    templates.  ``list_templates`` intentionally exposes H3C variants under
    the public ``h3c_comware`` family, so the version-aware restriction must
    be applied here before command deduplication.
    """
    normalized_query = str(query or '').strip()
    if len(normalized_query) < 2:
        return []

    normalized_platform = str(platform or '').strip().lower()
    requested_h3c_variant = normalized_platform if normalized_platform in {
        'h3c_comware_v3',
        'h3c_comware_v5',
        'h3c_comware_v7',
        'h3c_comware_v9',
    } else ''
    requested_h3c_version = requested_h3c_variant.rsplit('_', 1)[-1] if requested_h3c_variant else ''
    platform_candidates = _template_platform_candidates(platform)
    if not platform_candidates:
        return []
    platform_rank = {item: index for index, item in enumerate(platform_candidates)}
    templates = [
        item for item in list_templates()
        if str(item.get('platform') or '').lower() in platform_rank
    ]
    if requested_h3c_version:
        allowed_versions = {requested_h3c_version, 'common'}
        if requested_h3c_version == 'v3':
            # Until a real V3 output fixture is registered, expose the
            # verified legacy V5 grammar as the explicit compatibility path.
            allowed_versions.add('v5')
        templates = [
            item for item in templates
            if str(item.get('platform') or '').lower() != 'h3c_comware'
            or str(item.get('version') or '').strip().lower() in allowed_versions
        ]

    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for item in templates:
        command = str(item.get('command') or '').strip()
        score = _fuzzy_command_score(normalized_query, command)
        if score:
            item_platform = str(item.get('platform') or '').lower()
            if requested_h3c_version and item_platform == 'h3c_comware':
                item_version = str(item.get('version') or '').strip().lower()
                template_rank = 0 if item_version == requested_h3c_version else 1
            else:
                template_rank = platform_rank.get(item_platform, 99)
            ranked.append((
                score,
                template_rank,
                item,
            ))

    best_by_command: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for entry in ranked:
        command_key = str(entry[2].get('command') or '').lower()
        previous = best_by_command.get(command_key)
        entry_preference = (
            entry[1],
            -entry[0],
            0 if entry[2].get('source') == 'custom' else 1,
        )
        previous_preference = (
            previous[1],
            -previous[0],
            0 if previous[2].get('source') == 'custom' else 1,
        ) if previous is not None else None
        if previous is None or entry_preference < previous_preference:
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
            'version': item.get('version', ''),
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
    # The external ntc-templates package still ships an HP-prefixed Comware
    # grammar.  It remains an adapter-only fallback for parse_output, but it
    # must not leak into Nexora's template catalog as a second H3C platform.
    if stem.lower().startswith(('hp_comware_', 'h3c_comware9_')):
        return None

    # 已知平台前缀列表（按长度降序匹配，避免 cisco_ios 被 cisco 截断）
    known_platforms = [
        'cisco_ios', 'cisco_xe', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco_ftd', 'cisco_fxos',
        'cisco_wlc', 'cisco_viptela', 'cisco_s300', 'cisco_s200', 'cisco_apic',
        'huawei_vrp_unknown', 'huawei_vrp5', 'huawei_vrp8', 'huawei_vrpv8', 'huawei_vrp',
        'huawei_smartax', 'huawei_ont',
        # H3C uses one public parser family.  Variant prefixes are explicit
        # grammar selectors and are checked before the family prefix.
        'h3c_comware_unknown', 'h3c_comware_v3', 'h3c_comware_v5', 'h3c_comware_v7', 'h3c_comware_v9', 'h3c_comware',
        'juniper_junos', 'juniper_screenos',
        'arista_eos',
        'paloalto_panos',
        'fortinet',
        'checkpoint_gaia',
        'hillstone_stoneos',
        'ruijie_rgos_unknown', 'ruijie_rgos_v10', 'ruijie_rgos_v11', 'ruijie_rgos_v12', 'ruijie_rgos',
        'ruijie_os',
        'zte_os_unknown', 'zte_rosng', 'zte_zxros',
        'raisecom_ros',
        'maipu_mypower_unknown', 'maipu_mypower_v6', 'maipu_mypower_v8', 'maipu_mypower_v9',
        'maipu_mypower', 'maipu',
        'dcn_dcnos',
        'dptech_conplat_unknown', 'dptech_conplat_fw', 'dptech_conplat', 'dptech_ios', 'dptech',
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
            public_platform = 'h3c_comware' if platform.startswith('h3c_comware') else platform
            template_variant = _PLANNED_TEMPLATE_PLATFORM_VERSIONS.get(platform)
            if platform.startswith('h3c_comware_v') or platform == 'h3c_comware_unknown':
                template_variant = platform.rsplit('_', 1)[-1]
            return {
                'platform': public_platform,
                'command': _canonical_template_command(platform, command),
                'stem': stem,
                **({'template_variant': template_variant} if template_variant else {}),
            }

    # 未知平台：取第一段作为 platform
    parts = stem.split('_', 1)
    if len(parts) == 2:
        platform, command = parts[0], parts[1].replace('_', ' ')
        return {
            'platform': platform,
            'command': _canonical_template_command(platform, command),
            'stem': stem,
        }

    return {'platform': stem, 'command': '', 'stem': stem}


def get_template_content(filename: str) -> tuple[str, str]:
    """
    获取模板内容。返回 (content, source)。
    source: 'custom' | 'builtin'
    """
    # 安全检查：只允许 .textfsm 文件名，不允许路径穿越
    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    filename = _canonical_template_filename(filename)
    aliases = _template_filename_aliases(filename)

    for candidate in aliases:
        custom_path = _CUSTOM_TEMPLATES_DIR / candidate
        if custom_path.exists():
            return custom_path.read_text(encoding='utf-8'), 'custom'

    packaged = _get_packaged_templates_dir()
    if packaged:
        for candidate in aliases:
            packaged_path = packaged / candidate
            if packaged_path.exists():
                return packaged_path.read_text(encoding='utf-8'), 'builtin'

    builtin = _get_builtin_templates_dir()
    if builtin:
        for candidate in aliases:
            builtin_path = builtin / candidate
            if builtin_path.exists():
                return builtin_path.read_text(encoding='utf-8'), 'builtin'

    raise FileNotFoundError(f"模板不存在: {filename}")


def save_custom_template(
    filename: str,
    content: str,
    *,
    action_code: str | None = None,
) -> dict[str, Any]:
    """
    保存自定义模板到 data/textfsm_templates/。
    会先验证模板语法。
    """
    import textfsm

    filename = _canonical_template_filename(filename)
    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    # An action association is optional metadata.  If an editor updates a
    # template without sending the field, preserve any existing association
    # already present in the submitted content.
    content = _apply_template_action_metadata(content, action_code)

    # 验证语法
    try:
        textfsm.TextFSM(io.StringIO(content))
    except textfsm.TextFSMTemplateError as e:
        raise ValueError(f"模板语法错误: {e}") from e

    _CUSTOM_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = _CUSTOM_TEMPLATES_DIR / filename
    path.write_text(content, encoding='utf-8')

    info = _parse_template_filename(filename) or {}
    metadata = _template_catalog_metadata(info)
    return {
        'filename': filename,
        'platform': metadata.get('platform', ''),
        'platform_family': metadata.get('platform_family', ''),
        'vendor': metadata.get('vendor', ''),
        'version': metadata.get('version', ''),
        'template_variant': metadata.get('template_variant', ''),
        'command': metadata.get('command', ''),
        'action_code': template_action_code(content),
        'source': 'custom',
        'size': len(content),
    }


def delete_custom_template(filename: str) -> bool:
    """删除自定义模板（只能删自定义的，不能删内置的）。"""
    if not filename.endswith('.textfsm') or '/' in filename or '\\' in filename or '..' in filename:
        raise ValueError(f"非法文件名: {filename}")

    for candidate in _template_filename_aliases(filename):
        path = _CUSTOM_TEMPLATES_DIR / candidate
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
