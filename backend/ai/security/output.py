"""Treat model output as untrusted content before it reaches the UI."""

from __future__ import annotations

import re
from typing import Any

from ai.security.classification import (
    PRIVATE_KEY_RE,
    SECRET_ASSIGNMENT_RE,
    find_cn_personal_info,
    is_redacted_assignment_match,
    iter_cn_secret_assignments,
)
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import TOKEN_RE, ScopedTokenVault


_DANGEROUS_HTML = re.compile(r"(?is)<\s*(?P<tag>script|iframe|object|embed|form)\b[^>]*>.*?<\s*/\s*(?P=tag)\s*>")
_DANGEROUS_URL = re.compile(r"(?i)\b(?:javascript|data|vbscript):")
_TOKEN_OPEN = "[[NXA_"
_CREDENTIAL_KEYWORD_RE = re.compile(
    r"(?i)\b(?:password|passwd|secret|community|token|api[_ -]?key|access[_ -]?token|"
    r"private[_ -]?key|pre-shared-key|key-string|shared-key)\b"
)
_CREDENTIAL_PREFIXES = (
    "password", "passwd", "secret", "community", "token", "api-key",
    "api key", "access-token", "access token", "private-key", "private key",
    "pre-shared-key", "key-string", "shared-key",
)

# Chinese credential keywords (batch 6).  Longest first so that
# "预共享密钥" wins over "密钥".  No word boundary: Chinese has none.
_ZH_CREDENTIAL_KEYWORDS = (
    "预共享密钥", "共享密钥", "社区字符串", "共同体名", "团体名", "团体字",
    "密码", "口令", "密钥",
)
_ZH_CREDENTIAL_KEYWORD_RE = re.compile("|".join(_ZH_CREDENTIAL_KEYWORDS))
# What may follow a keyword while the assignment is still being streamed:
# an optional operator ("是", "：", "设置为" or a prefix of one), an optional
# opening quote, then printable ASCII only.  Any Chinese / non-ASCII
# character after the value ends the assignment and releases the hold.
_ZH_ASSIGNMENT_TAIL_RE = re.compile(
    r"\s*(?:[:：=]|设置为|设置|设为|设|修改为|修改|修|改为|改成|改|是|为)?\s*[\"'“‘「]?[!-~]*"
)
_ZH_CREDENTIAL_PREFIXES = tuple(sorted(
    {keyword[:size] for keyword in _ZH_CREDENTIAL_KEYWORDS for size in range(1, len(keyword))},
    key=len,
    reverse=True,
))

# A trailing run that may still grow into an identity-card, bank-card or
# mobile number (digits, X, spaces, hyphens, a leading +).
_NUMBER_TAIL_RE = re.compile(r"[0-9Xx +-]+$")
_NUMBER_HOLD_MAX = 32
_PII_CONTEXT_CHARS = 24

_MASK_KEEP = {
    # category: (leading alphanumerics kept, trailing alphanumerics kept)
    "cn_id_card": (3, 4),
    "bank_card": (0, 4),
    "cn_mobile": (3, 4),
}


def _mask_value(value: str, category: str) -> str:
    head, tail = _MASK_KEEP.get(category, (0, 4))
    total = sum(1 for char in value if char.isalnum())
    seen = 0
    out: list[str] = []
    for char in value:
        if not char.isalnum():
            out.append(char)  # keep spaces / hyphens of a grouped number
            continue
        keep = seen < head or seen >= total - tail
        out.append(char if keep else "*")
        seen += 1
    return "".join(out)


def _mask_segment(text: str, prefix: str) -> str:
    matches = find_cn_personal_info(text, strict=True, context=prefix)
    if not matches:
        return text
    parts: list[str] = []
    last = 0
    for item in matches:
        parts.append(text[last:item.start])
        parts.append(_mask_value(text[item.start:item.end], item.category))
        last = item.end
    parts.append(text[last:])
    return "".join(parts)


def mask_personal_info(text: str, *, prefix: str = "") -> str:
    """Mask identity-card, bank-card and mobile numbers the model produced.

    Uses the strict (output) detector: valid ID check digit, Luhn plus a
    card-like shape, a phone keyword or +86 for mobile numbers.  ``prefix`` is
    text that precedes ``text`` (the streamed tail) so a keyword in an earlier
    chunk still counts.  Opaque ``[[NXA_...]]`` tokens are left untouched;
    values restored from them later belong to the user and are not masked.
    """

    if not text or not any(char.isdigit() for char in text):
        return text
    parts: list[str] = []
    last = 0
    context = prefix
    for token in TOKEN_RE.finditer(text):
        segment = text[last:token.start()]
        parts.append(_mask_segment(segment, context))
        parts.append(token.group(0))
        context = (context + segment + token.group(0))[-_PII_CONTEXT_CHARS:]
        last = token.end()
    parts.append(_mask_segment(text[last:], context))
    return "".join(parts)


def _redact_cn_credentials(text: str) -> str:
    """Replace only the value of "密码是Huawei@123"-style assignments."""

    matches = list(iter_cn_secret_assignments(text))
    if not matches:
        return text
    parts: list[str] = []
    last = 0
    for match in matches:
        parts.append(text[last:match.start(1)])
        parts.append("<REDACTED_CREDENTIAL>")
        last = match.end(1)
    parts.append(text[last:])
    return "".join(parts)


def sanitize_output(
    value: Any,
    *,
    tenant_id: str,
    task_id: str,
    vault: ScopedTokenVault,
    pii_context: str = "",
) -> Any:
    if isinstance(value, str):
        clean = _DANGEROUS_HTML.sub("", value)
        clean = _DANGEROUS_URL.sub("blocked:", clean)
        # Model output is untrusted too. A provider must not be able to echo a
        # credential/private key into the operator UI or a downstream audit
        # payload, even if the secret was introduced by a tool or a provider
        # error rather than the original user message.
        clean = PRIVATE_KEY_RE.sub("<REDACTED_PRIVATE_KEY>", clean)
        def redact_credential(match: re.Match[str]) -> str:
            if is_redacted_assignment_match(match):
                return match.group(0)
            # A provider may quote an opaque or fake token as ``token X``.
            # Preserve it so exact-token resolution remains observable and
            # never turn an unknown token into a misleading redaction.
            value = match.group(1) if match.lastindex else ""
            if TOKEN_RE.fullmatch(value or ""):
                return match.group(0)
            return "<REDACTED_CREDENTIAL>"

        clean = SECRET_ASSIGNMENT_RE.sub(redact_credential, clean)
        clean = _redact_cn_credentials(clean)
        clean = sanitize_text(clean)
        # Numbers the model generated are masked before token resolution, so
        # an identity-card number the user supplied (restored from its token)
        # is shown as the user wrote it.
        clean = mask_personal_info(clean, prefix=pii_context)
        # Resolve only exact, scoped tokens. Unknown/fake tokens remain visible
        # as literal text and are never guessed or fuzzy-matched.
        return vault.resolve_text(clean, tenant_id=tenant_id, task_id=task_id)
    if isinstance(value, list):
        return [sanitize_output(item, tenant_id=tenant_id, task_id=task_id, vault=vault) for item in value]
    if isinstance(value, dict):
        return {str(k): sanitize_output(v, tenant_id=tenant_id, task_id=task_id, vault=vault) for k, v in value.items()}
    return value


def _possible_token_start(text: str, *, start_at: int = 0) -> int | None:
    """Find an incomplete token or a partial token opener at the end of text."""

    token_start = text.rfind(_TOKEN_OPEN, start_at)
    if token_start >= 0:
        return token_start

    # A provider may split even the ``[[NXA_`` opener across chunks. Keep the
    # longest suffix that could still become an opener, and emit everything
    # before it immediately.
    max_prefix = min(len(text), len(_TOKEN_OPEN) - 1)
    for size in range(max_prefix, 0, -1):
        if text.endswith(_TOKEN_OPEN[:size]):
            return len(text) - size
    return None


def _possible_number_start(text: str, *, start_at: int = 0) -> int | None:
    """Hold a trailing digit run that may continue in the next chunk.

    An identity-card or bank-card number split across two provider chunks
    would otherwise reach the UI half unmasked.  Only a short run made of
    digits / X / spaces / hyphens / + is held, starting at its first digit or
    ``+`` (at most the last 32 characters).
    """

    match = _NUMBER_TAIL_RE.search(text, pos=max(0, start_at))
    if not match or not any(char.isdigit() for char in match.group(0)):
        return None
    begin = max(match.start(), len(text) - _NUMBER_HOLD_MAX)
    for index in range(begin, len(text)):
        if text[index].isdigit() or text[index] == "+":
            return index
    return None


def _possible_credential_start(
    text: str,
    *,
    start_at: int = 0,
) -> int | None:
    """Find a credential directive that may continue in the next chunk.

    The complete assignment regex is used for the final replacement.  This
    companion check retains the current line after a credential keyword until
    a line break or stream end, so a provider cannot emit a long password
    value in several chunks before DLP sees the complete assignment.
    """

    candidate: int | None = None
    for keyword in _CREDENTIAL_KEYWORD_RE.finditer(text, pos=max(0, start_at)):
        # A completed line is safe to emit because ``_emit`` scans the whole
        # line.  A keyword in the final, unterminated line must remain pending
        # regardless of whether the assignment regex can already see part of
        # its value; provider chunks may split that value at any character.
        if not re.search(r"[\r\n]", text[keyword.end():]):
            candidate = keyword.start()
            break

    # Also retain a split keyword such as ``pass`` + ``word``.  The longest
    # possible prefix wins, while the complete-keyword branch above handles a
    # keyword that is already present but has not received its value yet.
    lower_text = text.casefold()
    max_prefix = min(len(text), max(len(item) for item in _CREDENTIAL_PREFIXES) - 1)
    for size in range(max_prefix, 0, -1):
        suffix = lower_text[-size:]
        if any(item.startswith(suffix) for item in _CREDENTIAL_PREFIXES):
            prefix_start = len(text) - size
            # A partial keyword is only meaningful at a word boundary.  Do
            # not hold the final ``k`` in an ordinary word such as
            # ``stream-ok`` merely because ``key-string`` is an allowed
            # credential keyword; doing so splits harmless provider chunks
            # and makes the streaming contract nondeterministic.
            at_word_boundary = (
                prefix_start == 0
                or not text[prefix_start - 1].isalnum()
            )
            if prefix_start >= start_at and at_word_boundary:
                candidate = min(candidate, prefix_start) if candidate is not None else prefix_start
            break

    # Chinese keywords ("密码是Huawei@123"): hold from the keyword while what
    # follows can still be the operator and an ASCII value.  The first
    # Chinese (non-ASCII) character after the value releases the hold.
    for keyword in _ZH_CREDENTIAL_KEYWORD_RE.finditer(text, pos=max(0, start_at)):
        if _ZH_ASSIGNMENT_TAIL_RE.fullmatch(text, keyword.end()):
            candidate = min(candidate, keyword.start()) if candidate is not None else keyword.start()
            break
    # A Chinese keyword split across chunks ("密" + "码是...").
    for prefix in _ZH_CREDENTIAL_PREFIXES:
        if text.endswith(prefix):
            prefix_start = len(text) - len(prefix)
            if prefix_start >= start_at:
                candidate = min(candidate, prefix_start) if candidate is not None else prefix_start
            break
    return candidate


class StreamingOutputResolver:
    """Sanitize and resolve provider output without breaking split tokens.

    Provider streaming chunks are not guaranteed to align with a token
    boundary. The resolver holds only a possible trailing token fragment;
    normal answer text is emitted as soon as it is safe to do so.
    """

    def __init__(self, *, tenant_id: str, task_id: str, vault: ScopedTokenVault):
        self.tenant_id = tenant_id
        self.task_id = task_id
        self.vault = vault
        self._pending = ""
        # Last raw characters already emitted: a phone/card keyword in an
        # earlier chunk still qualifies a number in this one.
        self._tail = ""

    def _emit(self, value: str) -> str:
        resolved = sanitize_output(
            value,
            tenant_id=self.tenant_id,
            task_id=self.task_id,
            vault=self.vault,
            pii_context=self._tail,
        )
        self._tail = (self._tail + value)[-_PII_CONTEXT_CHARS:]
        return resolved if isinstance(resolved, str) else str(resolved)

    def push(self, value: Any) -> str:
        self._pending += str(value or "")
        if not self._pending:
            return ""

        complete_matches = list(TOKEN_RE.finditer(self._pending))
        last_complete_end = complete_matches[-1].end() if complete_matches else 0
        incomplete_start = _possible_token_start(self._pending, start_at=last_complete_end)
        credential_start = _possible_credential_start(
            self._pending,
            start_at=last_complete_end,
        )
        number_start = _possible_number_start(self._pending, start_at=last_complete_end)
        safe_cut = incomplete_start if incomplete_start is not None else len(self._pending)
        if credential_start is not None:
            safe_cut = min(safe_cut, credential_start)
        if number_start is not None:
            safe_cut = min(safe_cut, number_start)
        if safe_cut <= 0:
            return ""

        safe_text = self._pending[:safe_cut]
        self._pending = self._pending[safe_cut:]
        return self._emit(safe_text)

    def flush(self) -> str:
        if not self._pending:
            return ""
        pending = self._pending
        self._pending = ""
        return self._emit(pending)
