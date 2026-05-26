import logging
from fastapi import APIRouter, HTTPException
from database import get_db_connection
from core.rbac import require_role
from services.change_order_service import (
    get_change_order,
    toggle_bookmark,
    get_user_bookmarks,
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/change-orders/{order_id}/bookmark')
def api_toggle_bookmark(order_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        if not get_change_order(conn, order_id):
            raise HTTPException(status_code=404, detail='Change order not found')
        bookmarked = toggle_bookmark(conn, user.get('user_id', ''), order_id)
        return {'success': True, 'data': {'bookmarked': bookmarked}}
    finally:
        conn.close()


@router.get('/change-orders-bookmarks')
def api_get_my_bookmarks(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        order_ids = get_user_bookmarks(conn, user.get('user_id', ''))
        return {'success': True, 'data': order_ids}
    finally:
        conn.close()
