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

from core.rbac import require_role
from core.textfsm import (
    list_templates,
    get_template_content,
    save_custom_template,
    delete_custom_template,
    get_supported_platforms,
    parse_with_template_content,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/textfsm/templates')
def api_list_templates(
    platform: str = Query('', description='按平台过滤'),
    search: str = Query('', description='关键字搜索'),
    source: str = Query('', description='按来源过滤：builtin|custom'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    _user=require_role('Viewer'),
):
    """列出所有模板（内置 + 自定义），自定义模板同名时覆盖内置。"""
    items = list_templates(platform_filter=platform, search=search)
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
def api_list_platforms(_user=require_role('Viewer')):
    """返回所有可用的平台列表（从已加载的模板中提取）。"""
    return {
        'success': True,
        'data': get_supported_platforms(),
        'message': '',
    }


@router.get('/textfsm/templates/{filename}')
def api_get_template(filename: str, _user=require_role('Viewer')):
    """获取单个模板的内容。"""
    try:
        content, source = get_template_content(filename)
        return {
            'success': True,
            'data': {
                'filename': filename,
                'content': content,
                'source': source,
                'editable': source == 'custom',
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
    _user=require_role('Operator'),
):
    """
    创建自定义模板。
    如果同名的内置模板存在，自定义模板会覆盖内置（parse 时优先使用自定义）。

    请求体：
      { "filename": "xxx.textfsm" 或  "platform"+"command" 自动生成, "content": "..." }
    """
    filename = (body.get('filename') or '').strip()
    platform = (body.get('platform') or '').strip().lower()
    command = (body.get('command') or '').strip().lower()
    content = body.get('content') or ''

    if not content:
        raise HTTPException(status_code=400, detail='模板内容不能为空')

    # 如果没有显式 filename，则从 platform + command 生成
    if not filename:
        if not platform or not command:
            raise HTTPException(status_code=400, detail='必须提供 filename 或 (platform + command)')
        import re
        cmd_part = re.sub(r'[^a-zA-Z0-9]+', '_', command).strip('_')
        filename = f"{platform}_{cmd_part}.textfsm"

    if not filename.endswith('.textfsm'):
        filename = f"{filename}.textfsm"

    try:
        result = save_custom_template(filename, content)
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
    _user=require_role('Operator'),
):
    """更新自定义模板内容。"""
    content = body.get('content') or ''
    if not content:
        raise HTTPException(status_code=400, detail='模板内容不能为空')

    try:
        result = save_custom_template(filename, content)
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
    _user=require_role('Operator'),
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
        records = parse_with_template_content(content, sample)
        return {
            'success': True,
            'data': {
                'records': records,
                'count': len(records),
                'fields': list(records[0].keys()) if records else [],
            },
            'message': '解析成功' if records else '模板匹配为空，请检查模板规则是否与样本匹配',
        }
    except ValueError as e:
        return {
            'success': False,
            'data': None,
            'message': str(e),
        }
