"""Provider-independent token estimates.

Used when a provider does not report usage and to keep requests inside a
model's context window.  The numbers are deliberately rough: CJK text costs
about 0.6 tokens per character and other text about 0.3 for DeepSeek/OpenAI
style tokenizers.  A flat ``len // 3`` under-counts Chinese by about half.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Fixed per-message overhead for role markers and separators.
MESSAGE_OVERHEAD_TOKENS = 4


def _is_cjk(ch: str) -> bool:
    return "\u3000" <= ch <= "\u9fff" or "\uac00" <= ch <= "\ud7af" or "\uff00" <= ch <= "\uffef"


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    text = str(text)
    cjk = sum(1 for ch in text if _is_cjk(ch))
    return max(1, int(round(cjk * 0.6 + (len(text) - cjk) * 0.3)))


def estimate_message_tokens(message: Mapping[str, Any] | Any) -> int:
    if not isinstance(message, Mapping):
        return MESSAGE_OVERHEAD_TOKENS + estimate_tokens(str(message or ""))
    return MESSAGE_OVERHEAD_TOKENS + estimate_tokens(str(message.get("content") or ""))


def fit_history_to_budget(messages: Iterable[Mapping[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    """Return the newest contiguous tail of ``messages`` that fits the budget.

    Older turns are dropped first; the order of the kept messages is
    preserved.  A budget of zero or less keeps nothing.
    """
    items = [dict(item) for item in messages or [] if isinstance(item, Mapping)]
    budget = int(token_budget or 0)
    if budget <= 0 or not items:
        return []
    kept: list[dict[str, Any]] = []
    used = 0
    for item in reversed(items):
        cost = estimate_message_tokens(item)
        if used + cost > budget:
            break
        kept.append(item)
        used += cost
    kept.reverse()
    return kept
