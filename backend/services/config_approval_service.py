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


def _get_approver_channels(approver_username: str) -> tuple[dict | None, str | None]:
    """查找审批人的通知渠道配置，返回 (channels_dict, error_msg)。"""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id, username, role, notification_channels FROM users WHERE username = ?',
            (approver_username,)
        ).fetchone()
        if not row:
            return None, f"Approver '{approver_username}' not found"
        channels_raw = row['notification_channels'] or '{}'
        try:
            channels = json.loads(channels_raw) if isinstance(channels_raw, str) else channels_raw
        except (json.JSONDecodeError, TypeError):
            channels = {}
        # 检查审批人是否有飞书通知渠道
        feishu = channels.get('feishu') or {}
        if not feishu.get('enabled') or not feishu.get('webhook_url', '').strip():
            return None, f"Approver '{approver_username}' has no Feishu webhook configured"
        return channels, None
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
) -> tuple[str | None, str | None]:
    """
    创建审批请求并发送验证码到审批人飞书。

    Args:
        approval_type: 审批类型 — 'config' (配置变更), 'scheduled_job' (定时作业), 'execution_plan' (执行计划)
        extra_fields: 额外展示字段，如 {'action_type': '配置备份', 'cron_expr': '0 2 * * *'}

    Returns:
        (approval_token, error_message) — 成功时 token 非空, error 为空; 反之亦然
    """
    _cleanup_expired()

    # 1. 查找审批人的飞书通知渠道
    channels, err = _get_approver_channels(approver_username)
    if err:
        return None, err

    # 2. 生成验证码 & 审批 token
    code = _generate_code()
    approval_token = secrets.token_urlsafe(32)

    # 3. 存储审批记录
    _pending_approvals[approval_token] = {
        'code': code,
        'approver': approver_username,
        'requester': requester_username,
        'config_reason': config_reason,
        'device_hostname': device_hostname,
        'command_preview': command_preview,
        'created_at': time.time(),
        'attempts': 0,
        'verified': False,
    }

    # 4. 构建飞书消息并发送
    feishu_cfg = channels.get('feishu', {})
    webhook_url = feishu_cfg['webhook_url']
    extra = extra_fields or {}

    # 根据审批类型选择标题和模板颜色
    sys_name = _get_system_name()
    type_config = {
        'config': {'title': f'🔐 {sys_name} 配置变更审批', 'template': 'orange'},
        'scheduled_job': {'title': f'⏰ {sys_name} 定时作业审批', 'template': 'blue'},
        'execution_plan': {'title': f'📋 {sys_name} 执行计划审批', 'template': 'turquoise'},
        'alert_rule': {'title': f'🛡️ {sys_name} 告警规则变更审批', 'template': 'red'},
        'alert_rule_delete': {'title': f'⚠️ {sys_name} 告警规则删除审批', 'template': 'rose'},
    }
    tc = type_config.get(approval_type, type_config['config'])

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

    logger.info(f"[ConfigApproval] Code sent to {approver_username} for request by {requester_username}")
    return approval_token, None


def verify_code(approval_token: str, code: str) -> tuple[bool, str]:
    """
    验证审批码。

    Returns:
        (success, error_message)
    """
    record = _pending_approvals.get(approval_token)
    if not record:
        return False, "Approval request not found or expired"

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

    # 校验验证码（常量时间比较防止时序攻击）
    record['attempts'] += 1
    if not secrets.compare_digest(record['code'], code.strip()):
        remaining = MAX_VERIFY_ATTEMPTS - record['attempts']
        if remaining <= 0:
            _pending_approvals.pop(approval_token, None)
            return False, "Too many failed attempts, please request a new code"
        return False, f"Invalid code, {remaining} attempt(s) remaining"

    # 验证通过
    record['verified'] = True
    return True, ""


def consume_approval(approval_token: str) -> dict | None:
    """
    消费一次已验证的审批令牌（一次性使用）。
    返回审批记录，或 None（如果令牌无效/未验证）。
    """
    record = _pending_approvals.get(approval_token)
    if not record:
        return None
    if not record.get('verified'):
        return None
    if time.time() - record['created_at'] > CODE_EXPIRY_SECONDS:
        _pending_approvals.pop(approval_token, None)
        return None
    # 消费后移除
    return _pending_approvals.pop(approval_token, None)
