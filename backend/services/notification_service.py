"""
多平台通知服务 — 飞书 / 钉钉 / 企业微信

消息格式：
  - 飞书：Interactive Card（彩色标题栏 + Markdown 正文）
  - 钉钉：Markdown 卡片（critical 级别自动 @all）
  - 企业微信：Markdown 消息

告警级别颜色映射：
  critical → 红色  major → 橙色  warning → 黄色  info/low → 青色/绿色
"""

import json
import os
import time
import hmac
import base64
import hashlib
import logging
import re
import smtplib
import socket
import ssl
import threading
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from urllib import request as urlrequest, error as urlerror
from urllib.parse import quote

from core.crypto import decrypt_credential
from database import get_db_connection

logger = logging.getLogger(__name__)

_AUTOMATIC_NOTIFICATIONS_ENV = "NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_email_rate_lock = threading.Lock()
_email_rate_history: dict[str, list[float]] = {}


def automatic_notifications_enabled() -> bool:
    """Return whether background/tenant notification dispatch is allowed.

    Production keeps the historical default (enabled when the variable is not
    set). The development launcher sets this variable to ``0`` so starting a
    local service cannot replay existing alert state into real webhooks. An
    operator can explicitly opt in by setting it to a true value. Explicit
    user-triggered webhook test functions call ``send_*`` directly and are not
    silently disabled by this automatic-dispatch guard.
    """

    configured = os.environ.get(_AUTOMATIC_NOTIFICATIONS_ENV)
    if configured is None:
        return True
    return configured.strip().lower() in _TRUE_VALUES

# ── 级别映射 ──────────────────────────────────────────────
_SEVERITY_EMOJI = {
    'critical': '🔴',
    'major':    '🟠',
    'warning':  '🟡',
    'info':     '🔵',
    'low':      '🟢',
}
_FEISHU_HEADER_COLOR = {
    'critical': 'red',
    'major':    'orange',
    'warning':  'yellow',
    'info':     'turquoise',
    'low':      'green',
}
_WECHAT_FONT_COLOR = {
    'critical': 'warning',   # WeCom: warning = 橙黄色
    'major':    'warning',
    'warning':  'warning',
    'info':     'info',
    'low':      'comment',
}
_SEVERITY_LABEL_ZH = {
    'critical': '严重',
    'major':    '主要',
    'warning':  '次要',
    'minor':    '次要',
    'info':     '提示',
    'low':      '次要',
}
_SEVERITY_LABEL_EN = {
    'critical': 'Critical',
    'major':    'Major',
    'warning':  'Minor',
    'minor':    'Minor',
    'info':     'Info',
    'low':      'Minor',
}


def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _status_label(status: str, lang: str = 'zh') -> str:
    if lang == 'en':
        return {'active': '🔥 Active', 'resolved': '✅ Closed/Recovered', 'acknowledged': '👁 Acknowledged'}.get(
            (status or '').lower(), status or 'Active'
        )
    return {'active': '🔥 告警中', 'resolved': '✅ 已关闭/恢复', 'acknowledged': '👁 已确认'}.get(
        (status or '').lower(), status or '告警中'
    )


def _fmt_duration(seconds: int, is_en: bool) -> str:
    """将秒数格式化为可读字符串，如 '4 分 5 秒' / '4m 5s'。"""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s" if is_en else f"{hours} 时 {minutes} 分 {secs} 秒"
    if minutes:
        return f"{minutes}m {secs}s" if is_en else f"{minutes} 分 {secs} 秒"
    return f"{secs}s" if is_en else f"{secs} 秒"


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


def _post_json(url: str, payload: dict, timeout: int = 5) -> tuple[bool, str]:
    """发送 JSON POST，返回 (success, response_body)。"""
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        url, data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            if resp.status >= 400:
                return False, f"HTTP {resp.status}: {body[:300]}"
            return True, body
    except urlerror.URLError as exc:
        return False, str(exc)


_EMAIL_ADDRESS_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _email_recipients(values) -> list[str]:
    """Return validated, de-duplicated recipients without leaking addresses."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    for value in values:
        address = str(value or '').strip().lower()
        if address and _EMAIL_ADDRESS_RE.fullmatch(address) and address not in result:
            result.append(address)
    return result


def _email_subject(alert: dict, *, test_mode: bool = False) -> str:
    severity = str(alert.get('severity') or 'info').upper()
    title = str(alert.get('title') or 'Nexora Alert').strip()
    if test_mode:
        return f"[SMTP TEST] {title}"[:240]
    object_name = str(alert.get('object_name') or alert.get('ip_address') or '').strip()
    return f"[{severity}] {title}{f' - {object_name}' if object_name else ''}"[:240]


def _email_body(alert: dict, *, html: bool = False, test_mode: bool = False) -> str:
    status = _status_label(str(alert.get('status') or 'active'), 'zh')
    title = str(alert.get('title') or '告警通知')
    object_name = str(alert.get('object_name') or '-')
    ip_address = str(alert.get('ip_address') or '-')
    severity = str(alert.get('severity') or 'info')
    message = str(alert.get('message') or '-')
    first = str(alert.get('first_occurrence') or _now_str())
    last = str(alert.get('last_occurrence') or first)
    duration = alert.get('duration_seconds')
    platform_url = str(alert.get('platform_url') or '').strip()

    def escape(value: str) -> str:
        return (
            value.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    if test_mode:
        result = 'SMTP 服务器已接受本次测试邮件发送请求。'
        note = '这是一封 SMTP 配置测试邮件，不是告警通知，也不会创建告警事件。'
        if not html:
            return '\n'.join((
                title,
                f'测试结果：{result}',
                f'说明：{note}',
                f'发起信息：{message}',
                f'测试时间：{first}',
            ))
        return (
            '<html><body style="margin:0;padding:24px;background:#f1f5f9;'
            'font-family:Arial,sans-serif;color:#1e293b">'
            '<div style="max-width:640px;margin:0 auto;padding:28px;background:#fff;'
            'border:1px solid #e2e8f0;border-radius:16px">'
            '<div style="display:inline-block;padding:5px 10px;border-radius:999px;'
            'background:#ecfeff;color:#0e7490;font-size:12px;font-weight:700">SMTP TEST</div>'
            f'<h2 style="margin:18px 0 10px">{escape(title)}</h2>'
            f'<p style="margin:0 0 12px">{escape(result)}</p>'
            f'<p style="margin:0;padding:12px 14px;border-radius:10px;'
            f'background:#f0f9ff;color:#075985;line-height:1.6">{escape(note)}</p>'
            f'<p style="margin:18px 0 4px;color:#475569">{escape(message)}</p>'
            f'<p style="margin:4px 0 0;color:#64748b;font-size:12px">测试时间：{escape(first)}</p>'
            '</div></body></html>'
        )

    if not html:
        lines = [
            title,
            f"级别：{severity}",
            f"状态：{status}",
            f"对象：{object_name}",
            f"IP：{ip_address}",
            f"描述：{message}",
            f"首次发生：{first}",
            f"最近发生：{last}",
        ]
        if duration is not None:
            lines.append(f"持续时间：{_fmt_duration(duration, False)}")
        if platform_url:
            lines.append(f"处理链接：{platform_url}")
        return "\n".join(lines)

    rows = [
        ('告警名称', title),
        ('级别', severity),
        ('状态', status),
        ('对象', object_name),
        ('IP', ip_address),
        ('描述', message),
        ('首次发生', first),
        ('最近发生', last),
    ]
    if duration is not None:
        rows.append(('持续时间', _fmt_duration(duration, False)))
    table = ''.join(
        f'<tr><th style="text-align:left;padding:6px 10px">{escape(label)}</th>'
        f'<td style="padding:6px 10px">{escape(value)}</td></tr>'
        for label, value in rows
    )
    link = f'<p><a href="{escape(platform_url)}">前往告警台处理</a></p>' if platform_url else ''
    return f'<html><body><h2>{escape(title)}</h2><table>{table}</table>{link}</body></html>'


def send_email(smtp_config: dict, recipients, alert: dict, *, test_mode: bool = False) -> dict:
    """Send an alert or explicit configuration-test email with a safe result."""
    addresses = _email_recipients(recipients)
    if not addresses:
        return {'success': False, 'error_code': 'smtp_invalid_recipient', 'recipient_count': 0}

    config = dict(smtp_config or {})
    if not bool(config.get('enabled')) and not test_mode:
        return {'success': False, 'error_code': 'smtp_config_missing', 'recipient_count': len(addresses)}
    host = str(config.get('host') or '').strip()
    from_address = str(config.get('from_address') or '').strip()
    if not host or not _EMAIL_ADDRESS_RE.fullmatch(from_address):
        return {'success': False, 'error_code': 'smtp_config_missing', 'recipient_count': len(addresses)}
    security = str(config.get('security') or 'starttls').strip().lower()
    try:
        rate_limit = max(1, min(10000, int(config.get('rate_limit_per_minute') or 60)))
    except (TypeError, ValueError):
        rate_limit = 60
    rate_key = str(config.get('id') or f"{host}:{from_address}")
    now = time.time()
    with _email_rate_lock:
        recent = [timestamp for timestamp in _email_rate_history.get(rate_key, []) if now - timestamp < 60]
        if len(recent) >= rate_limit:
            _email_rate_history[rate_key] = recent
            return {'success': False, 'error_code': 'smtp_rate_limited', 'recipient_count': len(addresses)}
        recent.append(now)
        _email_rate_history[rate_key] = recent
    try:
        port = int(config.get('port') or (465 if security == 'ssl' else 587))
        connect_timeout = max(1, min(120, int(config.get('connect_timeout_seconds') or 10)))
        send_timeout = max(1, min(120, int(config.get('send_timeout_seconds') or 20)))
    except (TypeError, ValueError):
        return {'success': False, 'error_code': 'smtp_config_missing', 'recipient_count': len(addresses)}

    password = str(config.get('password') or '')
    if not password and config.get('password_ciphertext'):
        password = str(decrypt_credential(config.get('password_ciphertext')) or '')
    username = str(config.get('username') or '').strip()
    message = EmailMessage()
    message['Subject'] = _email_subject(alert, test_mode=test_mode)
    message['From'] = formataddr((str(config.get('from_name') or 'Nexora').strip(), from_address))
    message['To'] = ', '.join(addresses)
    reply_to = str(config.get('reply_to') or '').strip()
    if reply_to and _EMAIL_ADDRESS_RE.fullmatch(reply_to):
        message['Reply-To'] = reply_to
    message.set_content(_email_body(alert, html=False, test_mode=test_mode))
    message.add_alternative(_email_body(alert, html=True, test_mode=test_mode), subtype='html')

    smtp = None
    try:
        if security == 'ssl':
            smtp = smtplib.SMTP_SSL(host, port, timeout=connect_timeout, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(host, port, timeout=connect_timeout)
            smtp.ehlo()
            if security == 'starttls':
                smtp.starttls(context=ssl.create_default_context())
                code, response = smtp.ehlo()
                if code >= 400:
                    raise smtplib.SMTPHeloError(code, response)
        if username:
            smtp.login(username, password)
        if smtp.sock is not None:
            smtp.sock.settimeout(send_timeout)
        smtp.send_message(message)
        return {'success': True, 'error_code': '', 'recipient_count': len(addresses)}
    except smtplib.SMTPAuthenticationError:
        return {'success': False, 'error_code': 'smtp_auth_failed', 'recipient_count': len(addresses)}
    except smtplib.SMTPRecipientsRefused:
        return {'success': False, 'error_code': 'smtp_recipient_rejected', 'recipient_count': len(addresses)}
    except (ssl.SSLError, smtplib.SMTPNotSupportedError):
        return {'success': False, 'error_code': 'smtp_tls_failed', 'recipient_count': len(addresses)}
    except (socket.timeout, TimeoutError):
        return {'success': False, 'error_code': 'smtp_timeout', 'recipient_count': len(addresses)}
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError):
        return {'success': False, 'error_code': 'smtp_dns_or_connect_failed', 'recipient_count': len(addresses)}
    except smtplib.SMTPException:
        return {'success': False, 'error_code': 'smtp_provider_error', 'recipient_count': len(addresses)}
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass


def test_smtp_connection(smtp_config: dict) -> dict:
    """Check SMTP reachability, TLS mode, and configured credentials without sending mail."""
    config = dict(smtp_config or {})
    host = str(config.get('host') or '').strip()
    security = str(config.get('security') or 'starttls').strip().lower()
    if not host or security not in {'ssl', 'starttls', 'none'}:
        return {'success': False, 'error_code': 'smtp_config_missing', 'connected': False, 'authenticated': False}

    try:
        port = int(config.get('port') or (465 if security == 'ssl' else 587))
        timeout = max(1, min(120, int(config.get('connect_timeout_seconds') or 10)))
    except (TypeError, ValueError):
        return {'success': False, 'error_code': 'smtp_config_missing', 'connected': False, 'authenticated': False}
    if not 1 <= port <= 65535:
        return {'success': False, 'error_code': 'smtp_config_missing', 'connected': False, 'authenticated': False}

    password = str(config.get('password') or '')
    if not password and config.get('password_ciphertext'):
        password = str(decrypt_credential(config.get('password_ciphertext')) or '')
    username = str(config.get('username') or '').strip()
    smtp = None
    try:
        if security == 'ssl':
            smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
            code, response = smtp.ehlo()
            if code >= 400:
                raise smtplib.SMTPHeloError(code, response)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
            code, response = smtp.ehlo()
            if code >= 400:
                raise smtplib.SMTPHeloError(code, response)
            if security == 'starttls':
                smtp.starttls(context=ssl.create_default_context())
                code, response = smtp.ehlo()
                if code >= 400:
                    raise smtplib.SMTPHeloError(code, response)
        if username:
            smtp.login(username, password)
        return {
            'success': True,
            'error_code': '',
            'connected': True,
            'authenticated': bool(username),
        }
    except smtplib.SMTPAuthenticationError:
        return {'success': False, 'error_code': 'smtp_auth_failed', 'connected': True, 'authenticated': False}
    except (ssl.SSLError, smtplib.SMTPNotSupportedError):
        return {'success': False, 'error_code': 'smtp_tls_failed', 'connected': False, 'authenticated': False}
    except (socket.timeout, TimeoutError):
        return {'success': False, 'error_code': 'smtp_timeout', 'connected': False, 'authenticated': False}
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError):
        return {'success': False, 'error_code': 'smtp_dns_or_connect_failed', 'connected': False, 'authenticated': False}
    except smtplib.SMTPException:
        return {'success': False, 'error_code': 'smtp_provider_error', 'connected': False, 'authenticated': False}
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass


def _profile_targets(row: dict) -> list[dict]:
    raw = row.get('recipient_targets_json')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '[]')
        except (TypeError, ValueError):
            raw = []
    if not isinstance(raw, list):
        return []
    targets = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('kind') or '').strip().lower()
        value_key = 'group_name' if kind == 'group' else 'user_id' if kind == 'user' else ''
        value = str(item.get(value_key) or '').strip()
        key = (kind, value)
        if value and value_key and key not in seen:
            targets.append({'kind': kind, value_key: value})
            seen.add(key)
    return targets


def _is_hidden_primary_override(row: dict) -> bool:
    return (
        str(row.get('tenant_id') or '') != 'tenant-default'
        and str(row.get('name') or '').strip().lower() == 'primary'
        and not bool(row.get('enabled'))
        and not str(row.get('host') or '').strip()
        and not str(row.get('from_address') or '').strip()
        and not str(row.get('password_ciphertext') or '').strip()
        and not _profile_targets(row)
    )


def get_email_profiles_for_dispatch(
    connection,
    tenant_id: str,
    *,
    profile_id: str | None = None,
    legacy_primary: bool = False,
    enabled_only: bool = False,
) -> list[dict]:
    """Return tenant SMTP profiles with tenant-default fallback semantics.

    A local row, including an intentionally empty primary override, blocks
    shared profiles. The workspace path asks specifically for the local (or
    shared-only) legacy primary profile so it never selects another profile by
    update time.
    """
    normalized_tenant = str(tenant_id or 'tenant-default').strip() or 'tenant-default'
    local_rows = [
        dict(row) for row in connection.execute(
            "SELECT * FROM notification_smtp_configs WHERE tenant_id = ? ORDER BY updated_at DESC, id",
            (normalized_tenant,),
        ).fetchall()
    ]
    shared_rows = [
        dict(row) for row in connection.execute(
            "SELECT * FROM notification_smtp_configs WHERE tenant_id = 'tenant-default' ORDER BY updated_at DESC, id",
        ).fetchall()
    ] if normalized_tenant != 'tenant-default' else []

    if profile_id:
        wanted = str(profile_id).strip()
        rows = [row for row in local_rows if str(row.get('id') or '') == wanted]
        if not rows and not local_rows:
            rows = [row for row in shared_rows if str(row.get('id') or '') == wanted]
    elif legacy_primary:
        rows = [row for row in local_rows if str(row.get('name') or '').strip().lower() == 'primary']
        if not rows and not local_rows:
            rows = [row for row in shared_rows if str(row.get('name') or '').strip().lower() == 'primary']
    else:
        rows = local_rows if local_rows else shared_rows

    if enabled_only:
        rows = [row for row in rows if bool(row.get('enabled'))]
    return rows


def _profile_email_recipients(profile: dict, user_rows: list[dict]) -> list[str]:
    targets = _profile_targets(profile)
    if not targets:
        return []
    group_names = {item['group_name'] for item in targets if item['kind'] == 'group'}
    user_ids = {item['user_id'] for item in targets if item['kind'] == 'user'}
    recipients = []
    for user in user_rows:
        user_id = str(user.get('id') or '').strip()
        group_name = str(user.get('group_name') or '').strip()
        if user_id not in user_ids and group_name not in group_names:
            continue
        address = str(user.get('email') or '').strip().lower()
        if address and _EMAIL_ADDRESS_RE.fullmatch(address) and address not in recipients:
            recipients.append(address)
    return recipients


# ── 飞书 Interactive Card ─────────────────────


def _feishu_card(alert: dict) -> dict:
    """
    alert keys: title, object_name, ip_address, status, severity,
                message, first_occurrence, last_occurrence, lang
    """
    lang      = (alert.get('lang') or 'zh').lower()
    is_en     = lang == 'en'
    severity  = (alert.get('severity') or 'info').lower()
    title     = alert.get('title', 'Alert Notification' if is_en else '告警通知')
    obj       = alert.get('object_name', '-')
    ip        = alert.get('ip_address', '-')
    status_raw = (alert.get('status') or 'active').lower()
    status    = _status_label(status_raw, lang)
    msg       = alert.get('message', '-')
    first_ts  = alert.get('first_occurrence', _now_str())
    last_ts   = alert.get('last_occurrence', first_ts)

    # 恢复告警附加字段
    dur_secs  = alert.get('duration_seconds')
    imp_win   = alert.get('impact_window')
    alert_cnt = alert.get('alert_count')
    dur_str   = _fmt_duration(dur_secs, is_en) if dur_secs is not None else None

    if status_raw == 'resolved':
        emoji = '🟢'
        color = 'green'
        sev_label = 'Clear' if is_en else '恢复/正常'
        title_text = "NetOps Network Alert Recovery" if is_en else "NetOps 网络告警恢复通知"
    else:
        emoji = _SEVERITY_EMOJI.get(severity, '⚪')
        color = _FEISHU_HEADER_COLOR.get(severity, 'blue')
        sev_label = (_SEVERITY_LABEL_EN if is_en else _SEVERITY_LABEL_ZH).get(severity, severity.upper())
        title_text = f"NetOps Network Alert" if is_en else f"NetOps 网络告警通知"

    if is_en:
        fields = [
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**Alert Name:**\n{title}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**Severity:**\n{emoji} {sev_label}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**Object:**\n{obj}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**IP:**\n{ip}"}},
            {"is_short": False, "text": {"tag": "lark_md", "content": f"**Status:**\n{status}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**First Occurrence:**\n{first_ts}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**Last Occurrence:**\n{last_ts}"}},
        ]
        if imp_win:
            fields.append({"is_short": False, "text": {"tag": "lark_md", "content": f"**Impact Window:**\n{imp_win}"}})
        if dur_str:
            fields.append({"is_short": True,  "text": {"tag": "lark_md", "content": f"**Duration:**\n{dur_str}"}})
        if alert_cnt is not None:
            fields.append({"is_short": True,  "text": {"tag": "lark_md", "content": f"**Alert Count:**\n{alert_cnt}"}})
        fields.append({"is_short": False, "text": {"tag": "lark_md", "content": f"**Description:**\n{msg}"}})
    else:
        fields = [
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**告警名称：**\n{title}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**告警级别：**\n{emoji} {sev_label}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**告警对象：**\n{obj}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**告警 IP：**\n{ip}"}},
            {"is_short": False, "text": {"tag": "lark_md", "content": f"**处理状态：**\n{status}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**首次发生时间：**\n{first_ts}"}},
            {"is_short": True,  "text": {"tag": "lark_md", "content": f"**最后发生时间：**\n{last_ts}"}},
        ]
        if imp_win:
            fields.append({"is_short": False, "text": {"tag": "lark_md", "content": f"**影响时间窗：**\n{imp_win}"}})
        if dur_str:
            fields.append({"is_short": True,  "text": {"tag": "lark_md", "content": f"**持续时长：**\n{dur_str}"}})
        if alert_cnt is not None:
            fields.append({"is_short": True,  "text": {"tag": "lark_md", "content": f"**告警次数：**\n{alert_cnt}"}})
        fields.append({"is_short": False, "text": {"tag": "lark_md", "content": f"**告警描述：**\n{msg}"}})

    elements: list = [
        {"tag": "div", "fields": fields},
        {"tag": "hr"},
    ]

    # 如果配置了平台 URL，追加操作按钮
    try:
        from core.config import settings as _settings
        platform_url = (_settings.PLATFORM_URL or '').strip()
    except Exception:
        platform_url = os.environ.get('PLATFORM_URL', '').strip()

    sys_name = _get_system_name()
    if platform_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"Open {sys_name} Platform" if is_en else f"前往 {sys_name} 平台处理"},
                "type": "primary",
                "url": platform_url,
            }],
        })
    else:
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"{sys_name} NOC Auto Alert" if is_en else f"{sys_name} NOC 自动告警"}],
        })

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} {title_text}"},
                "template": color,
            },
            "elements": elements,
        },
    }


def send_feishu(webhook_url: str, alert: dict) -> tuple[bool, str]:
    """飞书自定义机器人 Webhook（Interactive Card 彩色卡片）。"""
    payload = _feishu_card(alert)
    ok, resp = _post_json(webhook_url, payload)
    if ok:
        try:
            body = json.loads(resp)
            code = body.get('code') if 'code' in body else body.get('StatusCode', 0)
            if code != 0:
                return False, f"Feishu error code={code} msg={body.get('msg', resp[:200])}"
        except Exception:
            pass
    return ok, resp


def send_feishu_verification_code(webhook_url: str, username: str, code: str, expires_min: int = 5, lang: str = 'zh') -> tuple[bool, str]:
    """通过飞书 Webhook 发送密码重置验证码卡片。"""
    is_en = lang == 'en'
    title = "🔐 " + ("Password Reset Code" if is_en else "密码重置验证码")
    fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**User:**\n{username}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**Code:**\n**{code}**"}},
    ]
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "div", "fields": fields}],
        },
    }
    return _post_json(webhook_url, payload)

def send_feishu_mfa_access_code(webhook_url: str, username: str, code: str, expires_min: int = 5, lang: str = 'zh', approver_name: str = "Admin", index: str = "00") -> tuple[bool, str]:
    """发送资产特权访问授权验证码。"""
    is_en = lang == 'en'
    title = "🛡️ " + ("Privileged Access Authorization" if is_en else "资产特权访问授权")
    
    user_label = "Requester" if is_en else "申请用户"
    approver_label = "Approver" if is_en else "审批人"
    code_label = "Auth Code" if is_en else "授权验证码"
    index_label = "Code Index" if is_en else "验证码索引"
    footer_text = (f"Expires in **{expires_min} min**. Audit active." if is_en else f"验证码 **{expires_min} 分钟**内有效。本次访问将被全程审计。")
    
    fields = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{user_label}:**\n{username}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{approver_label}:**\n{approver_name}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{index_label}:**\n<font color='blue'>**#{index}**</font>"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{code_label}:**\n<font color='red'>**{code}**</font>"}},
        {"is_short": False, "text": {"tag": "lark_md", "content": f"⏱ {footer_text}"}},
    ]
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "orange"},
            "elements": [
                {"tag": "div", "fields": fields},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "NetOps Security Gateway"}]}
            ],
        },
    }
    return _post_json(webhook_url, payload)


def send_dingtalk_verification_code(webhook_url: str, username: str, code: str, expires_min: int = 5, lang: str = 'zh', secret: str = '') -> tuple[bool, str]:
    """通过钉钉 Webhook 发送密码重置验证码。"""
    is_en = lang == 'en'
    if is_en:
        md_text = f"## 🔐 Password Reset Code\n\n**User:** {username}\n\n**Code:** `{code}`\n\n⏱ Expires in {expires_min} minutes."
        title = "Password Reset Code"
    else:
        md_text = f"## 🔐 密码重置验证码\n\n**用户：** {username}\n\n**验证码：** `{code}`\n\n⏱ {expires_min} 分钟内有效，请勿泄露。"
        title = "密码重置验证码"
    url = webhook_url
    if secret and secret.strip():
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        hmac_code = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode()
        url = f"{webhook_url}&timestamp={ts}&sign={quote(sign)}"
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": md_text}}
    return _post_json(url, payload)


def send_wechat_verification_code(webhook_url: str, username: str, code: str, expires_min: int = 5, lang: str = 'zh') -> tuple[bool, str]:
    """通过企业微信 Webhook 发送密码重置验证码。"""
    is_en = lang == 'en'
    if is_en:
        content = f"## 🔐 Password Reset Code\n\n> **User:** {username}\n> **Code:** `{code}`\n> ⏱ Expires in {expires_min} minutes."
    else:
        content = f"## 🔐 密码重置验证码\n\n> **用户：** {username}\n> **验证码：** `{code}`\n> ⏱ {expires_min} 分钟内有效，请勿泄露。"
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    return _post_json(webhook_url, payload)


# ── 钉钉 Markdown 卡片 ─────────────────────────


def _dingtalk_markdown(alert: dict) -> dict:
    lang      = (alert.get('lang') or 'zh').lower()
    is_en     = lang == 'en'
    severity  = (alert.get('severity') or 'info').lower()
    title     = alert.get('title', 'Alert' if is_en else '告警通知')
    obj       = alert.get('object_name', '-')
    ip        = alert.get('ip_address', '-')
    status_raw = (alert.get('status') or 'active').lower()
    status    = _status_label(status_raw, lang)
    msg       = alert.get('message', '-')
    first_ts  = alert.get('first_occurrence', _now_str())
    last_ts   = alert.get('last_occurrence', first_ts)

    # 恢复告警附加字段
    dur_secs  = alert.get('duration_seconds')
    imp_win   = alert.get('impact_window')
    alert_cnt = alert.get('alert_count')
    dur_str   = _fmt_duration(dur_secs, is_en) if dur_secs is not None else None

    if status_raw == 'resolved':
        emoji = '🟢'
        sev_label = 'Clear' if is_en else '恢复/正常'
        title_text = "Alert Recovery Notification" if is_en else "网络告警恢复通知"
    else:
        emoji = _SEVERITY_EMOJI.get(severity, '⚪')
        sev_label = (_SEVERITY_LABEL_EN if is_en else _SEVERITY_LABEL_ZH).get(severity, severity.upper())
        title_text = title

    if is_en:
        extra_rows = ""
        if imp_win:
            extra_rows += f"| Impact Window | {imp_win} |\n"
        if dur_str:
            extra_rows += f"| Duration | {dur_str} |\n"
        if alert_cnt is not None:
            extra_rows += f"| Alert Count | {alert_cnt} |\n"
        sys_name = _get_system_name()
        md_text = (
            f"## {emoji} [{sev_label}] {title_text}\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| Alert Name | {title} |\n"
            f"| Object | {obj} |\n"
            f"| IP | {ip} |\n"
            f"| Status | {status} |\n"
            f"| Severity | {emoji} {sev_label} |\n"
            f"| Description | {msg} |\n"
            f"| First Occurrence | {first_ts} |\n"
            f"| Last Occurrence | {last_ts} |\n"
            f"{extra_rows}"
            f"\n---\n*{sys_name} NOC Auto Alert*"
        )
    else:
        extra_rows = ""
        if imp_win:
            extra_rows += f"| 影响时间窗 | {imp_win} |\n"
        if dur_str:
            extra_rows += f"| 持续时长 | {dur_str} |\n"
        if alert_cnt is not None:
            extra_rows += f"| 告警次数 | {alert_cnt} |\n"
        sys_name = _get_system_name()
        md_text = (
            f"## {emoji} [{sev_label}] {title_text}\n\n"
            f"| 字段 | 内容 |\n"
            f"|------|------|\n"
            f"| 告警名称 | {title} |\n"
            f"| 告警对象 | {obj} |\n"
            f"| 告警 IP | {ip} |\n"
            f"| 处理状态 | {status} |\n"
            f"| 告警级别 | {emoji} {sev_label} |\n"
            f"| 告警描述 | {msg} |\n"
            f"| 首次发生 | {first_ts} |\n"
            f"| 最后发生 | {last_ts} |\n"
            f"{extra_rows}"
            f"\n---\n*{sys_name} NOC 自动告警*"
        )
    return {
        "msgtype": "markdown",
        "markdown": {"title": f"{emoji} [{sev_label}] {title_text}", "text": md_text},
        "at": {"isAtAll": severity == 'critical'},
    }


def send_dingtalk(webhook_url: str, alert: dict, secret: str = '') -> tuple[bool, str]:
    """钉钉自定义机器人 Webhook（Markdown + 可选 HMAC-SHA256 签名）。"""
    url = webhook_url
    if secret and secret.strip():
        ts = str(round(time.time() * 1000))
        string_to_sign = f"{ts}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        sign = base64.b64encode(hmac_code).decode()
        url = f"{webhook_url}&timestamp={ts}&sign={quote(sign)}"
    payload = _dingtalk_markdown(alert)
    ok, resp = _post_json(url, payload)
    if ok:
        try:
            body = json.loads(resp)
            if body.get('errcode', 0) != 0:
                return False, f"DingTalk errcode={body.get('errcode')} errmsg={body.get('errmsg', resp[:200])}"
        except Exception:
            pass
    return ok, resp


# ── 企业微信 Markdown ────────────────────────


def _wechat_markdown(alert: dict) -> dict:
    lang      = (alert.get('lang') or 'zh').lower()
    is_en     = lang == 'en'
    severity  = (alert.get('severity') or 'info').lower()
    title     = alert.get('title', 'Alert' if is_en else '告警通知')
    obj       = alert.get('object_name', '-')
    ip        = alert.get('ip_address', '-')
    status_raw = (alert.get('status') or 'active').lower()
    status    = _status_label(status_raw, lang)
    msg       = alert.get('message', '-')
    first_ts  = alert.get('first_occurrence', _now_str())
    last_ts   = alert.get('last_occurrence', first_ts)

    # 恢复告警附加字段
    dur_secs  = alert.get('duration_seconds')
    imp_win   = alert.get('impact_window')
    alert_cnt = alert.get('alert_count')
    dur_str   = _fmt_duration(dur_secs, is_en) if dur_secs is not None else None

    if status_raw == 'resolved':
        emoji = '🟢'
        color = 'info'
        sev_label = 'Clear' if is_en else '恢复/正常'
        title_text = "Alert Recovery Notification" if is_en else "网络告警恢复通知"
    else:
        emoji = _SEVERITY_EMOJI.get(severity, '⚪')
        color = _WECHAT_FONT_COLOR.get(severity, 'comment')
        sev_label = (_SEVERITY_LABEL_EN if is_en else _SEVERITY_LABEL_ZH).get(severity, severity.upper())
        title_text = title

    if is_en:
        extra_lines = ""
        if imp_win:
            extra_lines += f"> **Impact Window**: {imp_win}\n"
        if dur_str:
            extra_lines += f"> **Duration**: {dur_str}\n"
        if alert_cnt is not None:
            extra_lines += f"> **Alert Count**: {alert_cnt}\n"
        sys_name = _get_system_name()
        content = (
            f"# {emoji} <font color=\"{color}\">[{sev_label}]</font> {title_text}\n"
            f"> **Alert Name**: {title}\n"
            f"> **Object**: {obj}\n"
            f"> **IP**: {ip}\n"
            f"> **Status**: {status}\n"
            f"> **Severity**: <font color=\"{color}\">**{sev_label}**</font>\n"
            f"> **Description**: {msg}\n"
            f"> **First Occurrence**: {first_ts}\n"
            f"> **Last Occurrence**: {last_ts}\n"
            f"{extra_lines}"
            f"> Source: {sys_name} NOC"
        )
    else:
        extra_lines = ""
        if imp_win:
            extra_lines += f"> **影响时间窗**：{imp_win}\n"
        if dur_str:
            extra_lines += f"> **持续时长**：{dur_str}\n"
        if alert_cnt is not None:
            extra_lines += f"> **告警次数**：{alert_cnt}\n"
        sys_name = _get_system_name()
        content = (
            f"# {emoji} <font color=\"{color}\">[{sev_label}]</font> {title_text}\n"
            f"> **告警名称**：{title}\n"
            f"> **告警对象**：{obj}\n"
            f"> **告警 IP**：{ip}\n"
            f"> **处理状态**：{status}\n"
            f"> **告警级别**：<font color=\"{color}\">**{sev_label}**</font>\n"
            f"> **告警描述**：{msg}\n"
            f"> **首次发生**：{first_ts}\n"
            f"> **最后发生**：{last_ts}\n"
            f"{extra_lines}"
            f"> 来源：{sys_name} NOC"
        )
    return {"msgtype": "markdown", "markdown": {"content": content}}


def send_wechat(webhook_url: str, alert: dict) -> tuple[bool, str]:
    """企业微信机器人 Webhook（Markdown）。"""
    payload = _wechat_markdown(alert)
    ok, resp = _post_json(webhook_url, payload)
    if ok:
        try:
            body = json.loads(resp)
            if body.get('errcode', 0) != 0:
                return False, f"WeCom errcode={body.get('errcode')} errmsg={body.get('errmsg', resp[:200])}"
        except Exception:
            pass
    return ok, resp


# ── 统一分发 ─────────────────────────────────


def send_all_channels(channels: dict, alert: dict) -> list[dict]:
    """
    遍历用户配置的所有通知渠道并发送告警。

    alert 格式：
    {
        "title":            "Interface Down",
        "object_name":      "GigabitEthernet0/1",
        "ip_address":       "192.168.1.1",
        "status":           "active" | "resolved" | "acknowledged",
        "severity":         "critical" | "major" | "warning" | "info" | "low",
        "message":          "端口状态变更：UP → DOWN",
        "first_occurrence": "2026-03-08 10:00:00",
        "last_occurrence":  "2026-03-08 10:00:00",
    }
    channels 格式（来自 users.notification_channels JSON）：
    {
        "feishu":   {"webhook_url": "...", "enabled": true},
        "dingtalk": {"webhook_url": "...", "enabled": true, "secret": "..."},
        "wechat":   {"webhook_url": "...", "enabled": true}
    }
    """
    results = []
    if not channels:
        return results

    feishu = channels.get('feishu') or {}
    if feishu.get('enabled') and feishu.get('webhook_url', '').strip():
        ok, msg = send_feishu(feishu['webhook_url'], alert)
        results.append({"platform": "feishu", "success": ok, "error": "" if ok else msg})
        if ok:
            logger.info("[Notify] Feishu notification sent")
        else:
            logger.warning(f"[Notify] Feishu send failed: {msg}")

    dingtalk = channels.get('dingtalk') or {}
    if dingtalk.get('enabled') and dingtalk.get('webhook_url', '').strip():
        ok, msg = send_dingtalk(dingtalk['webhook_url'], alert, secret=dingtalk.get('secret', ''))
        results.append({"platform": "dingtalk", "success": ok, "error": "" if ok else msg})
        if ok:
            logger.info("[Notify] DingTalk notification sent")
        else:
            logger.warning(f"[Notify] DingTalk send failed: {msg}")

    wechat = channels.get('wechat') or {}
    if wechat.get('enabled') and wechat.get('webhook_url', '').strip():
        ok, msg = send_wechat(wechat['webhook_url'], alert)
        results.append({"platform": "wechat", "success": ok, "error": "" if ok else msg})
        if ok:
            logger.info("[Notify] WeCom notification sent")
        else:
            logger.warning(f"[Notify] WeCom send failed: {msg}")

    return results


def _dispatch_to_users(
    alert: dict,
    tenant_id: str | None = None,
    *,
    channels: set[str] | list[str] | tuple[str, ...] | None = None,
    profile_id: str | None = None,
    legacy_primary: bool = False,
    raise_on_error: bool = False,
) -> list[dict]:
    """Dispatch through configured channels without crossing tenant scope.

    ``channels=None`` preserves the legacy workspace behavior and follows each
    user's enabled preferences.  An explicit channel set is used by a rule
    notification policy and prevents a Feishu-only rule from also sending to
    other configured destinations.
    """
    if not automatic_notifications_enabled():
        logger.info("[Notify] Automatic notification dispatch disabled by runtime policy")
        return []

    tenant_id = str(tenant_id or '').strip()
    requested_channels = None if channels is None else {
        str(channel or '').strip().lower()
        for channel in channels
        if str(channel or '').strip()
    }
    conn = get_db_connection()
    try:
        # 1. 获取全局通道配置（作为 URL 和 Secret 的来源）
        global_rows = conn.execute(
            "SELECT platform, webhook_url, enabled, secret FROM global_notification_channels"
        ).fetchall()
        global_map = {str(r['platform'] or '').strip().lower(): dict(r) for r in global_rows}

        # 2. 获取所有用户的通知偏好
        user_query = "SELECT id, email, group_name, notification_channels, preferred_language FROM users WHERE status = 'active'"
        user_params: list[str] = []
        if tenant_id:
            user_query += " AND tenant_id = ?"
            user_params.append(tenant_id)
        user_rows = [dict(row) for row in conn.execute(user_query, user_params).fetchall()]

        # 3. 汇总去重后的发送目标。个人设置可以覆盖全局通道；如果
        # 个人设置只保存了掩码值，则安全地回退到全局通道配置。
        # targets: (platform, url) -> {secret, lang}
        targets = {}
        email_recipients: list[str] = []
        email_pref_seen = False

        def _unmasked(value) -> str:
            normalized = str(value or '').strip()
            if not normalized or '***' in normalized or '****' in normalized:
                return ''
            return normalized

        for u_row in user_rows:
            try:
                user_channels = json.loads(u_row['notification_channels'] or '{}')
                u_lang = u_row['preferred_language'] or 'zh'
            except Exception:
                continue
            if not isinstance(user_channels, dict):
                user_channels = {}

            personal_platforms = {
                str(platform).strip().lower()
                for platform in user_channels
                if str(platform).strip().lower() in {'feishu', 'dingtalk', 'wechat', 'email'}
            }
            configured_platforms = (
                set(requested_channels)
                if requested_channels is not None
                else set(global_map) | personal_platforms
            )
            for platform in configured_platforms:
                if platform == 'email':
                    email_pref_seen = True
                    email_pref = user_channels.get('email') or {}
                    if not isinstance(email_pref, dict):
                        email_pref = {}
                    if not bool(email_pref.get('enabled')):
                        continue
                    status = str(alert.get('status') or 'active').strip().lower()
                    if status == 'resolved' and email_pref.get('recovery_enabled') is False:
                        continue
                    if status != 'resolved' and email_pref.get('active_enabled') is False:
                        continue
                    raw_email = u_row.get('email') if hasattr(u_row, 'get') else u_row['email']
                    address = str(raw_email or '').strip().lower()
                    if address and address not in email_recipients:
                        email_recipients.append(address)
                    continue

                g_cfg = global_map.get(platform) or {}
                u_pref = user_channels.get(platform) or {}
                if not isinstance(u_pref, dict):
                    u_pref = {}

                personal_url = _unmasked(u_pref.get('webhook_url'))
                webhook_url = personal_url or _unmasked(g_cfg.get('webhook_url'))
                if not webhook_url:
                    continue

                # 优先级：用户设置的 enabled 状态 > 全局设置。没有显式
                # enabled 时，个人 URL 默认启用；只有全局回退 URL 时才
                # 继承全局开关。
                if 'enabled' in u_pref:
                    is_enabled = bool(u_pref.get('enabled'))
                elif personal_url:
                    is_enabled = True
                else:
                    is_enabled = bool(g_cfg.get('enabled'))
                if not is_enabled:
                    continue

                personal_secret = _unmasked(u_pref.get('secret'))
                secret = personal_secret or _unmasked(g_cfg.get('secret'))
                key = (platform, webhook_url)
                if key not in targets:
                    targets[key] = {
                        'secret': secret,
                        'lang': u_lang,
                    }

        # 4. 执行 webhook 发送
        results = []
        for (platform, url), cfg in targets.items():
            # 为当前目的地克隆告警信息并设置语言
            user_alert = {**alert, 'lang': cfg['lang']}
            
            if platform == 'feishu':
                ok, msg = send_feishu(url, user_alert)
            elif platform == 'dingtalk':
                ok, msg = send_dingtalk(url, user_alert, secret=cfg['secret'])
            elif platform == 'wechat':
                ok, msg = send_wechat(url, user_alert)
            else:
                continue
            
            results.append({"platform": platform, "success": ok, "error": "" if ok else msg})
            if ok:
                logger.info(f"[Notify] Dispatched to {platform}: {url[:30]}...")
            else:
                logger.warning(f"[Notify] Dispatch failed to {platform}: {msg}")

        email_requested = requested_channels is not None and 'email' in requested_channels
        if requested_channels is None and email_pref_seen:
            email_requested = True
        if email_requested:
            if profile_id:
                email_profiles = get_email_profiles_for_dispatch(
                    conn,
                    tenant_id or 'tenant-default',
                    profile_id=profile_id,
                )
            elif legacy_primary or requested_channels is None:
                # Workspace notifications retain the legacy primary profile.
                email_profiles = get_email_profiles_for_dispatch(
                    conn,
                    tenant_id or 'tenant-default',
                    legacy_primary=True,
                )
            else:
                email_profiles = get_email_profiles_for_dispatch(
                    conn,
                    tenant_id or 'tenant-default',
                    enabled_only=True,
                )

            if not email_profiles:
                results.append({
                    'platform': 'email',
                    'success': False,
                    'error': 'smtp_config_missing',
                    'recipient_count': len(email_recipients),
                    'destination_key': profile_id or 'primary',
                })
            else:
                for smtp_config in email_profiles:
                    if not bool(smtp_config.get('enabled')):
                        results.append({
                            'platform': 'email',
                            'success': False,
                            'error': 'smtp_config_missing',
                            'recipient_count': 0,
                            'destination_key': str(smtp_config.get('id') or profile_id or 'primary'),
                        })
                        continue
                    targets = _profile_targets(smtp_config)
                    if targets:
                        profile_recipients = _profile_email_recipients(smtp_config, user_rows)
                    elif str(smtp_config.get('name') or '').strip().lower() == 'primary':
                        profile_recipients = email_recipients
                    else:
                        profile_recipients = []
                    if not profile_recipients:
                        results.append({
                            'platform': 'email',
                            'success': False,
                            'error': 'email_no_recipients',
                            'recipient_count': 0,
                            'destination_key': str(smtp_config.get('id') or profile_id or 'primary'),
                        })
                        continue
                    email_result = send_email(smtp_config, profile_recipients, alert)
                    results.append({
                        'platform': 'email',
                        'success': bool(email_result.get('success')),
                        'error': email_result.get('error_code') or '',
                        'recipient_count': int(email_result.get('recipient_count') or 0),
                        'destination_key': str(smtp_config.get('id') or profile_id or 'primary'),
                    })

        return results
    except Exception as e:
        logger.error(f"[Notify] scoped notification dispatch error: {e}")
        if raise_on_error:
            raise
        return []
    finally:
        conn.close()


def dispatch_to_all_users(
    alert: dict,
    *,
    channels: set[str] | list[str] | tuple[str, ...] | None = None,
    profile_id: str | None = None,
    legacy_primary: bool = False,
    raise_on_error: bool = False,
) -> list[dict]:
    """Dispatch to all configured active users (legacy alert path)."""
    return _dispatch_to_users(
        alert,
        channels=channels,
        profile_id=profile_id,
        legacy_primary=legacy_primary,
        raise_on_error=raise_on_error,
    )


def dispatch_to_tenant_users(
    alert: dict,
    tenant_id: str,
    *,
    channels: set[str] | list[str] | tuple[str, ...] | None = None,
    profile_id: str | None = None,
    legacy_primary: bool = False,
    raise_on_error: bool = False,
) -> list[dict]:
    """Dispatch only to active users in the Playbook execution tenant."""
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        logger.warning('[Notify] tenant-scoped dispatch rejected without tenant_id')
        return []
    return _dispatch_to_users(
        alert,
        tenant_id=tenant_id,
        channels=channels,
        profile_id=profile_id,
        legacy_primary=legacy_primary,
        raise_on_error=raise_on_error,
    )
