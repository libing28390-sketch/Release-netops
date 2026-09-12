"""Tenant/task scoped reversible tokenization for outbound AI payloads."""

from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from core.config import settings


TOKEN_RE = re.compile(r"\[\[NXA_[A-Z0-9]+_[A-Za-z0-9_-]{16,}]]")


@dataclass
class _VaultEntry:
    raw_value: str
    expires_at: float


class ScopedTokenVault:
    """Ephemeral vault with exact, scope-bound lookups.

    The mapping is intentionally in memory.  A future Redis implementation may
    replace the storage methods, but it must retain the `(tenant, task)` scope
    and TTL semantics rather than persisting raw identifiers in the database.
    """

    def __init__(self, ttl_seconds: int | None = None, max_entries: int = 50_000):
        # Keep tests and emergency short-lived scopes useful while enforcing
        # the production upper bound required by the security plan.
        self.ttl_seconds = max(1, min(int(ttl_seconds or getattr(settings, "AI_SECURITY_VAULT_TTL_SECONDS", 3600)), 86400))
        self.max_entries = max_entries
        self._entries: dict[tuple[str, str, str], _VaultEntry] = {}
        self._reverse: dict[tuple[str, str, str, str], str] = {}
        self._lock = threading.RLock()

    def _scope(self, tenant_id: str, task_id: str) -> tuple[str, str]:
        return (str(tenant_id or "tenant-default"), str(task_id or "task-default"))

    def put(self, raw_value: str, *, kind: str, tenant_id: str, task_id: str) -> str:
        if not raw_value:
            return raw_value
        tenant, task = self._scope(tenant_id, task_id)
        kind_code = re.sub(r"[^A-Z0-9]", "", str(kind).upper())[:20] or "VALUE"
        now = time.monotonic()
        with self._lock:
            self.purge(now=now)
            reverse_key = (tenant, task, kind_code, raw_value)
            existing = self._reverse.get(reverse_key)
            if existing and (tenant, task, existing) in self._entries:
                return existing
            # token_urlsafe has enough entropy for a tenant-wide collision
            # domain; keep generating until the scoped token is unique.
            while True:
                token = f"[[NXA_{kind_code}_{secrets.token_urlsafe(18)}]]"
                if (tenant, task, token) not in self._entries:
                    break
            self._entries[(tenant, task, token)] = _VaultEntry(raw_value, now + self.ttl_seconds)
            self._reverse[reverse_key] = token
            return token

    def resolve_token(self, token: str, *, tenant_id: str, task_id: str) -> str | None:
        tenant, task = self._scope(tenant_id, task_id)
        with self._lock:
            entry = self._entries.get((tenant, task, token))
            if not entry:
                return None
            if entry.expires_at <= time.monotonic():
                self._entries.pop((tenant, task, token), None)
                return None
            return entry.raw_value

    def resolve_text(self, text: str, *, tenant_id: str, task_id: str) -> str:
        def replace(match: re.Match[str]) -> str:
            return self.resolve_token(match.group(0), tenant_id=tenant_id, task_id=task_id) or match.group(0)

        return TOKEN_RE.sub(replace, text)

    def purge(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)
        if expired:
            expired_tokens = {key[2] for key in expired}
            for key, token in list(self._reverse.items()):
                if token in expired_tokens:
                    self._reverse.pop(key, None)
        if len(self._entries) > self.max_entries:
            for key in sorted(self._entries, key=lambda item: self._entries[item].expires_at)[: len(self._entries) - self.max_entries]:
                self._entries.pop(key, None)

    def clear_scope(self, *, tenant_id: str, task_id: str) -> None:
        scope = self._scope(tenant_id, task_id)
        with self._lock:
            tokens = {key[2] for key in self._entries if key[:2] == scope}
            for key in [item for item in self._entries if item[:2] == scope]:
                self._entries.pop(key, None)
            for key, token in list(self._reverse.items()):
                if token in tokens:
                    self._reverse.pop(key, None)


def tokenize_text(text: str, *, tenant_id: str, task_id: str, vault: ScopedTokenVault) -> str:
    """Replace identifiers from most specific to least specific."""
    if not text:
        return text

    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("EMAIL", re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")),
        ("IP", re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])")),
        ("IPV6", re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}(?![\w:])")),
        ("MAC", re.compile(r"(?i)(?<![\w])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w])")),
        ("PHONE", re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,18}\d)(?!\w)")),
        ("HOST", re.compile(r"(?<![\w.-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?![\w.-])")),
        ("SERIAL", re.compile(r"(?i)\b(?:serial(?:[-_ ]?number)?|sn)\s*[:=#-]?\s*[A-Z0-9][A-Z0-9._-]{5,31}\b")),
        ("SITE", re.compile(r"(?i)\b(?:site|机房|园区|站点)\s*[:=：]\s*[\u4e00-\u9fffA-Za-z0-9][^\r\n,;]{1,80}")),
        ("BUSINESS", re.compile(r"(?i)\b(?:customer|business|project|department|业务|客户|项目|部门)\s*[:=：]\s*[^\r\n,;]{1,80}")),
    )
    result = text
    for kind, pattern in patterns:
        result = pattern.sub(
            lambda match: vault.put(match.group(0), kind=kind, tenant_id=tenant_id, task_id=task_id),
            result,
        )
    return result


def opaque_user_id(user_id: str | None, *, tenant_id: str, task_id: str) -> str:
    """Create a stable, non-reversible provider identifier without PII."""
    import hashlib

    source = f"{tenant_id}:{task_id}:{user_id or 'anonymous'}".encode("utf-8")
    return "nxa_user_" + hashlib.sha256(source).hexdigest()[:32]


token_vault = ScopedTokenVault()
