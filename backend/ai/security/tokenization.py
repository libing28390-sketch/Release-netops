"""Tenant/task scoped reversible tokenization for outbound AI payloads."""

from __future__ import annotations

import functools
import heapq
import hashlib
import hmac
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
        # (expires_at, key): expired entries are popped from the front instead
        # of scanning every entry on every put() (M12: O(n) per token).
        self._expiry_heap: list[tuple[float, tuple[str, str, str]]] = []
        self._raw_by_key: dict[tuple[str, str, str], tuple[str, str, str, str]] = {}
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
            key = (tenant, task, token)
            self._entries[key] = _VaultEntry(raw_value, now + self.ttl_seconds)
            self._reverse[reverse_key] = token
            self._raw_by_key[key] = reverse_key
            heapq.heappush(self._expiry_heap, (now + self.ttl_seconds, key))
            if len(self._entries) > self.max_entries:
                self.purge(now=now)
            return token

    def resolve_token(self, token: str, *, tenant_id: str, task_id: str) -> str | None:
        tenant, task = self._scope(tenant_id, task_id)
        with self._lock:
            entry = self._entries.get((tenant, task, token))
            if not entry:
                return None
            if entry.expires_at <= time.monotonic():
                self._drop((tenant, task, token))
                return None
            return entry.raw_value

    def resolve_text(self, text: str, *, tenant_id: str, task_id: str) -> str:
        def replace(match: re.Match[str]) -> str:
            return self.resolve_token(match.group(0), tenant_id=tenant_id, task_id=task_id) or match.group(0)

        return TOKEN_RE.sub(replace, text)

    def _drop(self, key: tuple[str, str, str]) -> None:
        self._entries.pop(key, None)
        reverse_key = self._raw_by_key.pop(key, None)
        if reverse_key is not None and self._reverse.get(reverse_key) == key[2]:
            self._reverse.pop(reverse_key, None)

    def purge(self, *, now: float | None = None) -> None:
        """Drop expired entries (amortised O(log n)), then enforce the cap."""
        now = now if now is not None else time.monotonic()
        heap = self._expiry_heap
        while heap and heap[0][0] <= now:
            expires_at, key = heapq.heappop(heap)
            entry = self._entries.get(key)
            # Stale heap items (entry replaced or already dropped) are skipped.
            if entry is not None and entry.expires_at == expires_at:
                self._drop(key)
        while len(self._entries) > self.max_entries and heap:
            _expires_at, key = heapq.heappop(heap)
            if key in self._entries:
                self._drop(key)
        # Bound the heap when many items went stale (clear_scope).
        if len(heap) > 2 * max(1, len(self._entries)) + 1024:
            self._expiry_heap = [(entry.expires_at, key) for key, entry in self._entries.items()]
            heapq.heapify(self._expiry_heap)

    def clear_scope(self, *, tenant_id: str, task_id: str) -> None:
        scope = self._scope(tenant_id, task_id)
        with self._lock:
            for key in [item for item in self._entries if item[:2] == scope]:
                self._drop(key)


# ── D2: exact-match tokenization of CMDB-managed device names ─────────────
# A device name only matches as a whole ASCII "word": it must not touch
# [A-Za-z0-9_.-] on the left, nor [A-Za-z0-9_-] / ".<alnum>" on the right
# (so "core" never matches inside "score", and "sw-core01" never matches
# inside "sw-core01.example.com", which HOST tokenizes as a whole).  Chinese
# characters and punctuation are boundaries: "交换机sw-core01的端口".
_DEVICE_LEFT_BOUNDARY = r"(?<![A-Za-z0-9_.-])"
_DEVICE_RIGHT_BOUNDARY = r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"
_DEVICE_RUN_RE = re.compile(r"[A-Za-z0-9_.-]+", re.ASCII)


@dataclass(frozen=True)
class _DeviceMatcher:
    names: frozenset[str]
    # Lower-cased names made only of [A-Za-z0-9_.-]: looked up per word run
    # so 20000 names do not become one 20000-way alternation per call.
    simple_lower: frozenset[str]
    # Names containing other characters (spaces, "/" ...), always tried.
    other_lower: tuple[str, ...]


_device_matcher: _DeviceMatcher | None = None
_device_matcher_lock = threading.Lock()


def _get_device_matcher(names: frozenset[str]) -> _DeviceMatcher:
    """Built once per device-name cache version (identity/equality check)."""
    global _device_matcher
    current = _device_matcher
    if current is not None and (current.names is names or current.names == names):
        return current
    with _device_matcher_lock:
        lowered = {name.lower() for name in names}
        simple = frozenset(name for name in lowered if _DEVICE_RUN_RE.fullmatch(name))
        other = tuple(sorted(lowered - simple))
        _device_matcher = _DeviceMatcher(names=names, simple_lower=simple, other_lower=other)
        return _device_matcher


@functools.lru_cache(maxsize=256)
def _device_name_pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    # Longest first so "sw-core01-mgmt" wins over "sw-core01".
    ordered = sorted(set(names), key=lambda name: (-len(name), name))
    alternation = "|".join(re.escape(name) for name in ordered)
    return re.compile(f"{_DEVICE_LEFT_BOUNDARY}(?:{alternation}){_DEVICE_RIGHT_BOUNDARY}", re.IGNORECASE | re.ASCII)


def _device_candidates(segment: str, simple_lower: frozenset[str]) -> set[str]:
    hits: set[str] = set()
    for run in _DEVICE_RUN_RE.findall(segment):
        lowered = run.lower()
        # A match starts at the run start and ends at the run end or before
        # one of its dots ("sw-core01." at the end of a sentence).
        if lowered in simple_lower:
            hits.add(lowered)
        for index, char in enumerate(lowered):
            if char == "." and index and lowered[:index] in simple_lower:
                hits.add(lowered[:index])
    return hits


def _tokenize_known_device_names(text: str, *, tenant_id: str, task_id: str, vault: ScopedTokenVault) -> str:
    from ai.security.known_identifiers import known_device_names

    names = known_device_names()
    if not names or not text:
        return text
    matcher = _get_device_matcher(names)

    def replace_segment(segment: str) -> str:
        if not segment:
            return segment
        candidates = _device_candidates(segment, matcher.simple_lower)
        lowered_segment = segment.lower()
        candidates.update(name for name in matcher.other_lower if name in lowered_segment)
        if not candidates:
            return segment
        pattern = _device_name_pattern(tuple(sorted(candidates)))
        return pattern.sub(
            lambda match: vault.put(match.group(0), kind="DEVICE", tenant_id=tenant_id, task_id=task_id),
            segment,
        )

    # Text inside existing [[NXA_...]] tokens is never re-tokenized.
    parts: list[str] = []
    last = 0
    for token in TOKEN_RE.finditer(text):
        parts.append(replace_segment(text[last:token.start()]))
        parts.append(token.group(0))
        last = token.end()
    parts.append(replace_segment(text[last:]))
    return "".join(parts)


def tokenize_text(text: str, *, tenant_id: str, task_id: str, vault: ScopedTokenVault) -> str:
    """Replace identifiers from most specific to least specific."""
    if not text:
        return text

    # Shared with classification/DLP so that whatever the final DLP check
    # would flag is exactly what gets tokenized here (batch 6).  The shared
    # patterns use ASCII word boundaries: "地址10.1.1.1" and "电话138..." are
    # tokenized even when the value touches a Chinese character.
    from ai.security.classification import (
        BUSINESS_NAME_RE,
        EMAIL_RE,
        IPV4_RE,
        IPV6_RE,
        MAC_RE,
        PHONE_RE,
        SITE_NAME_RE,
        find_cn_personal_info,
    )

    # Identity-card and bank-card numbers first: the generic phone pattern
    # would otherwise take only part of an ID ending in "X" or of a grouped
    # 19-digit card number.
    result = text
    personal = find_cn_personal_info(result)
    if personal:
        kinds = {"cn_id_card": "IDCARD", "bank_card": "BANKCARD"}
        parts: list[str] = []
        last = 0
        for item in personal:
            parts.append(result[last:item.start])
            parts.append(vault.put(item.value, kind=kinds.get(item.category, "VALUE"), tenant_id=tenant_id, task_id=task_id))
            last = item.end
        parts.append(result[last:])
        result = "".join(parts)

    before_devices: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("EMAIL", EMAIL_RE),
        ("IP", IPV4_RE),
        ("IPV6", IPV6_RE),
        ("MAC", MAC_RE),
        ("PHONE", PHONE_RE),
    )
    after_devices: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("HOST", re.compile(r"(?<![\w.-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?![\w.-])", re.ASCII)),
        ("SERIAL", re.compile(r"(?i)\b(?:serial(?:[-_ ]?number)?|sn)\s*[:=#-]?\s*[A-Z0-9][A-Z0-9._-]{5,31}\b", re.ASCII)),
        ("SITE", SITE_NAME_RE),
        ("BUSINESS", BUSINESS_NAME_RE),
    )
    for kind, pattern in before_devices:
        result = pattern.sub(
            lambda match: vault.put(match.group(0), kind=kind, tenant_id=tenant_id, task_id=task_id),
            result,
        )
    # D2: only CMDB-managed device names, exact match (no generic pattern).
    result = _tokenize_known_device_names(result, tenant_id=tenant_id, task_id=task_id, vault=vault)
    for kind, pattern in after_devices:
        result = pattern.sub(
            lambda match: vault.put(match.group(0), kind=kind, tenant_id=tenant_id, task_id=task_id),
            result,
        )
    return result


def opaque_user_id(user_id: str | None, *, tenant_id: str, task_id: str) -> str:
    """Stable owner key for Nexora's own tables (conversations, agents...).

    Unkeyed on purpose: existing rows are looked up by this value.  Never
    send it to a provider -- use :func:`provider_user_id` for that.
    """
    source = f"{tenant_id}:{task_id}:{user_id or 'anonymous'}".encode("utf-8")
    return "nxa_user_" + hashlib.sha256(source).hexdigest()[:32]


def _provider_id_key() -> bytes:
    salt = str(getattr(settings, "AI_HASH_SALT", "") or "")
    if len(salt) >= 16:
        return salt.encode("utf-8")
    # No dedicated salt: derive one from the master key material, so the
    # value is still keyed (an unkeyed sha256 of tenant:task:user can be
    # reversed with a dictionary of usernames, M12).
    material = str(getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or getattr(settings, "SECRET_KEY", "") or "")
    return hmac.new(material.encode("utf-8"), b"nexora-provider-user-id-v1", hashlib.sha256).digest()


def provider_user_id(user_id: str | None, *, tenant_id: str, task_id: str) -> str:
    """Keyed, non-reversible identifier sent to AI providers (``user`` field)."""
    source = f"{tenant_id}:{task_id}:{user_id or 'anonymous'}".encode("utf-8")
    return "nxa_user_" + hmac.new(_provider_id_key(), source, hashlib.sha256).hexdigest()[:32]


token_vault = ScopedTokenVault()
