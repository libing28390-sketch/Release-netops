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
