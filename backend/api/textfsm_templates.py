"""
TextFSM 模板管理 API
======================
提供内置模板查看、自定义模板管理、在线测试等功能。

模板文件来源：
  1. data/textfsm_templates/     ← 自定义（可增删改）
  2. ntc_templates/templates/    ← 内置（只读）
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Body, HTTPException, Query

from core.rbac import require_permission, require_role
from core.textfsm import (
    list_templates,
    list_template_suggestions,
    get_template_content,
    save_custom_template,
    delete_custom_template,
    get_supported_platforms,
    smart_parse_cli,
    template_action_code,
    canonical_template_filename,
    resolve_textfsm_platform,
    resolve_textfsm_template_namespace,
)
from services.platform_registry_service import (
    get_profile_action_commands,
    iter_action_definitions,
)
from services.textfsm_sandbox_service import TextFSMSandboxError, parse_template_in_sandbox

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/textfsm/templates')
def api_list_templates(
    platform: str = Query('', description='按平台过滤'),
    vendor: str = Query('', description='按厂商过滤'),
    platform_family: str = Query('', description='按平台族过滤，例如 h3c_comware'),
    version: str = Query('', description='按模板版本过滤，例如 v3|v5|v7|v9|common'),
    exact_platform: bool = Query(False, description='是否仅匹配该平台值，不合并兼容别名'),
    search: str = Query('', description='关键字搜索'),
    source: str = Query('', description='按来源过滤：builtin|custom'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    _user=require_permission('textfsm', 'view'),
):
    """列出所有模板（内置 + 自定义），自定义模板同名时覆盖内置。"""
    items = list_templates(
        platform_filter=platform,
        search=search,
        exact_platform=exact_platform,
        vendor_filter=vendor,
        platform_family_filter=platform_family,
        version_filter=version,
    )
    if source:
        items = [t for t in items if t.get('source') == source]
    
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    paginated_items = items[start:end]
    
    return {
        'success': True,
        'data': {
            'total': total,
            'items': paginated_items,
            'page': page,
            'page_size': page_size
        },
        'message': '',
    }


@router.get('/textfsm/platforms')
def api_list_platforms(_user=require_permission('textfsm', 'view')):
    """返回所有可用的平台列表（从已加载的模板中提取）。"""
    return {
        'success': True,
        'data': get_supported_platforms(),
        'message': '',
    }


_H3C_ACTION_PROFILE_ALIASES = {
    'h3c_comware_v3': 'h3c_comware_v3',
    'h3c_comware_v5': 'hp_comware',
    'h3c_comware_v7': 'h3c_comware',
    'h3c_comware_v9': 'h3c_comware9',
}
_TEXTFSM_ACTION_GROUPS = {
    'get_interface_brief': ('基础网络查询', 'Basic network queries'),
    'get_interfaces': ('基础网络查询', 'Basic network queries'),
    'get_ip_interfaces': ('基础网络查询', 'Basic network queries'),
    'get_arp_table': ('基础网络查询', 'Basic network queries'),
    'get_mac_table': ('基础网络查询', 'Basic network queries'),
    'get_vlan_table': ('基础网络查询', 'Basic network queries'),
    'get_lldp_neighbors': ('基础网络查询', 'Basic network queries'),
    'get_transceivers': ('基础网络查询', 'Basic network queries'),
    'get_link_aggregation': ('基础网络查询', 'Basic network queries'),
    'get_route_table': ('路由协议分析', 'Routing protocol analysis'),
    'get_bgp_neighbors': ('路由协议分析', 'Routing protocol analysis'),
    'get_ospf_neighbors': ('路由协议分析', 'Routing protocol analysis'),
    'get_isis_neighbors': ('路由协议分析', 'Routing protocol analysis'),
    'get_stp': ('路由协议分析', 'Routing protocol analysis'),
    'get_bfd_sessions': ('路由协议分析', 'Routing protocol analysis'),
    'get_ntp_status': ('路由协议分析', 'Routing protocol analysis'),
    'get_bgp_routes': ('路由协议分析', 'Routing protocol analysis'),
    'get_version': ('系统状态监控', 'System status monitoring'),
    'get_temperature': ('系统状态监控', 'System status monitoring'),
    'get_fans': ('系统状态监控', 'System status monitoring'),
    'get_power': ('系统状态监控', 'System status monitoring'),
    'get_logbuffer': ('系统状态监控', 'System status monitoring'),
    'get_interface_description': ('系统状态监控', 'System status monitoring'),
    'get_uptime': ('系统状态监控', 'System status monitoring'),
    'get_irf': ('系统状态监控', 'System status monitoring'),
    'get_cpu': ('系统状态监控', 'System status monitoring'),
    'get_memory': ('系统状态监控', 'System status monitoring'),
}
# These actions return opaque configuration text rather than structured
# command output, so they cannot be associated with a TextFSM parser.
_TEXTFSM_EXCLUDED_ACTION_CODES = frozenset({
    'get_running_config',
    'get_startup_config',
})


@router.get('/textfsm/action-options')
def api_textfsm_action_options(
    platform: str = Query('', description='具体解析平台，例如 h3c_comware_v7'),
    _user=require_permission('textfsm', 'view'),
):
    """Return optional, human-readable action associations for template authoring."""
    normalized_platform = str(platform or '').strip().lower()
    profile_code = _H3C_ACTION_PROFILE_ALIASES.get(normalized_platform, normalized_platform)
    parser_platform = resolve_textfsm_platform(normalized_platform) or normalized_platform
    # The action catalog is maintained at the parser-family level for the
    # planned concrete template namespaces.  VRP8 has a legacy parser alias
    # with the same command catalog as the shared Huawei VRP family.
    if parser_platform == 'huawei_vrpv8':
        parser_platform = 'huawei_vrp'
    try:
        commands = get_profile_action_commands({
            'platform_code': profile_code,
            'parser_platform': parser_platform,
        })
    except Exception:
        commands = {}
    items = []
    for definition in iter_action_definitions():
        action_code = str(definition.get('action_code') or '')
        if action_code in _TEXTFSM_EXCLUDED_ACTION_CODES:
            continue
        group_zh, group_en = _TEXTFSM_ACTION_GROUPS.get(
            action_code,
            ('其他查询', 'Other queries'),
        )
        items.append({
            'action_code': action_code,
            'name_zh': definition.get('name_zh') or action_code,
            'name_en': definition.get('name_en') or action_code,
            'purpose': definition.get('purpose') or '',
            'risk': definition.get('risk') or 'low',
            'command': commands.get(action_code),
            'group_zh': group_zh,
            'group_en': group_en,
            'available': bool(commands.get(action_code)),
        })
    return {'success': True, 'data': items, 'message': ''}


@router.get('/textfsm/command-suggestions')
def api_command_suggestions(
    platform: str = Query('', description='资产平台'),
    query: str = Query('', min_length=0, description='命令模糊查询'),
    limit: int = Query(8, ge=1, le=20),
    _user=require_permission('textfsm', 'view'),
):
    """Return real template commands matching an abbreviated CLI query."""
    return {
        'success': True,
        'data': list_template_suggestions(platform, query, limit),
        'message': '',
    }


@router.get('/textfsm/templates/{filename}')
def api_get_template(filename: str, _user=require_permission('textfsm', 'view')):
    """获取单个模板的内容。"""
    try:
        content, source = get_template_content(filename)
        from core.textfsm import TEMPLATE_DEFAULT_SAMPLES
        display_filename = canonical_template_filename(filename)
        default_sample = TEMPLATE_DEFAULT_SAMPLES.get(display_filename, '')
        return {
            'success': True,
            'data': {
                'filename': display_filename,
                'content': content,
                'source': source,
                'editable': source == 'custom',
                'default_sample': default_sample,
                'action_code': template_action_code(content),
            },
            'message': '',
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f'模板不存在: {filename}')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/textfsm/templates')
def api_create_template(
    body: dict = Body(...),
    _user=require_permission('textfsm', 'create'),
):
    """
    创建自定义模板。
    如果同名的内置模板存在，自定义模板会覆盖内置（parse 时优先使用自定义）。

    请求体：
      { "filename": "xxx.textfsm" 或  "platform"+"command" 自动生成,
        "platform_family": "huawei_vrp", "version": "v8", "content": "..." }
    """
    filename = (body.get('filename') or '').strip()
    platform = (body.get('platform') or '').strip().lower()
    platform_family = (body.get('platform_family') or '').strip().lower()
    version = (body.get('version') or '').strip().lower()
    command = (body.get('command') or '').strip().lower()
    action_code = body.get('action_code')
    content = body.get('content') or ''

    if not content:
        raise HTTPException(status_code=400, detail='模板内容不能为空')

    # 如果没有显式 filename，则从 platform + command 生成
    if not filename:
        platform = resolve_textfsm_template_namespace(
            platform,
            platform_family=platform_family,
            version=version,
        )
        if not platform or not command:
            raise HTTPException(status_code=400, detail='必须提供 filename 或 (platform + command)')
        import re
        cmd_part = re.sub(r'[^a-zA-Z0-9]+', '_', command).strip('_')
        filename = f"{platform}_{cmd_part}.textfsm"

    if not filename.endswith('.textfsm'):
        filename = f"{filename}.textfsm"

    try:
        result = save_custom_template(filename, content, action_code=action_code)
        return {'success': True, 'data': result, 'message': '模板已保存'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to save template {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put('/textfsm/templates/{filename}')
def api_update_template(
    filename: str,
    body: dict = Body(...),
    _user=require_permission('textfsm', 'edit_draft'),
):
    """更新自定义模板内容。"""
    content = body.get('content') or ''
    if not content:
        raise HTTPException(status_code=400, detail='模板内容不能为空')

    try:
        if 'action_code' not in body:
            try:
                existing_content, _ = get_template_content(filename)
                action_code = template_action_code(existing_content)
            except FileNotFoundError:
                action_code = None
        else:
            # Explicit null/empty from the editor means "clear association";
            # omission above means preserve the existing metadata.
            action_code = str(body.get('action_code') or '').strip()
        result = save_custom_template(filename, content, action_code=action_code)
        return {'success': True, 'data': result, 'message': '模板已更新'}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update template {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete('/textfsm/templates/{filename}')
def api_delete_template(filename: str, _user=require_role('Administrator')):
    """删除自定义模板（只能删自定义，不能删内置）。"""
    try:
        # 先检查是否是内置的
        try:
            _, source = get_template_content(filename)
            if source == 'builtin':
                raise HTTPException(status_code=403, detail='内置模板不可删除，只能通过上传同名自定义模板进行覆盖')
        except FileNotFoundError:
            pass

        ok = delete_custom_template(filename)
        if not ok:
            raise HTTPException(status_code=404, detail=f'自定义模板不存在: {filename}')
        return {'success': True, 'message': '模板已删除'}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete template {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/textfsm/test')
def api_test_template(
    body: dict = Body(...),
    _user=require_permission('textfsm', 'test'),
):
    """
    在线测试模板：传入模板内容 + 样本输出，返回解析结果。
    用于前端编辑器实时验证。

    请求体：
      { "content": "模板内容", "sample_output": "设备输出" }
    """
    content = body.get('content') or ''
    sample = body.get('sample_output') or ''

    if not content:
        raise HTTPException(status_code=400, detail='模板内容不能为空')
    if not sample:
        raise HTTPException(status_code=400, detail='样本输出不能为空')

    try:
        records = parse_template_in_sandbox(
            content,
            sample,
            timeout_seconds=30,
            max_template_bytes=256_000,
            max_output_bytes=2_000_000,
            max_records=1_000,
            max_fields=128,
        )
        return {
            'success': True,
            'data': {
                'records': records,
                'count': len(records),
                'fields': list(records[0].keys()) if records else [],
            },
            'message': '解析成功' if records else '模板匹配为空，请检查模板规则是否与样本匹配',
        }
    except TextFSMSandboxError as e:
        return {
            'success': False,
            'data': None,
            'error_code': e.code,
            'message': e.message,
        }


@router.post('/textfsm/auto-generate')
def api_auto_generate_template(
    body: dict = Body(...),
    _user=require_permission('textfsm', 'test'),
):
    """
    输入样本输出文本，自动分析表头生成 TextFSM 模板框架。
    """
    sample = body.get('sample_output') or ''
    if not sample:
        raise HTTPException(status_code=400, detail='样本输出内容不能为空')
    
    from services.textfsm_builder_service import auto_generate_template
    try:
        res = auto_generate_template(sample)
        return {
            'success': True,
            'data': {
                'content': res['template'],
                **res
            },
            'message': '模板生成成功'
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/textfsm/smart-parse')
def api_smart_parse_cli(
    body: dict = Body(...),
    _user=require_permission('textfsm', 'test'),
):
    """
    智能结构化 CLI 解析接口，支持输入回显样本、命令、平台以及设备软硬件版本信息进行多层解析。
    """
    output = body.get('output') or ''
    command = body.get('command') or ''
    platform = body.get('platform') or None
    version = body.get('version') or None
    model = body.get('model') or None
    
    if not output:
        raise HTTPException(status_code=400, detail='设备输出内容不能为空')
    if not command:
        raise HTTPException(status_code=400, detail='查询命令不能为空')
        
    try:
        res = smart_parse_cli(
            output=output,
            command=command,
            platform=platform,
            version=version,
            model=model
        )
        return res
    except Exception as e:
        logger.error("Failed to run smart_parse_cli via API: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

