import logging
import os
import uuid
import shutil
from typing import Optional
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from database import get_db_connection, PROJECT_ROOT
from core.rbac import require_role
from services.audit_service import log_audit_event
from services.change_order_service import get_change_order

logger = logging.getLogger(__name__)
router = APIRouter()

# MIME whitelist for control-sheet attachments
_CONTROL_SHEET_ALLOWED_MIMES: frozenset[str] = frozenset({
    'application/pdf',
    'application/msword',                                                    # .doc
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/vnd.ms-excel',                                              # .xls
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',    # .xlsx
})

# Extension → canonical MIME
_EXT_TO_MIME: dict[str, str] = {
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls':  'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

# Statuses that allow control-sheet uploads
_CONTROL_SHEET_UPLOAD_STATUSES: frozenset[str] = frozenset({
    'approved', 'implementing', 'completed', 'rolled_back',
})

_CONTROL_SHEET_MAX_BYTES: int = 20 * 1024 * 1024  # 20 MiB


@router.post('/change-orders/{order_id}/control-sheet')
async def api_upload_control_sheet(
    order_id: str,
    file: UploadFile = File(...),
    note: Optional[str] = Form(None),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')

        actor_username = user.get('username', '')
        actor_role = user.get('role', '')
        requester_username = existing.get('requester_username', '')
        if actor_username != requester_username and actor_role != 'Administrator':
            raise HTTPException(
                status_code=403,
                detail='只有工单申请人（实施人）或管理员才能上传变更控制表附件',
            )

        order_status = existing.get('status', '')
        if order_status not in _CONTROL_SHEET_UPLOAD_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'当前工单状态 "{order_status}" 不允许上传变更控制表附件；'
                    f'允许的状态：{", ".join(sorted(_CONTROL_SHEET_UPLOAD_STATUSES))}'
                ),
            )

        client_mime = (file.content_type or '').strip().lower().split(';')[0].strip()
        filename = file.filename or ''
        ext = os.path.splitext(filename)[1].lower()
        resolved_mime = client_mime if client_mime in _CONTROL_SHEET_ALLOWED_MIMES else _EXT_TO_MIME.get(ext, client_mime)

        if resolved_mime not in _CONTROL_SHEET_ALLOWED_MIMES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f'不支持的文件类型 "{client_mime or ext or "unknown"}"；'
                    '仅允许上传 PDF、Word（.doc/.docx）、Excel（.xls/.xlsx）文件'
                ),
            )

        content = await file.read()
        if len(content) > _CONTROL_SHEET_MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f'文件大小超过限制（最大 20 MiB，当前 {len(content) / 1024 / 1024:.1f} MiB）',
            )
        if len(content) == 0:
            raise HTTPException(status_code=400, detail='上传的文件不能为空')

        attachment_id = f"cs-{uuid.uuid4().hex[:12]}"
        safe_ext = ext if ext in _EXT_TO_MIME else '.bin'
        stored_filename = f"{attachment_id}{safe_ext}"
        attachments_dir = os.path.join(PROJECT_ROOT, 'data', 'change_order_attachments')
        os.makedirs(attachments_dir, exist_ok=True)
        file_path = os.path.join(attachments_dir, stored_filename)

        with open(file_path, 'wb') as fh:
            fh.write(content)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

        conn.execute(
            '''
            INSERT INTO change_order_control_sheet_attachments
                (id, order_id, file_path, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (attachment_id, order_id, file_path, filename or stored_filename, len(content), now),
        )

        log_audit_event(
            event_type='change_order.control_sheet_uploaded',
            category='change_order',
            severity='low',
            status='open',
            summary=(
                f"变更工单 {existing['order_number']} 上传了变更控制表附件: "
                f"{filename or stored_filename}"
            ),
            actor_id=user.get('user_id'),
            actor_username=actor_username,
            actor_role=actor_role,
            target_type='change_order',
            target_id=order_id,
            target_name=existing['order_number'],
            details={
                'attachment_id': attachment_id,
                'filename': filename or stored_filename,
                'mime_type': resolved_mime,
                'size_bytes': len(content),
                'note': note or '',
            },
            conn=conn,
        )

        conn.commit()

        return {
            'success': True,
            'data': {
                'id': attachment_id,
                'filename': filename or stored_filename,
                'mime_type': resolved_mime,
                'size_bytes': len(content),
                'uploaded_at': now,
                'note': note or '',
            },
        }
    finally:
        conn.close()


@router.post('/change-orders/{order_id}/attachments')
async def api_upload_attachment(order_id: str, file: UploadFile = File(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        existing = get_change_order(conn, order_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Change order not found')
        
        attachment_id = f"att-{uuid.uuid4().hex[:12]}"
        file_ext = os.path.splitext(file.filename)[1]
        stored_filename = f"{attachment_id}{file_ext}"
        attachments_dir = os.path.join(PROJECT_ROOT, 'data', 'change_order_attachments')
        file_path = os.path.join(attachments_dir, stored_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        conn.execute('''
            INSERT INTO change_order_control_sheet_attachments (id, order_id, file_path, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (attachment_id, order_id, file_path, file.filename, file_size, now))
        conn.commit()
        
        return {'success': True, 'data': {'id': attachment_id, 'file_name': file.filename, 'file_size': file_size}}
    finally:
        conn.close()
