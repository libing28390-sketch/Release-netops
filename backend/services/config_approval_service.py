"""
配置变更审批服务 — 验证码生成、存储、验证与飞书发送。

流程：
1. 操作员填写审批人用户名 + 变更原因
2. 后端生成 6 位数字验证码，通过审批人的飞书 webhook 发送
3. 操作员输入验证码，后端校验后放行配置操作
4. 验证码 5 分钟过期，3 次失败后自动作废
"""

import base64
import json
import hashlib
import hmac
import logging
import re
import secrets
import struct
import time
from datetime import datetime, timezone, timedelta
from database import get_db_connection
from services import notification_service
from core.config import settings
from core.rbac import authorize_resource, resource_action_allowed

logger = logging.getLogger(__name__)

# 配置常量
CODE_LENGTH = 6
CODE_EXPIRY_SECONDS = 300   # 5 分钟
MAX_VERIFY_ATTEMPTS = 3
MAX_MFA_APPROVER_FAILURES = 5
MFA_APPROVER_FAILURE_WINDOW_SECONDS = 300
MFA_APPROVER_LOCK_SECONDS = 900
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
    """Mark expired persistent approvals; callers may land on any worker."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            "UPDATE config_approval_requests SET status = 'expired' "
            "WHERE status IN ('pending', 'verified') AND expires_at <= ?",
            (now,),
        )
        conn.commit()
    finally:
        conn.close()


def _digest(value: str) -> str:
    key = str(getattr(settings, 'SECRET_KEY', '') or '').encode('utf-8')
    return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()


def approval_manifest_hash(manifest: object) -> str:
    """Hash a canonical, secret-free operation manifest for exact approval binding."""
    if not isinstance(manifest, dict) or not manifest:
        return ''
    canonical = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _approval_from_row(row) -> dict:
    record = dict(row)
    try:
        record['extra_fields'] = json.loads(record.pop('extra_fields_json') or '{}')
    except (TypeError, ValueError):
        record['extra_fields'] = {}
    record['approver'] = record.get('approver_username', '')
    record['requester'] = record.get('requester_username', '')
    record['verified'] = record.get('status') in {'verified', 'consumed'}
    return record


def _revoke_approval(approval_token: str) -> None:
    if not approval_token:
        return
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE config_approval_requests SET status = 'revoked' "
            "WHERE token_hash = ? AND status IN ('pending', 'verified')",
            (_digest(approval_token),),
        )
        conn.commit()
    finally:
        conn.close()


def _lock_clause() -> str:
    import database as database_module
    return ' FOR UPDATE' if database_module._USE_PG else ''


def _matching_totp_step(secret: str, code: str, now: datetime) -> int | None:
    """Return the matching TOTP step so one code cannot approve two requests."""
    try:
        normalized = str(secret or '').strip().replace(' ', '')
        normalized += '=' * ((8 - len(normalized) % 8) % 8)
        key = base64.b32decode(normalized, casefold=True)
        submitted = str(code or '').strip()
        if not re.fullmatch(r'\d{6}', submitted):
            return None
    except Exception:
        return None

    current_step = int(now.timestamp() // 30)
    for step in range(current_step - 1, current_step + 2):
        digest = hmac.new(key, struct.pack('>Q', step), hashlib.sha1).digest()
        offset = digest[-1] & 0x0f
        truncated = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
        candidate = f'{truncated % 1_000_000:06d}'
        if secrets.compare_digest(candidate, submitted):
            return step
    return None


def _mfa_approver_failure_state(conn, approver_id: str, now: datetime) -> int | None:
    """Lock and return the shared failure count; None means account is locked."""
    now_iso = now.replace(microsecond=0).isoformat()
    conn.execute(
        """INSERT INTO config_approval_mfa_limits
                   (approver_id, window_started_at, attempts, locked_until, updated_at)
             VALUES (?, ?, 0, '', ?)
             ON CONFLICT (approver_id) DO NOTHING""",
        (approver_id, now_iso, now_iso),
    )
    row = conn.execute(
        "SELECT window_started_at, attempts, locked_until FROM config_approval_mfa_limits "
        "WHERE approver_id = ?" + _lock_clause(),
        (approver_id,),
    ).fetchone()
    if not row:
        raise RuntimeError('MFA approval rate-limit row could not be locked')
    locked_until = _parse_approval_timestamp(row['locked_until'])
    if locked_until and now < locked_until:
        return None
    window_started = _parse_approval_timestamp(row['window_started_at'])
    if not window_started or (now - window_started).total_seconds() >= MFA_APPROVER_FAILURE_WINDOW_SECONDS:
        conn.execute(
            """UPDATE config_approval_mfa_limits
                  SET window_started_at = ?, attempts = 0, locked_until = '', updated_at = ?
                WHERE approver_id = ?""",
            (now_iso, now_iso, approver_id),
        )
        return 0
    return max(0, int(row['attempts'] or 0))


def _parse_approval_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _record_mfa_approver_failure(conn, approver_id: str, prior_attempts: int, now: datetime) -> None:
    attempts = prior_attempts + 1
    locked_until = ''
    if attempts >= MAX_MFA_APPROVER_FAILURES:
        locked_until = (now + timedelta(seconds=MFA_APPROVER_LOCK_SECONDS)).replace(microsecond=0).isoformat()
    now_iso = now.replace(microsecond=0).isoformat()
    conn.execute(
        """UPDATE config_approval_mfa_limits
              SET attempts = ?, locked_until = ?, updated_at = ?
            WHERE approver_id = ?""",
        (attempts, locked_until, now_iso, approver_id),
    )


def _consume_mfa_approver_step(conn, approver_id: str, time_step: int, now: datetime) -> bool:
    cursor = conn.execute(
        """INSERT INTO config_approval_mfa_steps (approver_id, time_step, used_at)
             VALUES (?, ?, ?) ON CONFLICT (approver_id, time_step) DO NOTHING""",
        (approver_id, time_step, now.replace(microsecond=0).isoformat()),
    )
    return getattr(cursor, 'rowcount', 1) != 0


def _safe_extra_fields(value: dict | None) -> dict:
    allowed = {'action_type', 'schedule_desc', 'operation', 'job_name'}
    source = value if isinstance(value, dict) else {}
    return {key: str(source[key])[:500] for key in allowed if key in source}


def _approval_manifest_display(operation_manifest: dict | None) -> str:
    """Render the actual bound operation for approvers, with secrets redacted."""
    if not isinstance(operation_manifest, dict) or not operation_manifest:
        return '{}'
    sensitive_key = re.compile(
        r'(?:password|passwd|secret|community|token|webhook|credential|private[_-]?key)',
        re.IGNORECASE,
    )
    try:
        from services.pam_audit_service import redact_command_input
    except Exception:
        redact_command_input = lambda value: str(value or '')

    def redact(value, key: str = ''):
        if sensitive_key.search(key):
            return '<REDACTED>'
        if isinstance(value, dict):
            return {str(child_key): redact(child, str(child_key)) for child_key, child in value.items()}
        if isinstance(value, list):
            return [redact(child, key) for child in value]
        if isinstance(value, str):
            return redact_command_input(value)
        return value

    serialized = json.dumps(
        redact(operation_manifest), ensure_ascii=False, sort_keys=True, indent=2, default=str,
    )
    # Keep untrusted values inside the card's code block.
    return serialized.replace('`', r'\u0060')


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
            SELECT id, username, role, role_profile, status, email, group_name,
                   tenant_id, scope_mode, mfa_enabled, mfa_secret, notification_channels
              FROM users
             WHERE COALESCE(NULLIF(tenant_id, ''), 'tenant-default') = ?
               AND status = 'active'
             ORDER BY username
            """,
            (_normalized_tenant_id(tenant_id),),
        ).fetchall()
        result = []
        for row in rows:
            approver = dict(row)
            if not resource_action_allowed(approver, 'pam', 'approve'):
                continue
            if not authorize_resource(approver, 'pam', 'approve', tenant_id=_normalized_tenant_id(tenant_id)):
                continue
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
            SELECT id, username, role, role_profile, status, email, group_name, tenant_id,
                   scope_mode, mfa_enabled, mfa_secret, notification_channels
              FROM users WHERE username = ?
            """,
            (approver_username,),
        ).fetchone()
        if not approver_row:
            return None, '所选审批人不存在'
        approver = dict(approver_row)
        if approver.get('status') != 'active' or not resource_action_allowed(approver, 'pam', 'approve'):
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

        if not requester_id or not str(requester.get('id') if requester else '').strip():
            return None, '审批申请必须绑定当前登录账号的稳定用户标识'

        if requester is not None:
            if requester.get('status') != 'active':
                return None, '当前操作账号已停用，无法发起审批'
            if str(requester.get('username') or '') != requester_username:
                return None, '审批申请人与当前登录账号不一致'
            requester_tenant_id = str(requester.get('tenant_id') or '')

        if str(approver.get('id') or '') == str(requester_id or ''):
            return None, '申请人不能审批自己的请求'
        if not str(requester_tenant_id or '').strip():
            return None, '审批申请人未分配租户，无法发起审批'

        expected_tenant = _normalized_tenant_id(requester_tenant_id)
        if _normalized_tenant_id(approver.get('tenant_id')) != expected_tenant:
            return None, '审批人与当前操作账号不属于同一租户'
        if not authorize_resource(approver, 'pam', 'approve', tenant_id=expected_tenant):
            return None, '所选审批人没有当前租户的审批授权'
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
    operation_manifest: dict | None = None,
) -> tuple[str | None, str | None]:
    """
    创建限时审批请求，可通过飞书、邮箱验证码或审批人 TOTP MFA 验证。

    Args:
        approval_type: 审批业务类型，消费时可要求与请求类型一致。
        extra_fields: 额外展示字段，如 {'action_type': '配置备份', 'schedule_desc': '每日 02:00'}
        verification_method: feishu、email 或 mfa。未传时兼容旧调用，默认飞书。
        operation_manifest: 服务端规范化的不可变操作输入；持久化时只保存其摘要。

    Returns:
        (approval_token, error_message) — 成功时 token 非空, error 为空; 反之亦然
    """
    _cleanup_expired()
    method = str(verification_method or 'feishu').strip().lower()
    if method not in APPROVAL_VERIFICATION_METHODS:
        return None, '不支持的审批验证方式'

    normalized_type = str(approval_type or 'config').strip() or 'config'
    binding_hash = approval_manifest_hash(operation_manifest)
    if normalized_type in {'config', 'scheduled_job', 'scheduled_job_delete', 'execution_plan'} and not binding_hash:
        return None, '审批申请缺少需要绑定的操作范围，请重新填写并申请'
    manifest_display = _approval_manifest_display(operation_manifest)
    if len(manifest_display) > 12000:
        return None, '审批操作清单过长，无法安全展示；请缩小本次设备或命令范围后重新申请'

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
    created_dt = datetime.now(timezone.utc).replace(microsecond=0)
    expires_dt = created_dt + timedelta(seconds=CODE_EXPIRY_SECONDS)
    created_at = created_dt.timestamp()

    record = {
        'code': code,
        'verification_method': method,
        'approval_type': normalized_type,
        'approver_id': str(approver.get('id') or ''),
        'approver': approver_username,
        'requester_id': str(requester_id or ''),
        'requester': requester_username,
        'requester_tenant_id': _normalized_tenant_id(requester_tenant_id or approver.get('tenant_id')),
        'config_reason': config_reason,
        # Client-supplied display fields can misrepresent the approved action.
        # Notifications below are rendered from the canonical bound manifest.
        'device_hostname': '',
        'command_preview': '',
        'extra_fields': {},
        'binding_hash': binding_hash,
        'created_at': created_at,
        'attempts': 0,
        'verified': False,
    }
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO config_approval_requests
               (token_hash, approval_type, requester_id, requester_username,
                requester_tenant_id, approver_id, approver_username,
                verification_method, code_hash, binding_hash, config_reason,
                device_hostname, command_preview, extra_fields_json, status,
                attempts, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'pending', 0, ?, ?)""",
            (
                _digest(approval_token), normalized_type, record['requester_id'],
                record['requester'], record['requester_tenant_id'], record['approver_id'],
                record['approver'], method, _digest(code) if code else '', binding_hash,
                str(config_reason or '')[:2000], '',
                json.dumps(record['extra_fields'], ensure_ascii=False, sort_keys=True),
                created_dt.isoformat(), expires_dt.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if method == 'mfa':
        logger.info(
            "[ConfigApproval] MFA approval requested for approver_id=%s requester_id=%s type=%s",
            record['approver_id'], record['requester_id'], record['approval_type'],
        )
        return approval_token, None

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
                    f'申请人说明（自由填写）：{str(config_reason or "-")[:2000]}\n'
                    f'服务端审批清单（敏感值已脱敏）：\n{manifest_display}\n'
                    f'清单 SHA-256：{binding_hash}\n\n'
                    f'验证码：{code}\n验证码 5 分钟内有效，最多允许 3 次验证。'
                ),
                'first_occurrence': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
        )
        if not email_result.get('success'):
            _revoke_approval(approval_token)
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

    card_fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**申请人：**\n{requester_username}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**清单 SHA-256：**\n`{binding_hash}`"}},
    ]
    card_fields.append(
        {"is_short": False, "text": {"tag": "lark_md", "content": f"**申请人说明（自由填写）：**\n{str(config_reason or '-')[:2000]}"}}
    )
    card_fields.append(
        {"is_short": False, "text": {"tag": "lark_md", "content": (
            '**服务端审批清单（敏感值已脱敏）：**\n```json\n'
            f'{manifest_display}\n```'
        )}}
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
        _revoke_approval(approval_token)
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
            _revoke_approval(approval_token)
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
    expected_binding_hash: str | None = None,
) -> tuple[bool, str]:
    """
    验证审批码。

    Returns:
        (success, error_message)
    """
    token_hash = _digest(str(approval_token or ''))
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM config_approval_requests WHERE token_hash = ?" + _lock_clause(),
            (token_hash,),
        ).fetchone()
        if not row:
            return False, "Approval request not found or expired"
        record = _approval_from_row(row)
        expected_requester_id = str(record.get('requester_id') or '')
        if not expected_requester_id or str(requester_id or '') != expected_requester_id:
            return False, '审批请求与当前登录账号不匹配'
        if requester_username and str(record.get('requester_username') or '') != requester_username:
            return False, '审批请求与当前登录账号不匹配'
        if expected_approval_type and str(record.get('approval_type') or '') != expected_approval_type:
            return False, '审批令牌与当前操作类型不匹配'
        if expected_binding_hash is not None and not secrets.compare_digest(
            str(record.get('binding_hash') or ''), str(expected_binding_hash or '')
        ):
            return False, '审批令牌与当前操作摘要不匹配'

        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            expires_at = datetime.fromisoformat(str(record.get('expires_at') or '').replace('Z', '+00:00'))
        except ValueError:
            expires_at = now - timedelta(seconds=1)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now >= expires_at or record.get('status') in {'expired', 'revoked', 'consumed'}:
            conn.execute(
                "UPDATE config_approval_requests SET status = 'expired' WHERE token_hash = ? AND status IN ('pending', 'verified')",
                (token_hash,),
            )
            conn.commit()
            return False, "Approval code has expired (5 min limit)"
        if record.get('status') == 'verified':
            return True, ""
        if record.get('status') != 'pending':
            return False, "Approval request is no longer active"
        if int(record.get('attempts') or 0) >= MAX_VERIFY_ATTEMPTS:
            conn.execute("UPDATE config_approval_requests SET status = 'expired' WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return False, "Too many failed attempts, please request a new code"

        approver_row = conn.execute(
            """SELECT id, role, role_profile, status, tenant_id, scope_mode,
                      mfa_enabled, mfa_secret
                 FROM users WHERE id = ?""",
            (record.get('approver_id'),),
        ).fetchone()
        approver = dict(approver_row) if approver_row else {}
        if (
            not approver
            or approver.get('status') != 'active'
            or not authorize_resource(
                approver, 'pam', 'approve',
                tenant_id=str(record.get('requester_tenant_id') or '') or None,
            )
        ):
            conn.execute("UPDATE config_approval_requests SET status = 'revoked' WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return False, '审批人当前已停用或已撤销审批授权，请重新申请'

        method = str(record.get('verification_method') or 'feishu')
        shared_mfa_attempts: int | None = None
        if method == 'mfa':
            if not approver.get('mfa_enabled') or not approver.get('mfa_secret'):
                conn.execute("UPDATE config_approval_requests SET status = 'revoked' WHERE token_hash = ?", (token_hash,))
                conn.commit()
                return False, '审批人 MFA 已停用，请重新申请其他验证方式'
            shared_mfa_attempts = _mfa_approver_failure_state(
                conn, str(record.get('approver_id') or ''), now,
            )
            if shared_mfa_attempts is None:
                conn.commit()
                return False, '审批人 MFA 验证尝试过多，请稍后再试'
            matching_step = _matching_totp_step(approver['mfa_secret'], code, now)
            valid = bool(
                matching_step is not None
                and _consume_mfa_approver_step(
                    conn, str(record.get('approver_id') or ''), matching_step, now,
                )
            )
        else:
            valid = secrets.compare_digest(
                str(record.get('code_hash') or ''), _digest(str(code or '').strip())
            )

        attempts = int(record.get('attempts') or 0) + 1
        if not valid:
            if method == 'mfa' and shared_mfa_attempts is not None:
                _record_mfa_approver_failure(
                    conn, str(record.get('approver_id') or ''), shared_mfa_attempts, now,
                )
            new_status = 'expired' if attempts >= MAX_VERIFY_ATTEMPTS else 'pending'
            conn.execute(
                "UPDATE config_approval_requests SET attempts = ?, status = ? WHERE token_hash = ?",
                (attempts, new_status, token_hash),
            )
            conn.commit()
            remaining = MAX_VERIFY_ATTEMPTS - attempts
            if remaining <= 0:
                return False, "Too many failed attempts, please request a new code"
            return False, f"Invalid code, {remaining} attempt(s) remaining"

        if method == 'mfa':
            approver_id = str(record.get('approver_id') or '')
            conn.execute(
                """UPDATE config_approval_mfa_limits
                      SET attempts = 0, locked_until = '', updated_at = ?
                    WHERE approver_id = ?""",
                (now.replace(microsecond=0).isoformat(), approver_id),
            )
            # Steps outside the current TOTP acceptance window cannot be
            # replayed and need not remain in the uniqueness table forever.
            conn.execute(
                'DELETE FROM config_approval_mfa_steps WHERE time_step < ?',
                (int(now.timestamp() // 30) - 5,),
            )

        verified_at = now.isoformat()
        conn.execute(
            "UPDATE config_approval_requests SET attempts = ?, status = 'verified', verified_at = ? WHERE token_hash = ? AND status = 'pending'",
            (attempts, verified_at, token_hash),
        )
        conn.commit()
        return True, ""
    finally:
        conn.close()


def consume_approval(
    approval_token: str,
    *,
    requester_id: str | None = None,
    expected_approval_type: str | None = None,
    expected_binding_hash: str | None = None,
) -> dict | None:
    """
    消费一次已验证的审批令牌（一次性使用）。
    返回审批记录，或 None（如果令牌无效/未验证）。
    """
    token_hash = _digest(str(approval_token or ''))
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM config_approval_requests WHERE token_hash = ?" + _lock_clause(),
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        record = _approval_from_row(row)
        if not requester_id or str(record.get('requester_id') or '') != str(requester_id):
            return None
        if expected_approval_type and str(record.get('approval_type') or '') != expected_approval_type:
            return None
        stored_binding = str(record.get('binding_hash') or '')
        if stored_binding and not expected_binding_hash:
            return None
        if expected_binding_hash is not None and not secrets.compare_digest(stored_binding, str(expected_binding_hash or '')):
            return None
        if record.get('status') != 'verified':
            return None
        if expected_approval_type and not str(record.get('binding_hash') or '').strip():
            return None

        # Revalidate both parties at the last irreversible boundary.  A code
        # that was verified before an account was disabled, moved to another
        # tenant, or stripped of approval rights must not remain executable.
        requester_row = conn.execute(
            "SELECT id, username, status, tenant_id FROM users WHERE id = ?",
            (str(record.get('requester_id') or ''),),
        ).fetchone()
        approver_row = conn.execute(
            "SELECT id, username, role, role_profile, status, tenant_id, scope_mode "
            "FROM users WHERE id = ?",
            (str(record.get('approver_id') or ''),),
        ).fetchone()
        requester = dict(requester_row) if requester_row else {}
        approver = dict(approver_row) if approver_row else {}
        bound_tenant = _normalized_tenant_id(record.get('requester_tenant_id'))
        if (
            not requester
            or requester.get('status') != 'active'
            or str(requester.get('username') or '') != str(record.get('requester_username') or '')
            or _normalized_tenant_id(requester.get('tenant_id')) != bound_tenant
        ):
            conn.execute("UPDATE config_approval_requests SET status = 'revoked' WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return None
        if (
            not approver
            or approver.get('status') != 'active'
            or str(approver.get('id') or '') == str(record.get('requester_id') or '')
            or _normalized_tenant_id(approver.get('tenant_id')) != bound_tenant
            or not authorize_resource(approver, 'pam', 'approve', tenant_id=bound_tenant)
        ):
            conn.execute("UPDATE config_approval_requests SET status = 'revoked' WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return None

        now = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            expires_at = datetime.fromisoformat(str(record.get('expires_at') or '').replace('Z', '+00:00'))
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now >= expires_at:
            conn.execute("UPDATE config_approval_requests SET status = 'expired' WHERE token_hash = ?", (token_hash,))
            conn.commit()
            return None
        consumed_at = now.isoformat()
        result = _approval_from_row(row)
        result['status'] = 'consumed'
        result['verified_at'] = record.get('verified_at')
        result['consumed_at'] = consumed_at
        update_cursor = conn.execute(
            """UPDATE config_approval_requests SET status = 'consumed', consumed_at = ?
                 WHERE token_hash = ? AND status = 'verified' AND expires_at > ?""",
            (consumed_at, token_hash, now.isoformat()),
        )
        if getattr(update_cursor, 'rowcount', 1) == 0:
            conn.rollback()
            return None
        conn.commit()
        return result
    finally:
        conn.close()
