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
from datetime import datetime
from urllib import request as urlrequest, error as urlerror
from urllib.parse import quote

logger = logging.getLogger(__name__)

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


def dispatch_to_all_users(alert: dict) -> list[dict]:
    """
    遍历所有用户，根据其个人通知偏好（enabled/disabled）分发告警。
    自动去重 (platform, webhook_url)，防止对同一个群组机器人重复发消息。
    """
    from database import get_db_connection
    conn = get_db_connection()
    try:
        # 1. 获取全局通道配置（作为 URL 和 Secret 的来源）
        global_rows = conn.execute(
            "SELECT platform, webhook_url, enabled, secret FROM global_notification_channels"
        ).fetchall()
        global_map = {r['platform']: dict(r) for r in global_rows}

        # 2. 获取所有用户的通知偏好
        user_rows = conn.execute(
            "SELECT notification_channels, preferred_language FROM users WHERE status = 'active'"
        ).fetchall()

        # 3. 汇总去重后的发送目标
        # targets: (platform, url) -> {secret, lang}
        targets = {}  
        
        for u_row in user_rows:
            try:
                user_channels = json.loads(u_row['notification_channels'] or '{}')
                u_lang = u_row['preferred_language'] or 'zh'
            except Exception:
                continue

            for platform, g_cfg in global_map.items():
                if not g_cfg['webhook_url']:
                    continue
                
                u_pref = user_channels.get(platform, {})
                # 优先级：用户设置的 enabled 状态 > 全局设置
                is_enabled = u_pref.get('enabled') if 'enabled' in u_pref else bool(g_cfg['enabled'])
                
                if is_enabled:
                    key = (platform, g_cfg['webhook_url'])
                    if key not in targets:
                        targets[key] = {
                            'secret': g_cfg['secret'] or '',
                            'lang': u_lang
                        }

        # 4. 执行发送
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

        return results
    except Exception as e:
        logger.error(f"[Notify] dispatch_to_all_users error: {e}")
        return []
    finally:
        conn.close()
