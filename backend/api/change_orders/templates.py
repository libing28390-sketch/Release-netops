import logging
from fastapi import APIRouter, HTTPException, Query, Body
from database import get_db_connection
from core.rbac import require_role
from services.change_order_service import (
    get_change_order,
    save_order_as_template,
    list_templates,
    delete_template,
    get_template,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/change-order-templates')
def api_save_as_template(body: dict = Body(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        order_id = body.get('order_id', '')
        name = body.get('name', '').strip()
        description = body.get('description', '').strip()
        if not order_id or not name:
            raise HTTPException(status_code=400, detail='order_id and name are required')
        order = get_change_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail='Change order not found')
        tpl = save_order_as_template(
            conn, name=name, description=description, order=order,
            creator_id=user.get('user_id', ''),
            creator_username=user.get('username', ''),
        )
        return {'success': True, 'data': tpl, 'message': '模板保存成功'}
    finally:
        conn.close()


@router.get('/change-order-templates')
def api_list_templates(mine: str = Query('', description='If "1", only my templates'), user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        creator_id = user.get('user_id', '') if mine == '1' else ''
        return {'success': True, 'data': list_templates(conn, creator_id)}
    finally:
        conn.close()


@router.get('/change-order-templates/{template_id}')
def api_get_template(template_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        tpl = get_template(conn, template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail='Template not found')
        return {'success': True, 'data': tpl}
    finally:
        conn.close()


@router.delete('/change-order-templates/{template_id}')
def api_delete_template(template_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        if not delete_template(conn, template_id):
            raise HTTPException(status_code=404, detail='Template not found')
        return {'success': True, 'message': '模板已删除'}
    finally:
        conn.close()
