"""
配置变更审批服务 — 验证码生成、存储、验证与飞书发送。

流程：
1. 操作员填写审批人用户名 + 变更原因
2. 后端生成 6 位数字验证码，通过审批人的飞书 webhook 发送
3. 操作员输入验证码，后端校验后放行配置操作
4. 验证码 5 分钟过期，3 次失败后自动作废
"""

import json
import logging
import re
import secrets
import time
from datetime import datetime
from database import get_db_connection
from services import notification_service

logger = logging.getLogger(__name__)

# 内存存储：approval_token -> 审批记录
# 生产环境建议换成 Redis
_pending_approvals: dict[str, dict] = {}

# 配置常量
CODE_LENGTH = 6
CODE_EXPIRY_SECONDS = 300   # 5 分钟
MAX_VERIFY_ATTEMPTS = 3
APPROVAL_VERIFICATION_METHODS = frozenset({'feishu', 'email', 'mfa'})
_EMAIL_ADDRESS_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


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


def _generate_code() -> str:
    """生成 6 位数字验证码（安全随机）。"""
    return ''.join([str(secrets.randbelow(10)) for _ in range(CODE_LENGTH)])


def _cleanup_expired():
    """清理过期记录。"""
    now = time.time()
    expired = [k for k, v in _pending_approvals.items() if now - v['created_at'] > CODE_EXPIRY_SECONDS + 60]
    for k in expired:
        del _pending_approvals[k]


def _normalized_tenant_id(value: object) -> str:
    return str(value or '').strip() or 'tenant-default'


def _parse_notification_channels(value: object) -> dict:
    try:
        channels = json.loads(value or '{}') if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError):
        channels = {}
    return channels if isinstance(channels, dict) else {}


def _email_delivery_route(connection, approver: dict) -> tuple[dict | None, list[str]]:
    """Resolve one enabled SMTP profile that may deliver to this approver."""
    email = str(approver.get('email') or '').strip().lower()
    if not _EMAIL_ADDRESS_RE.fullmatch(email):
        return None, []

    profiles = notification_service.get_email_profiles_for_dispatch(
        connection,
        _normalized_tenant_id(approver.get('tenant_id')),
        enabled_only=True,
    )
    approver_row = dict(approver)
    approver_row['email'] = email

    # Prefer a profile explicitly assigned to this user or their group.
    for profile in profiles:
        targets = notification_service._profile_targets(profile)
        if not targets:
            continue
        recipients = notification_service._profile_email_recipients(profile, [approver_row])
        if email in recipients:
            return profile, [email]

    # The legacy primary profile is the system fallback for direct user mail.
    for profile in profiles:
        if str(profile.get('name') or '').strip().lower() == 'primary':
            if not notification_service._profile_targets(profile):
                return profile, [email]
    return None, []


def _approval_methods_for_user(connection, approver: dict) -> list[str]:
    methods = []
    if bool(approver.get('mfa_enabled')) and str(approver.get('mfa_secret') or '').strip():
        methods.append('mfa')
    smtp_profile, email_recipients = _email_delivery_route(connection, approver)
    if smtp_profile and email_recipients:
        methods.append('email')
    channels = _parse_notification_channels(approver.get('notification_channels'))
    feishu = channels.get('feishu') or {}
    if feishu.get('enabled') and str(feishu.get('webhook_url') or '').strip():
        methods.append('feishu')
    return methods


def list_approvers_with_methods(tenant_id: str) -> list[dict]:
    """Return eligible approvers and safe method flags, never secrets/addresses."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, username, role, status, email, group_name,
                   tenant_id, mfa_enabled, mfa_secret, notification_channels
              FROM users
             WHERE COALESCE(NULLIF(tenant_id, ''), 'tenant-default') = ?
               AND status = 'active'
               AND role IN ('Administrator', 'Operator')
             ORDER BY username
            """,
            (_normalized_tenant_id(tenant_id),),
        ).fetchall()
        result = []
        for row in rows:
            approver = dict(row)
            methods = _approval_methods_for_user(conn, approver)
            if methods:
                result.append({
                    'id': str(approver.get('id') or ''),
                    'username': str(approver.get('username') or ''),
                    'role': str(approver.get('role') or ''),
                    'verification_methods': methods,
                })
        return result
    finally:
        conn.close()


def _get_approver_for_request(
    approver_username: str,
    requester_id: str | None,
    requester_username: str,
    requester_tenant_id: str | None,
) -> tuple[dict | None, str | None]:
    conn = get_db_connection()
    try:
        approver_row = conn.execute(
            """
            SELECT id, username, role, status, email, group_name, tenant_id,
                   mfa_enabled, mfa_secret, notification_channels
              FROM users WHERE username = ?
            """,
            (approver_username,),
        ).fetchone()
        if not approver_row:
            return None, '所选审批人不存在'
        approver = dict(approver_row)
        if approver.get('status') != 'active' or approver.get('role') not in {'Administrator', 'Operator'}:
            return None, '所选审批人账号未启用或不具备审批权限'

        requester = None
        if requester_id:
            requester_row = conn.execute(
                "SELECT id, username, status, tenant_id FROM users WHERE id = ?",
                (requester_id,),
            ).fetchone()
            requester = dict(requester_row) if requester_row else None
        elif requester_username:
            requester_row = conn.execute(
                "SELECT id, username, status, tenant_id FROM users WHERE username = ?",
                (requester_username,),
            ).fetchone()
            requester = dict(requester_row) if requester_row else None

        if (requester_id or requester_username) and requester is None:
            return None, '当前操作账号无法核验，无法发起审批'

        if requester is not None:
            if requester.get('status') != 'active':
                return None, '当前操作账号已停用，无法发起审批'
            if str(requester.get('username') or '') != requester_username:
                return None, '审批申请人与当前登录账号不一致'
            requester_tenant_id = str(requester.get('tenant_id') or '')

        expected_tenant = _normalized_tenant_id(requester_tenant_id)
        if _normalized_tenant_id(approver.get('tenant_id')) != expected_tenant:
            return None, '审批人与当前操作账号不属于同一租户'
        return approver, None
    finally:
        conn.close()


def request_approval(
    approver_username: str,
    requester_username: str,
    config_reason: str,
    device_hostname: str = '',
    command_preview: str = '',
    approval_type: str = 'config',
    extra_fields: dict | None = None,
    verification_method: str = 'feishu',
    requester_id: str | None = None,
    requester_tenant_id: str | None = None,
) -> tuple[str | None, str | None]:
    """
    创建限时审批请求，可通过飞书、邮箱验证码或审批人 TOTP MFA 验证。

    Args:
        approval_type: 审批业务类型，消费时可要求与请求类型一致。
        extra_fields: 额外展示字段，如 {'action_type': '配置备份', 'cron_expr': '0 2 * * *'}
        verification_method: feishu、email 或 mfa。未传时兼容旧调用，默认飞书。

    Returns:
        (approval_token, error_message) — 成功时 token 非空, error 为空; 反之亦然
    """
    _cleanup_expired()
    method = str(verification_method or 'feishu').strip().lower()
    if method not in APPROVAL_VERIFICATION_METHODS:
        return None, '不支持的审批验证方式'

    approver, err = _get_approver_for_request(
        approver_username,
        requester_id,
        requester_username,
        requester_tenant_id,
    )
    if err:
        return None, err

    conn = get_db_connection()
    try:
        available_methods = _approval_methods_for_user(conn, approver)
        smtp_profile, email_recipients = (
            _email_delivery_route(conn, approver) if method == 'email' else (None, [])
        )
    finally:
        conn.close()

    if method not in available_methods:
        errors = {
            'mfa': '所选审批人尚未启用 MFA 动态验证',
            'email': '审批人未配置可用邮箱或 SMTP 邮件服务',
            'feishu': '审批人未配置可用的飞书审批通知',
        }
        return None, errors[method]

    # MFA codes are generated by the approver's authenticator. Email and
    # Feishu use a short-lived server-generated code.
    code = None if method == 'mfa' else _generate_code()
    approval_token = secrets.token_urlsafe(32)
    created_at = time.time()

    record = {
        'code': code,
        'verification_method': method,
        'approval_type': str(approval_type or 'config').strip() or 'config',
        'approver_id': str(approver.get('id') or ''),
        'approver': approver_username,
        'requester_id': str(requester_id or ''),
        'requester': requester_username,
        'requester_tenant_id': _normalized_tenant_id(requester_tenant_id or approver.get('tenant_id')),
        'config_reason': config_reason,
        'device_hostname': device_hostname,
        'command_preview': command_preview,
        'extra_fields': dict(extra_fields or {}),
        'created_at': created_at,
        'attempts': 0,
        'verified': False,
    }
    _pending_approvals[approval_token] = record

    if method == 'mfa':
        logger.info(
            "[ConfigApproval] MFA approval requested for approver_id=%s requester_id=%s type=%s",
            record['approver_id'], record['requester_id'], record['approval_type'],
        )
        return approval_token, None

    extra = extra_fields or {}
    sys_name = _get_system_name()
    type_config = {
        'config': {'title': f'🔐 {sys_name} 配置变更审批', 'template': 'orange'},
        'scheduled_job': {'title': f'⏰ {sys_name} 定时作业审批', 'template': 'blue'},
        'scheduled_job_delete': {'title': f'🗑️ {sys_name} 定时作业删除审批', 'template': 'red'},
        'execution_plan': {'title': f'📋 {sys_name} 执行计划审批', 'template': 'turquoise'},
        'alert_rule': {'title': f'🛡️ {sys_name} 告警规则变更审批', 'template': 'red'},
        'alert_rule_delete': {'title': f'⚠️ {sys_name} 告警规则删除审批', 'template': 'rose'},
    }
    tc = type_config.get(approval_type, type_config['config'])

    if method == 'email':
        email_result = notification_service.send_email(
            smtp_profile,
            email_recipients,
            {
                'title': f'{sys_name} 安全审批验证码',
                'severity': 'info',
                'status': 'active',
                'object_name': tc['title'],
                'ip_address': '-',
                'message': (
                    f'审批人：{approver_username}\n'
                    f'申请人：{requester_username}\n'
                    f'审批事项：{tc["title"]}\n'
                    f'目标设备：{device_hostname or "-"}\n'
                    f'申请原因：{config_reason}\n\n'
                    f'验证码：{code}\n验证码 5 分钟内有效，最多允许 3 次验证。'
                ),
                'first_occurrence': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
        )
        if not email_result.get('success'):
            _pending_approvals.pop(approval_token, None)
            error_code = str(email_result.get('error_code') or '')
            logger.warning(
                "[ConfigApproval] Email delivery failed for approver_id=%s error_code=%s",
                record['approver_id'], error_code or 'unknown',
            )
            if error_code == 'smtp_config_missing':
                return None, 'SMTP 邮件服务当前不可用，请联系管理员检查邮件配置'
            if error_code in {'smtp_invalid_recipient', 'smtp_recipient_rejected'}:
                return None, '审批人邮箱地址无效或被邮件服务器拒绝'
            return None, '审批邮件发送失败，请稍后重试或选择其他验证方式'
        logger.info("[ConfigApproval] Email code sent for approver_id=%s type=%s", record['approver_id'], record['approval_type'])
        return approval_token, None

    # Feishu remains available as a selectable legacy delivery method.
    channels = _parse_notification_channels(approver.get('notification_channels'))
    feishu_cfg = channels.get('feishu') or {}
    webhook_url = str(feishu_cfg.get('webhook_url') or '').strip()

    # 构建动态字段
    card_fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**申请人：**\n{requester_username}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**目标设备：**\n{device_hostname or '-'}"}},
    ]

    # 添加作业类型（定时作业/执行计划）
    if extra.get('action_type'):
        card_fields.append(
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**作业类型：**\n{extra['action_type']}"}}
        )

    # 添加调度信息
    if extra.get('schedule_desc'):
        card_fields.append(
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**执行计划：**\n{extra['schedule_desc']}"}}
        )

    # 变更原因
    card_fields.append(
        {"is_short": False, "text": {"tag": "lark_md", "content": f"**变更原因：**\n{config_reason}"}}
    )

    # 命令预览（仅在有内容时显示）
    if command_preview and command_preview.strip():
        cmd_preview_display = command_preview[:120] + ('...' if len(command_preview) > 120 else '')
        card_fields.append(
            {"is_short": False, "text": {"tag": "lark_md", "content": f"**命令预览：**\n```\n{cmd_preview_display}\n```"}}
        )

    card_payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": tc['title']},
                "template": tc['template'],
            },
            "elements": [
                {"tag": "div", "fields": card_fields},
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**验证码：`{code}`**\n\n请将此验证码告知申请人，验证码 5 分钟内有效。",
                    },
                },
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {sys_name} Config Approval"},
                    ],
                },
            ],
        },
    }

    ok, resp = notification_service._post_json(webhook_url, card_payload, timeout=15)
    if not ok:
        # 清理刚创建的记录
        _pending_approvals.pop(approval_token, None)
        logger.warning(f"[ConfigApproval] Feishu send failed: {resp}")
        # 对前端返回友好提示
        if 'timed out' in resp.lower() or 'timeout' in resp.lower():
            return None, "飞书服务连接超时，请检查网络后重试 / Feishu connection timed out, please retry"
        return None, f"Failed to send approval code via Feishu: {resp[:200]}"

    # 检查飞书返回 code
    try:
        body = json.loads(resp)
        code_val = body.get('code') if 'code' in body else body.get('StatusCode', 0)
        if code_val != 0:
            _pending_approvals.pop(approval_token, None)
            return None, f"Feishu API error code={code_val}"
    except Exception:
        pass

    logger.info(
        "[ConfigApproval] Feishu code sent for approver_id=%s requester_id=%s type=%s",
        record['approver_id'], record['requester_id'], record['approval_type'],
    )
    return approval_token, None


def verify_code(
    approval_token: str,
    code: str,
    *,
    requester_id: str | None = None,
    requester_username: str | None = None,
    expected_approval_type: str | None = None,
) -> tuple[bool, str]:
    """
    验证审批码。

    Returns:
        (success, error_message)
    """
    record = _pending_approvals.get(approval_token)
    if not record:
        return False, "Approval request not found or expired"

    expected_requester_id = str(record.get('requester_id') or '')
    if expected_requester_id and str(requester_id or '') != expected_requester_id:
        return False, '审批请求与当前登录账号不匹配'
    if not expected_requester_id and requester_username and str(record.get('requester') or '') != requester_username:
        return False, '审批请求与当前登录账号不匹配'
    if expected_approval_type and str(record.get('approval_type') or '') != expected_approval_type:
        return False, '审批令牌与当前操作类型不匹配'

    # 检查过期
    if time.time() - record['created_at'] > CODE_EXPIRY_SECONDS:
        _pending_approvals.pop(approval_token, None)
        return False, "Approval code has expired (5 min limit)"

    # 检查已验证
    if record['verified']:
        return True, ""

    # 检查尝试次数
    if record['attempts'] >= MAX_VERIFY_ATTEMPTS:
        _pending_approvals.pop(approval_token, None)
        return False, "Too many failed attempts, please request a new code"

    # Check the selected factor. MFA is verified against the approver account
    # currently stored in the database; email and Feishu use constant-time OTP
    # comparison against the short-lived pending request.
    record['attempts'] += 1
    method = str(record.get('verification_method') or 'feishu')
    if method == 'mfa':
        conn = get_db_connection()
        try:
            approver = conn.execute(
                "SELECT status, mfa_enabled, mfa_secret FROM users WHERE id = ?",
                (record.get('approver_id'),),
            ).fetchone()
            if not approver or approver['status'] != 'active' or not approver['mfa_enabled'] or not approver['mfa_secret']:
                _pending_approvals.pop(approval_token, None)
                return False, '审批人 MFA 已停用，请重新申请其他验证方式'
            from api.users import verify_totp
            valid = verify_totp(approver['mfa_secret'], code.strip(), window=1)
        finally:
            conn.close()
    else:
        valid = secrets.compare_digest(str(record.get('code') or ''), code.strip())

    if not valid:
        remaining = MAX_VERIFY_ATTEMPTS - record['attempts']
        if remaining <= 0:
            _pending_approvals.pop(approval_token, None)
            return False, "Too many failed attempts, please request a new code"
        return False, f"Invalid code, {remaining} attempt(s) remaining"

    # 验证通过
    record['verified'] = True
    record['verified_at'] = time.time()
    return True, ""


def consume_approval(
    approval_token: str,
    *,
    requester_id: str | None = None,
    expected_approval_type: str | None = None,
) -> dict | None:
    """
    消费一次已验证的审批令牌（一次性使用）。
    返回审批记录，或 None（如果令牌无效/未验证）。
    """
    record = _pending_approvals.get(approval_token)
    if not record:
        return None
    expected_requester_id = str(record.get('requester_id') or '')
    if expected_requester_id and str(requester_id or '') != expected_requester_id:
        return None
    if expected_approval_type and str(record.get('approval_type') or '') != expected_approval_type:
        return None
    if not record.get('verified'):
        return None
    if time.time() - record['created_at'] > CODE_EXPIRY_SECONDS:
        _pending_approvals.pop(approval_token, None)
        return None
    # 消费后移除
    return _pending_approvals.pop(approval_token, None)
