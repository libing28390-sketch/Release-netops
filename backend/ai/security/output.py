"""Treat model output as untrusted content before it reaches the UI."""

from __future__ import annotations

import html
import re
from typing import Any

from ai.security.classification import PRIVATE_KEY_RE, SECRET_ASSIGNMENT_RE
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import TOKEN_RE, ScopedTokenVault


_DANGEROUS_HTML = re.compile(r"(?is)<\s*(?P<tag>script|iframe|object|embed|form)\b[^>]*>.*?<\s*/\s*(?P=tag)\s*>")
_DANGEROUS_URL = re.compile(r"(?i)\b(?:javascript|data|vbscript):")
_TOKEN_OPEN = "[[NXA_"


def sanitize_output(value: Any, *, tenant_id: str, task_id: str, vault: ScopedTokenVault) -> Any:
    if isinstance(value, str):
        clean = _DANGEROUS_HTML.sub("", value)
        clean = _DANGEROUS_URL.sub("blocked:", clean)
        # Model output is untrusted too. A provider must not be able to echo a
        # credential/private key into the operator UI or a downstream audit
        # payload, even if the secret was introduced by a tool or a provider
        # error rather than the original user message.
        clean = PRIVATE_KEY_RE.sub("<REDACTED_PRIVATE_KEY>", clean)
        def redact_credential(match: re.Match[str]) -> str:
            # A provider may quote an opaque or fake token as ``token X``.
            # Preserve it so exact-token resolution remains observable and
            # never turn an unknown token into a misleading redaction.
            value = match.group(1) if match.lastindex else ""
            if TOKEN_RE.fullmatch(value or ""):
                return match.group(0)
            return "<REDACTED_CREDENTIAL>"

        clean = SECRET_ASSIGNMENT_RE.sub(redact_credential, clean)
        clean = sanitize_text(clean)
        # Resolve only exact, scoped tokens. Unknown/fake tokens remain visible
        # as literal text and are never guessed or fuzzy-matched.
        return vault.resolve_text(html.escape(clean, quote=False), tenant_id=tenant_id, task_id=task_id)
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

    def _emit(self, value: str) -> str:
        resolved = sanitize_output(
            value,
            tenant_id=self.tenant_id,
            task_id=self.task_id,
            vault=self.vault,
        )
        return resolved if isinstance(resolved, str) else str(resolved)

    def push(self, value: Any) -> str:
        self._pending += str(value or "")
        if not self._pending:
            return ""

        complete_matches = list(TOKEN_RE.finditer(self._pending))
        last_complete_end = complete_matches[-1].end() if complete_matches else 0
        incomplete_start = _possible_token_start(self._pending, start_at=last_complete_end)
        safe_cut = incomplete_start if incomplete_start is not None else len(self._pending)
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
