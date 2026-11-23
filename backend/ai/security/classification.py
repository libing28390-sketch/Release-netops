"""Classification primitives for the Nexora AI security boundary.

The classifier deliberately errs on the side of a higher sensitivity level.
It is used before any provider request is constructed, so a caller cannot
turn a finding into a harmless-looking mask and still send the original value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import Any, Iterable, Mapping

from core.enum_compat import StrEnum


class DataLevel(IntEnum):
    L0_PUBLIC = 0
    L1_GENERAL = 1
    L2_IDENTIFIER = 2
    L3_SENSITIVE = 3
    L4_PROHIBITED = 4


class SecurityAction(StrEnum):
    ALLOW = "ALLOW"
    MINIMIZE = "MINIMIZE"
    TOKENIZE = "TOKENIZE"
    BLOCK = "BLOCK"


class DataClassification(StrEnum):
    """Stable policy vocabulary exposed by the Security Gateway contract."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"


@dataclass(frozen=True)
class Finding:
    level: DataLevel
    category: str
    start: int | None = None
    end: int | None = None
    detail: str = ""


# These patterns are intentionally value-oriented.  A key name by itself is
# not a secret, while a key name followed by a value is prohibited.
# re.ASCII makes ``\b`` true between an English keyword and a following
# Chinese character, so prose such as "token过期" or "提示password错误" would
# read as an assignment whose value is the Chinese text.  A CJK character may
# follow the keyword only as an operator (是/为/设置为 ...) that introduces an
# ASCII value, e.g. "password是Huawei@123".
_KEYWORD_NOT_PROSE = r"(?!(?!(?:是|为|设置为|设为|改为|改成|修改为)\s*['\"“‘「]?[!-~]{4})[\u3400-\u9fff\uf900-\ufaff])"
_POLICY_WORD_NOT_VALUE = (
    r"(?!(?:polic(?:y|ies)|complexity|length|expir[a-z]*|rotation|strength|requirements?|rules?|minimum|maximum|aging)\b)"
)
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?:password|passwd|secret|community|token|api[_ -]?key|access[_ -]?token|"
    r"private[_ -]?key|pre-shared-key|key-string|shared-key)\b" + _KEYWORD_NOT_PROSE + r"\s*"
    # Huawei VRP permits an optional privilege-level selector before the
    # cipher/simple modifier (for example ``password level 3 cipher``). Keep
    # the selector in the command grammar so a redacted value is not mistaken
    # for live credential material while real values remain detectable.
    r"(?:(?:[:=]\s*)|(?:(?:level\s+\d+\s+)?(?:irreversible[-_ ]?cipher|cipher|simple|hash|7|8|9|read|write)\s+)|(?:level\s+\d+\s+))?"
    # Do not backtrack and treat a standalone CLI modifier such as
    # ``password irreversible-cipher`` as the credential value.  If the
    # actual value arrives in a later stream chunk, the output resolver keeps
    # the directive pending until it can scan the complete assignment.
    # Policy words (``password complexity``, ``token expired``) are prose,
    # not a credential value, and the ``:``/``=`` operator is never the value
    # itself (task d1).
    r"['\"]?(?!(?:irreversible[-_ ]?cipher|cipher|simple|hash|7|8|9|read|write)\b)" + _POLICY_WORD_NOT_VALUE
    + r"(?![:=])([^\s,'\";\\]+)",
    re.ASCII,
)
RADIUS_TACACS_SECRET_RE = re.compile(
    r"(?im)\b(?:radius|tacacs(?:\+|[-_ ]plus)?)[-_ ]?(?:key|secret|shared[-_ ]?secret|server[-_ ]?key)\b" + _KEYWORD_NOT_PROSE + r"\s*(?:[:=]|secret|key)?\s*"
    # VRP modifiers (``radius-server key cipher <value>``) precede the value.
    r"(?:(?:irreversible[-_ ]?cipher|cipher|simple|hash|7|8|9)\s+)*['\"]?([^\s,'\";]+)",
    re.ASCII,
)
JWT_RE = re.compile(r"(?i)\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b", re.ASCII)
# A redacted cookie value (``Cookie: <REDACTED>``) is not live material.
COOKIE_RE = re.compile(r"(?i)\b(?:cookie|set-cookie)\s*[:=](?!\s*<REDACTED)\s*[^\r\n;]+", re.ASCII)
SERIAL_RE = re.compile(
    r"(?i)\b(?:"
    r"serial(?:[-_ ]?number)?\s*[:=#-]\s*[A-Z0-9][A-Z0-9._-]{5,31}|"
    r"sn\s*[:=#-]\s*[A-Z0-9][A-Z0-9._-]{5,31}|"
    r"sn[-_ ]+[A-Z0-9][A-Z0-9._-]{5,31}"
    r")\b",
    re.ASCII,
)
SITE_NAME_RE = re.compile(r"(?i)(?:\bsite|机房|园区|站点)\s*[:=：]\s*[\u4e00-\u9fffA-Za-z0-9][^\r\n,;]{1,80}", re.ASCII)
BUSINESS_NAME_RE = re.compile(r"(?i)(?:\b(?:customer|business|project|department)|业务|客户|项目|部门)\s*[:=：]\s*[^\r\n,;]{1,80}", re.ASCII)
SNMP_SECRET_RE = re.compile(r"(?im)\bsnmp(?:-agent|-server)?\s+community\s+(?:(?:read|write|cipher|simple)\s+)*([^\s\\]+)", re.ASCII)
_ASSIGNMENT_MODIFIER_VALUES = frozenset({"read", "write", "cipher", "simple", "hash", "7", "8", "9"})
_REDACTED_ASSIGNMENT_VALUE_RE = re.compile(r"^<REDACTED(?:_[A-Z0-9]+)?>$", re.IGNORECASE)
# A marker followed by sentence text ("<REDACTED>，帮我检查VLAN10") is still a
# redacted value: the ASCII run right after the marker carries no letter or
# digit.  A backslash ends the run (JSON-escaped "\n" in a serialized body).
_REDACTED_VALUE_PREFIX_RE = re.compile(r"^<REDACTED(?:_[A-Z0-9]+)?>(?![!-\[\]-~]*[A-Za-z0-9])", re.IGNORECASE)
_CN_ASSIGNMENT_OPERATOR_RE = re.compile(r"^(?:设置为|修改为|设为|改为|改成|是|为)\s*[\"'“‘「]?")
_TOKEN_PLACEHOLDER_RE = re.compile(r"\[\[NXA_[A-Z0-9]+_[A-Za-z0-9_-]{16,}\]\]")
_NON_HOST_DOTTED_CODE_RE = re.compile(r"(?i)(?<![\w.-])(?:ai\.assistant|permission\.[a-z0-9_.-]+)(?![\w.-])")


def is_redacted_assignment_match(match: re.Match[str]) -> bool:
    """Return whether a credential detector matched only a safe placeholder.

    Sanitized network configuration deliberately keeps the directive shape,
    for example ``snmp-agent community read <REDACTED>``.  The detector must
    not treat the redaction marker, or the ``read`` modifier when no value is
    present, as a live credential.
    """

    value = (match.group(1) or "").strip().strip("'\"")
    # "password是<REDACTED>": the Chinese operator is part of the captured
    # value when the keyword is followed by CJK text.
    value = _CN_ASSIGNMENT_OPERATOR_RE.sub("", value, count=1)
    if _REDACTED_ASSIGNMENT_VALUE_RE.fullmatch(value) or _REDACTED_VALUE_PREFIX_RE.match(value):
        return True
    if value.casefold() in _ASSIGNMENT_MODIFIER_VALUES:
        return bool(re.search(r"\bcommunity\s+$", match.group(0), re.IGNORECASE))
    return False
IPV4_RE = re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])", re.ASCII)
IPV6_RE = re.compile(
    r"(?i)(?<![\w:])(?:"
    r"(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,7}:|"
    r"(?:[0-9a-f]{1,4}:){1,6}:[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,5}(?::[0-9a-f]{1,4}){1,2}|"
    r"(?:[0-9a-f]{1,4}:){1,4}(?::[0-9a-f]{1,4}){1,3}|"
    r"(?:[0-9a-f]{1,4}:){1,3}(?::[0-9a-f]{1,4}){1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,2}(?::[0-9a-f]{1,4}){1,5}|"
    r"[0-9a-f]{1,4}:(?:(?::[0-9a-f]{1,4}){1,6})|"
    r":(?:(?::[0-9a-f]{1,4}){1,7}|:)"
    r")(?![\w:])",
    re.ASCII,
)
MAC_RE = re.compile(r"(?i)(?<![\w])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w])", re.ASCII)
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])", re.ASCII)
# Dates and times are not phone numbers (task d1): with re.ASCII a date that
# touches a Chinese character ("告警于2024-01-01发生") would otherwise match.
# Excluded: YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD (with or without a time or
# time zone after it), YYYYMMDD followed by a time, and any run that starts
# right after "digit + separator" (the tail of a date or a time).
_DATE_TIME_AHEAD = (
    r"(?!(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])(?!\d)"
    r"|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[T ]?(?:[01]\d|2[0-3]):?[0-5]\d)"
)
PHONE_RE = re.compile(r"(?<!\w)(?<!\d[-/.:])" + _DATE_TIME_AHEAD + r"(?:\+?\d[\d ()-]{7,18}\d)(?!\w)", re.ASCII)
HOSTNAME_RE = re.compile(
    r"(?<![\w.-])(?=[A-Za-z0-9.-]{3,253}(?![\w.-]))"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}|"
    # A bare hyphenated English phrase (for example ``read-only`` or
    # ``natural-language``) is common in system prompts and is not evidence
    # of a network hostname.  Keep short hostname detection for the usual
    # device-style form with a numeric segment (``sw-core01``), while dotted
    # DNS names remain covered by the branch above.
    r"[A-Za-z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]*\d[A-Za-z0-9]*)+(?![\w.-])",
    re.ASCII,
)

PROMPT_INJECTION_RE = re.compile(
    r"(?i)\b(?:ignore|disregard|override|bypass)\b.{0,80}\b(?:previous|prior|system|developer|policy|instruction)s?\b"
    r"|\b(?:reveal|show|print|leak|repeat|output)\b.{0,60}\b(?:system|developer|hidden|initial)\s+prompts?\b"
    r"|\b(?:jailbreak|DAN\s+mode)\b",
    re.ASCII,
)
# Chinese injection phrasing (review M13: detection was English only).  The
# object words are AI-specific (指令/提示词/设定 ...) or need an AI-directed
# qualifier (你的/系统/所有 ...), so ordinary operations text such as
# "忽略之前的告警" or "实验环境可以忽略上述限制" is not flagged.
PROMPT_INJECTION_ZH_RE = re.compile(
    r"(?:忽略|无视|忽视|忘记|忘掉|抛开|抛弃|不要理会|不用理会|不要遵守|不再遵守|停止遵守|不必遵守)"
    r"[^。！？!?\n]{0,12}?(?:之前|此前|先前|前面|上面|上述|以上|原有|原来|原先|所有|全部|一切|你的|系统|开发者)"
    r"[^。！？!?\n]{0,8}?(?:指令|指示|提示词|系统提示|设定|人设)"
    r"|(?:忽略|无视|忽视|忘记|忘掉|抛开|抛弃|不要理会|不用理会|不要遵守|不再遵守|停止遵守|不必遵守)"
    r"[^。！？!?\n]{0,12}?(?:你的|系统|开发者|所有|全部|一切)[^。！？!?\n]{0,8}?(?:规则|限制|约束|要求|守则|准则)"
    r"|(?:你现在是|从现在(?:开始|起)[，, ]?你|你将扮演|你要扮演|请扮演|扮演一个|假装你是|假设你是)"
    r"[^。！？!?\n]{0,30}?(?:没有任何|没有|不受|无|解除|取消)(?:任何)?(?:限制|约束|审查|规则|过滤)"
    r"|越狱模式|无限制模式|DAN\s*模式|上帝模式|(?:进入|开启|切换到|启用)开发者模式"
    r"|(?:输出|显示|打印|泄露|泄漏|重复|复述|告诉我|给我看|展示|透露)[^。！？!?\n]{0,16}?(?:提示词|系统提示|system\s*prompt)"
    r"|(?:你的|系统|初始|隐藏|原始)(?:提示词|系统提示|设定)[^。！？!?\n]{0,12}?"
    r"(?:输出|显示|打印|泄露|泄漏|重复|复述|发给我|告诉我|给我看|展示|透露)",
    re.IGNORECASE,
)
FULL_CONFIG_RE = re.compile(
    r"(?i)(?:show|display)\s+(?:running-config|current-configuration|configuration)|"
    r"\b(?:running-config|current-configuration|full topology)\b|完整拓扑|全量配置",
    re.ASCII,
)
FULL_CMDB_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:cmdb|asset inventory|device inventory)\b|全量(?:CMDB|资产|设备清单)")
FULL_LOG_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:logs?|log stream|session logs?)\b|全量日志|完整日志")
FULL_SESSION_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:sessions?|terminal sessions?)\b|全量会话|完整会话")
CONFIG_CHANGE_RE = re.compile(
    r"(?i)\b(?:configure terminal|system-view|commit|write memory|save)\b|"
    r"(?:下发|修改|变更|删除|清空|重启|重载|保存)\s*(?:配置|设备|端口|接口|命令|操作|规则|策略)|"
    r"批量(?:关闭|启用|开启|变更|操作|下发)|"
    r"(?:关闭|禁用)\s*(?:端口|接口)",
    re.ASCII,
)
HIDDEN_INSTRUCTION_RE = re.compile(r"(?is)(?:<!--.*?(?:ignore|system|instruction|override|忽略|系统提示|指令|提示词).*?-->|<script\b.*?>.*?</script>|style\s*=\s*['\"][^'\"]*(?:display\s*:\s*none|visibility\s*:\s*hidden))")

# A request to retrieve a credential is prohibited even when the user did not
# paste a credential value.  Checking the request verb and the protected
# object together avoids treating ordinary security explanations as secrets,
# while ensuring that ``SSH 账密``/``show the password`` cannot reach a cloud
# model merely because no ``key=value`` assignment was present.
CREDENTIAL_REQUEST_RE = re.compile(
    r"(?is)(?:"
    r"\b(?:show|display|reveal|output|print|return|provide|give|list|fetch|retrieve|export|dump|send|share|tell(?:\s+me)?|query|get|access)\b"
    r"[\s\S]{0,120}?\b(?:passwords?|passwd|credentials?|ssh\s+(?:credentials?|passwords?|keys?)|snmp\s+(?:community|string)|community\s+strings?|private\s+keys?|api\s+keys?)\b"
    r"|\b(?:passwords?|passwd|credentials?|ssh\s+(?:credentials?|passwords?|keys?)|snmp\s+(?:community|string)|community\s+strings?|private\s+keys?|api\s+keys?)\b"
    r"[\s\S]{0,120}?\b(?:show|display|reveal|output|print|return|provide|give|list|fetch|retrieve|export|dump|send|share|tell(?:\s+me)?|query|get|access)\b"
    r"|(?:查询|获取|列出|输出|返回|提供|导出|查看|读取|发送|共享|告诉我|给我|拿到|访问)"
    r"[^\r\n。！？]{0,100}(?:密码|凭据|账密|口令|私钥|密钥|SNMP共同体|社区字符串|令牌|秘密"
    r"|SNMP\s*community|community\s*strings?|passwords?|passwd|credentials?|private\s*keys?|api\s*keys?)"
    r"|(?:密码|凭据|账密|口令|私钥|密钥|SNMP共同体|社区字符串|令牌|秘密)"
    r"[^\r\n。！？]{0,100}(?:查询|获取|列出|输出|返回|提供|导出|查看|读取|发送|共享|告诉我|给我|拿到|访问)"
    r")",
    re.ASCII,
)
# Asking about a password *policy* ("查看密码复杂度策略", "show password
# complexity") is not a credential request (task d1).  The phrase is replaced
# before CREDENTIAL_REQUEST_RE runs, so "show the admin password" in the same
# message is still found.
_CREDENTIAL_POLICY_PHRASE_RE = re.compile(
    r"(?i)(?:\b(?:passwords?|passwd|credentials?|community\s+strings?|private\s+keys?|api\s+keys?)\b|密码|凭据|账密|口令|私钥|密钥|令牌)"
    r"\s*(?:的\s*)?"
    r"(?:复杂度|策略|长度|规则|过期|有效期|强度|要求|位数|polic(?:y|ies)|complexity|length|expir[a-z]*|rotation|strength|requirements?|rules?)",
    re.ASCII,
)
# A credential keyword whose value was redacted ("密码是<REDACTED>",
# "password cipher <REDACTED>") is a statement, not a request.
_REDACTED_ASSIGNMENT_PHRASE_RE = re.compile(
    r"(?i)(?:(?:snmp(?:-(?:agent|server))?|radius(?:-server)?|tacacs(?:\+|[-_ ]plus|-server)?)\s+)?"
    r"(?:\b(?:passwords?|passwd|secret|community|token|api[_ -]?key|access[_ -]?token|private[_ -]?key|pre-shared-key|key-string|shared-key|key)\b"
    r"|预共享密钥|共享密钥|认证密钥|登录密码|管理员密码|密码|口令|密钥|团体名|团体字|共同体名|社区字符串)"
    r"[^\S\r\n]*(?:[:：=]|设置为|修改为|设为|改为|改成|是|为)?[^\S\r\n]*"
    r"(?:(?:level\s+\d+|irreversible[-_ ]?cipher|cipher|simple|hash|7|8|9|read|write)\s+)*"
    r"[\"'“‘「]?<REDACTED(?:_[A-Z0-9]+)?>",
    re.ASCII,
)


def _credential_request_probe(content: str) -> str:
    probe, _ = redact_secrets(content)
    probe = _REDACTED_ASSIGNMENT_PHRASE_RE.sub("<REDACTED>", probe)
    return _CREDENTIAL_POLICY_PHRASE_RE.sub("策略", probe)


TENANT_REFERENCE_RE = re.compile(r"(?i)\btenant[-_:]?[a-z0-9][a-z0-9_-]{1,80}\b", re.ASCII)
_SCOPE_REQUEST_RE = re.compile(
    r"(?i)(?:\b(?:query|show|display|list|fetch|retrieve|export|dump|access|get|provide|give|send|share)\b|"
    r"查询|查看|获取|列出|导出|读取|访问|提供|给我|发送|共享)",
    re.ASCII,
)
_PRIVATE_SCOPE_MARKER_RE = re.compile(
    r"(?i)(?:\b(?:private|privileged|tenant|cmdb|asset|assets|inventory|device|devices|credential|credentials|password|secret|ssh|snmp)\b|"
    r"私有|专属|租户|资产|设备|清单|凭据|密码|账密|口令|密钥)",
    re.ASCII,
)


# ── Chinese personal information and credentials (review batch 6) ─────────
#
# Identity-card and bank-card numbers are identifiers: they are tokenized for
# the one provider request (the model never sees them) and the final DLP check
# refuses a body that still contains one.  Input detection and DLP use the same
# function so a value that was not tokenized can never fail DLP.
#
# Boundaries are ASCII on purpose: "身份证110105...", "卡号6222..." must match.
_ASCII_WORD = r"A-Za-z0-9_"
_CN_ID_CARD_RE = re.compile(
    rf"(?<![{_ASCII_WORD}])[1-9]\d{{5}}((?:18|19|20)\d{{2}})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{{3}}[0-9Xx](?![{_ASCII_WORD}])",
    re.ASCII,
)
# 16-19 digits, optionally in groups of four separated by one space or hyphen.
_BANK_CARD_RE = re.compile(
    rf"(?<![{_ASCII_WORD}+])\d{{4}}(?:[ -]?\d{{4}}){{3}}(?:[ -]?\d{{1,3}})?(?![{_ASCII_WORD}])",
    re.ASCII,
)
_CN_MOBILE_RE = re.compile(
    rf"(?<![{_ASCII_WORD}+])(?P<prefix>(?:\+|00)86[ -]?)?(?P<number>1[3-9]\d(?P<sep>[ -]?)\d{{4}}(?P=sep)\d{{4}})(?![{_ASCII_WORD}])",
    re.ASCII,
)
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"
_CARD_CONTEXT_RE = re.compile(r"(?i)(?:卡号|银行卡|信用卡|储蓄卡|借记卡|账号|帐号|card)")
_MOBILE_CONTEXT_RE = re.compile(r"(?i)(?:手机|电话|联系|致电|拨打|热线|号码|mobile|phone|tel|call)")


@dataclass(frozen=True)
class PersonalInfoMatch:
    category: str  # cn_id_card | bank_card | cn_mobile
    start: int
    end: int
    value: str


def cn_id_checksum_ok(value: str) -> bool:
    """GB 11643-1999 check digit of an 18-character resident identity number."""

    if len(value) != 18 or not value[:17].isdigit():
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value[:17], _ID_WEIGHTS))
    return _ID_CHECK_CODES[total % 11] == value[17].upper()


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _id_date_ok(match: re.Match[str]) -> bool:
    try:
        born = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return False
    return born <= date.today()


def _context_before(text: str, start: int, context: str, width: int = 16) -> str:
    return (context + text[:start])[-width:]


def find_cn_personal_info(text: str, *, strict: bool = False, context: str = "") -> list[PersonalInfoMatch]:
    """Chinese identity-card, bank-card and (strict mode) mobile numbers.

    ``strict=False`` is used on the way *in* (tokenization and DLP): an ID
    needs a valid structure and birth date, a card number a valid Luhn digit
    or the usual four-digit grouping.  ``strict=True`` is used on model
    *output*, where a match is masked irreversibly, so it also requires the
    ID check digit, a card number in grouped form / after a card keyword /
    with the UnionPay 62 prefix, and a mobile number after a phone keyword or
    with +86.  ``context`` is text that precedes ``text`` (streaming).
    """

    if not text or not any(char.isdigit() for char in text):
        return []
    found: list[PersonalInfoMatch] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= a or start >= b for a, b in taken)

    for match in _CN_ID_CARD_RE.finditer(text):
        value = match.group(0)
        if not _id_date_ok(match) or (strict and not cn_id_checksum_ok(value)):
            continue
        found.append(PersonalInfoMatch("cn_id_card", match.start(), match.end(), value))
        taken.append((match.start(), match.end()))

    for match in _BANK_CARD_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        value = match.group(0)
        digits = re.sub(r"[ -]", "", value)
        if not 16 <= len(digits) <= 19 or len(set(digits)) == 1:
            continue
        grouped = digits != value
        if strict:
            keyword = bool(_CARD_CONTEXT_RE.search(_context_before(text, match.start(), context)))
            if not luhn_ok(digits) or not (grouped or keyword or digits.startswith("62")):
                continue
        elif not (luhn_ok(digits) or grouped):
            continue
        found.append(PersonalInfoMatch("bank_card", match.start(), match.end(), value))
        taken.append((match.start(), match.end()))

    if strict:
        for match in _CN_MOBILE_RE.finditer(text):
            start, end = match.start("number"), match.end("number")
            if not free(match.start(), match.end()):
                continue
            keyword = bool(_MOBILE_CONTEXT_RE.search(_context_before(text, match.start(), context)))
            if not (match.group("prefix") or keyword):
                continue
            found.append(PersonalInfoMatch("cn_mobile", start, end, match.group("number")))
            taken.append((match.start(), match.end()))

    found.sort(key=lambda item: item.start)
    return found


# Chinese credential assignments: "密码是Huawei@123", "口令：P@ssw0rd".
# The value must be printable ASCII (passwords are), so prose such as
# "密码为空" or "密码：至少 8 位" does not match.  Length specs ("8-16"),
# short numbers ("密钥为2048位"), masks and redaction markers are ignored.
CN_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?:预共享密钥|共享密钥|认证密钥|登录密码|管理员密码|密码|口令|密钥|团体名|团体字|共同体名|社区字符串)"
    r"\s*(?:[:：=]|设置为|修改为|设为|改为|改成|是|为)\s*[\"'“‘「]?"
    # Quotes and backslashes end the value: the final DLP check scans the
    # JSON-serialized body, where "密码：******" is followed by `"}]...` and
    # would otherwise be read as a live value.
    r"((?:(?![\"'\\])[!-~]){4,64})"
)
_LENGTH_SPEC_RE = re.compile(r"\d{1,2}(?:[-~]\d{1,2})?", re.ASCII)
_PLACEHOLDER_VALUES = frozenset({"null", "none", "empty", "n/a", "xxxx", "xxxxxx", "password", "your_password", "<password>"})


def cn_secret_value_ok(value: str) -> bool:
    """Whether a matched Chinese assignment value looks like a real secret."""

    text = (value or "").strip().strip("\"'”’」,，。;；")
    if len(text) < 4:
        return False
    if _REDACTED_ASSIGNMENT_VALUE_RE.fullmatch(text) or text.startswith("<REDACTED") or text.startswith("[[NXA_"):
        return False
    if set(text) <= set("*xX•.·#"):
        return False
    if _LENGTH_SPEC_RE.fullmatch(text) or (text.isdigit() and len(text) <= 4):
        return False
    return text.casefold() not in _PLACEHOLDER_VALUES


def iter_cn_secret_assignments(text: str) -> Iterable[re.Match[str]]:
    for match in CN_SECRET_ASSIGNMENT_RE.finditer(text or ""):
        if cn_secret_value_ok(match.group(1)):
            yield match


CN_SECRET_REDACTION = "<REDACTED>"


def redact_cn_secret_assignments(text: str) -> tuple[str, int]:
    """Replace the value of "密码是Huawei@123"-style assignments, keep the rest.

    Chinese credential phrasing is common in vendor manuals and knowledge
    articles ("缺省密码为Admin@123").  Blocking the whole request for it would
    make those documents unusable, so the security gateway and conversation
    storage redact the value instead and the request continues.  The result
    is idempotent: a redacted value no longer matches.  The final DLP check
    still refuses any body that carries an unredacted value.
    """

    if not text:
        return text, 0
    parts: list[str] = []
    last = 0
    count = 0
    for match in iter_cn_secret_assignments(text):
        parts.append(text[last:match.start(1)])
        parts.append(CN_SECRET_REDACTION)
        # Sentence punctuation right after the value ("密码是Huawei@123," /
        # "...123)。") is kept; only the value itself is replaced.
        value = match.group(1)
        # "!" and "?" stay part of the value: passwords often end with them.
        trimmed = value.rstrip(".,;:)]}")
        if len(trimmed) < 4:
            trimmed = value
        last = match.start(1) + len(trimmed)
        count += 1
    if not count:
        return text, 0
    parts.append(text[last:])
    return "".join(parts), count


SECRET_REDACTION = "<REDACTED>"
_COOKIE_VALUE_RE = re.compile(
    r"(?i)\b((?:cookie|set-cookie)\s*[:=](?!\s*<REDACTED)\s*)([^\r\n;]+(?:;[ \t]*[^\s;=]+=[^\r\n;]*)*)",
    re.ASCII,
)
_ASCII_VALUE_RUN_RE = re.compile(r"[!-~]+")


def _assignment_value_span(match: re.Match[str]) -> tuple[int, int] | None:
    """The part of group(1) that is the secret: ASCII, without a CN operator."""

    start = match.start(1)
    value = match.group(1) or ""
    operator = _CN_ASSIGNMENT_OPERATOR_RE.match(value)
    if operator:
        start += operator.end()
        value = value[operator.end():]
    run = _ASCII_VALUE_RUN_RE.match(value)
    if run:
        value = run.group(0)
    # Sentence punctuation after the value stays; the marker plus trailing
    # punctuation is still recognized as redacted.
    trimmed = value.rstrip(".,;:)]}")
    if trimmed:
        value = trimmed
    return (start, start + len(value)) if value else None


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact English and Chinese credential values, keep everything else.

    English assignments (``password``/``secret``/``community``/``token``/
    ``api key``/``key-string``/``pre-shared-key`` ...), SNMP communities and
    RADIUS/TACACS keys get ``<REDACTED>`` in place of the value; the keyword
    and Huawei VRP modifiers (``cipher``, ``irreversible-cipher``,
    ``level N``) stay.  Private-key blocks become ``<REDACTED_PRIVATE_KEY>``,
    JWTs ``<REDACTED_TOKEN>`` and cookie values ``<REDACTED>``.  Chinese
    assignments are handled by :func:`redact_cn_secret_assignments`.

    Idempotent: a redacted value no longer matches any detector.  The final
    DLP check still refuses whatever this function did not redact.
    Returns the redacted text and the number of redactions.
    """

    if not text:
        return text, 0
    result = text
    count = 0
    result, replaced = PRIVATE_KEY_RE.subn("<REDACTED_PRIVATE_KEY>", result)
    count += replaced
    result, replaced = JWT_RE.subn("<REDACTED_TOKEN>", result)
    count += replaced
    result, replaced = _COOKIE_VALUE_RE.subn(lambda match: match.group(1) + SECRET_REDACTION, result)
    count += replaced
    for _ in range(4):
        spans: list[tuple[int, int]] = []
        for pattern in (SECRET_ASSIGNMENT_RE, SNMP_SECRET_RE, RADIUS_TACACS_SECRET_RE):
            for match in pattern.finditer(result):
                if is_redacted_assignment_match(match):
                    continue
                span = _assignment_value_span(match)
                if span:
                    spans.append(span)
        if not spans:
            break
        spans.sort()
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        parts: list[str] = []
        last = 0
        for start, end in merged:
            parts.append(result[last:start])
            parts.append(SECRET_REDACTION)
            last = end
        parts.append(result[last:])
        result = "".join(parts)
        count += len(merged)
    result, replaced = redact_cn_secret_assignments(result)
    count += replaced
    return result, count


def iter_prompt_injection(text: str) -> Iterable[re.Match[str]]:
    yield from PROMPT_INJECTION_RE.finditer(text or "")
    yield from PROMPT_INJECTION_ZH_RE.finditer(text or "")


def classification_for_level(level: DataLevel) -> DataClassification:
    if level <= DataLevel.L0_PUBLIC:
        return DataClassification.PUBLIC
    if level == DataLevel.L1_GENERAL:
        return DataClassification.INTERNAL
    if level == DataLevel.L2_IDENTIFIER:
        return DataClassification.CONFIDENTIAL
    return DataClassification.SECRET


def normalize_classification(value: Any) -> DataClassification | None:
    try:
        return DataClassification(str(value or "").strip().upper())
    except ValueError:
        return None


def separate_data_and_instructions(messages: Any) -> tuple[Any, list[str]]:
    """Mark prompt text as untrusted data and return detected instructions.

    The gateway never promotes text found in documents/tool results to a
    system/developer instruction.  Callers can show the safe categories while
    retaining the original data only inside their tenant-scoped workflow.
    """
    findings: list[str] = []
    for text in iter_text_values(messages):
        if next(iter_prompt_injection(text), None) is not None:
            findings.append("prompt_injection")
        if HIDDEN_INSTRUCTION_RE.search(text):
            findings.append("hidden_instruction")
    return messages, sorted(set(findings))


def iter_text_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            # Keys are metadata and are not sent as user content by the
            # gateway, but inspect them for policy fields such as raw_output.
            if isinstance(key, str):
                yield key
            yield from iter_text_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_text_values(item)


def request_policy_findings(messages: Any, *, tenant_id: str | None = None) -> list[Finding]:
    """Detect access requests that must stop before any model egress.

    This is intentionally separate from :func:`classify_text`: a credential
    *request* is unsafe even without a credential value, while words such as
    ``password`` in an explanatory assistant/system message are not by
    themselves evidence that a user is trying to retrieve a secret.  Tenant
    references are compared with the authenticated tenant so a prompt cannot
    turn an arbitrary ``tenant-...`` identifier into a cloud lookup scope.
    """

    findings: list[Finding] = []
    current_tenant = str(tenant_id or "tenant-default").strip().casefold()
    for item in messages if isinstance(messages, (list, tuple)) else ():
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role") or "").strip().casefold() != "user":
            continue
        content = str(item.get("content") or "")
        if not content:
            continue
        if CREDENTIAL_REQUEST_RE.search(_credential_request_probe(content)):
            findings.append(Finding(DataLevel.L4_PROHIBITED, "credential_request"))

        _GENERIC_TENANT_TOKENS = {"tenant_id", "tenant_name", "tenant_scope", "tenant_key", "tenant_code", "tenant_type"}
        requested_tenants = {
            str(match).strip().casefold()
            for match in TENANT_REFERENCE_RE.findall(content)
            if str(match).strip() and str(match).strip().casefold() not in _GENERIC_TENANT_TOKENS
        }
        if (
            requested_tenants
            and any(target != current_tenant for target in requested_tenants)
            and _SCOPE_REQUEST_RE.search(content)
            and _PRIVATE_SCOPE_MARKER_RE.search(content)
        ):
            findings.append(Finding(DataLevel.L4_PROHIBITED, "cross_tenant_scope_request"))
    return findings


def classify_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    if not text:
        return findings

    # Token placeholders are already scoped to the tenant/task vault.  They
    # must not be reclassified as hostnames or serial numbers merely because
    # the opaque suffix contains hyphens or digits.
    detection_text = _NON_HOST_DOTTED_CODE_RE.sub(
        " ",
        _TOKEN_PLACEHOLDER_RE.sub(" ", text),
    )

    for pattern, category in (
        (PRIVATE_KEY_RE, "private_key"),
        (SECRET_ASSIGNMENT_RE, "credential"),
        (SNMP_SECRET_RE, "snmp_community"),
        (RADIUS_TACACS_SECRET_RE, "radius_or_tacacs_key"),
        (JWT_RE, "jwt"),
        (COOKIE_RE, "cookie"),
    ):
        for match in pattern.finditer(text):
            if pattern in {SECRET_ASSIGNMENT_RE, SNMP_SECRET_RE, RADIUS_TACACS_SECRET_RE} and is_redacted_assignment_match(match):
                continue
            findings.append(Finding(DataLevel.L4_PROHIBITED, category, match.start(), match.end()))
    # Chinese credential phrasing is redacted (not blocked) by the gateway and
    # by conversation storage, so it is reported at L1: it must not raise the
    # data level or quarantine a document.  See redact_cn_secret_assignments.
    for match in iter_cn_secret_assignments(text):
        findings.append(Finding(DataLevel.L1_GENERAL, "credential_redactable", match.start(), match.end(), detail="zh_assignment"))

    for match in FULL_CONFIG_RE.finditer(text):
        findings.append(Finding(DataLevel.L4_PROHIBITED, "full_configuration_or_topology", match.start(), match.end()))
    for pattern, category in ((FULL_CMDB_RE, "full_cmdb"), (FULL_LOG_RE, "full_logs"), (FULL_SESSION_RE, "full_sessions")):
        for match in pattern.finditer(detection_text):
            findings.append(Finding(DataLevel.L4_PROHIBITED, category, match.start(), match.end()))

    for match in iter_prompt_injection(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "prompt_injection", match.start(), match.end()))
    for match in HIDDEN_INSTRUCTION_RE.finditer(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "hidden_instruction", match.start(), match.end()))

    if CONFIG_CHANGE_RE.search(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "change_command", detail="write-capable command"))

    for pattern, category in (
        (IPV4_RE, "ip_address"),
        (IPV6_RE, "ip_address"),
        (MAC_RE, "mac_address"),
        (EMAIL_RE, "email"),
        (PHONE_RE, "phone"),
        (HOSTNAME_RE, "hostname"),
        (SERIAL_RE, "serial_number"),
        (SITE_NAME_RE, "site_name"),
        (BUSINESS_NAME_RE, "business_name"),
    ):
        for match in pattern.finditer(detection_text):
            findings.append(Finding(DataLevel.L2_IDENTIFIER, category, match.start(), match.end()))
    for item in find_cn_personal_info(detection_text):
        findings.append(Finding(DataLevel.L2_IDENTIFIER, item.category, item.start, item.end))

    return findings


def classify(value: Any) -> tuple[DataLevel, list[Finding]]:
    findings = [finding for text in iter_text_values(value) for finding in classify_text(text)]
    if not findings:
        return DataLevel.L1_GENERAL, []
    return max((item.level for item in findings), default=DataLevel.L1_GENERAL), findings


def action_for(level: DataLevel, *, has_prompt_injection: bool = False) -> SecurityAction:
    if level >= DataLevel.L4_PROHIBITED:
        return SecurityAction.BLOCK
    if level == DataLevel.L3_SENSITIVE:
        return SecurityAction.MINIMIZE
    if level == DataLevel.L2_IDENTIFIER or has_prompt_injection:
        return SecurityAction.TOKENIZE
    return SecurityAction.ALLOW
