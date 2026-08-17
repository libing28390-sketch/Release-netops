"""Deterministic offline retrieval and entity-resolution metrics for KB V2.

The functions in this module are deliberately independent of PostgreSQL, SQLite,
network clients and application state.  Database-backed evaluation harnesses may
feed them rows from PostgreSQL, but this module never opens a database itself.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from statistics import fmean
from typing import Any


DEFAULT_KS: tuple[int, ...] = (1, 3, 5)


def _validate_k(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    return k


def _normalise_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique_ids(values: Iterable[Any] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or ():
        item = _normalise_id(value)
        if item is not None and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _top_k(ranked_ids: Iterable[Any] | None, k: int) -> list[str]:
    return _unique_ids(ranked_ids)[: _validate_k(k)]


def _no_match_score(ranked_ids: Iterable[Any] | None, k: int) -> float:
    return 1.0 if not _top_k(ranked_ids, k) else 0.0


def recall_at_k(ranked_ids: Iterable[Any] | None, gold_ids: Iterable[Any] | None, k: int) -> float:
    """Return binary-relevance Recall@K with an explicit no-match convention.

    For a no-match case (empty Gold), an empty top-K is a correct result (1.0)
    and any returned document is incorrect (0.0).  For normal cases the score
    is ``|topK ∩ Gold| / |Gold|``; duplicate ranked IDs count once.
    """

    top = _top_k(ranked_ids, k)
    gold = set(_unique_ids(gold_ids))
    if not gold:
        return _no_match_score(top, k)
    return len(set(top) & gold) / len(gold)


def precision_at_k(ranked_ids: Iterable[Any] | None, gold_ids: Iterable[Any] | None, k: int) -> float:
    """Return binary-relevance Precision@K using K as the denominator.

    Using K (rather than the number of returned rows) penalises an incomplete
    result list consistently.  Empty Gold uses the same fail-closed no-match
    convention as :func:`recall_at_k`.
    """

    k = _validate_k(k)
    top = _top_k(ranked_ids, k)
    gold = set(_unique_ids(gold_ids))
    if not gold:
        return _no_match_score(top, k)
    return len(set(top) & gold) / k


def mean_reciprocal_rank(ranked_ids: Iterable[Any] | None, gold_ids: Iterable[Any] | None) -> float:
    """Return reciprocal rank of the first relevant unique result.

    Empty Gold is scored 1.0 only when no result is returned; a guessed result
    scores 0.0.  This makes no-match behavior fail closed instead of silently
    rewarding arbitrary documents.
    """

    ranked = _unique_ids(ranked_ids)
    gold = set(_unique_ids(gold_ids))
    if not gold:
        return 1.0 if not ranked else 0.0
    for rank, document_id in enumerate(ranked, start=1):
        if document_id in gold:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Iterable[Any] | None, gold_ids: Iterable[Any] | None, k: int) -> float:
    """Return binary-relevance NDCG@K with deterministic duplicate handling."""

    k = _validate_k(k)
    top = _top_k(ranked_ids, k)
    gold = set(_unique_ids(gold_ids))
    if not gold:
        return _no_match_score(top, k)
    dcg = sum(
        (1.0 / math.log2(rank + 1))
        for rank, document_id in enumerate(top, start=1)
        if document_id in gold
    )
    ideal_hits = min(k, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evaluate_retrieval_cases(
    cases: Iterable[Mapping[str, Any]],
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, Any]:
    """Return macro retrieval metrics for mappings with ranked and Gold IDs."""

    normalised_ks = tuple(_validate_k(k) for k in ks)
    if len(set(normalised_ks)) != len(normalised_ks):
        raise ValueError("ks must not contain duplicates")
    rows = list(cases)
    if not rows:
        return {
            "case_count": 0,
            "recall_at_k": {str(k): 0.0 for k in normalised_ks},
            "precision_at_k": {str(k): 0.0 for k in normalised_ks},
            "mrr": 0.0,
            "ndcg_at_k": {str(k): 0.0 for k in normalised_ks},
        }

    def ranked(row: Mapping[str, Any]) -> Iterable[Any]:
        return row.get("ranked_ids", row.get("retrieved_ids", ())) or ()

    def gold(row: Mapping[str, Any]) -> Iterable[Any]:
        return row.get("gold_ids", row.get("gold_document_ids", ())) or ()

    return {
        "case_count": len(rows),
        "recall_at_k": {str(k): round(fmean(recall_at_k(ranked(row), gold(row), k) for row in rows), 6) for k in normalised_ks},
        "precision_at_k": {str(k): round(fmean(precision_at_k(ranked(row), gold(row), k) for row in rows), 6) for k in normalised_ks},
        "mrr": round(fmean(mean_reciprocal_rank(ranked(row), gold(row)) for row in rows), 6),
        "ndcg_at_k": {str(k): round(fmean(ndcg_at_k(ranked(row), gold(row), k) for row in rows), 6) for k in normalised_ks},
    }


def normalize_entity_value(value: Any) -> str | None:
    """Canonicalise a human/entity label for exact-resolution comparison."""

    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    if not text:
        return None
    text = re.sub(r"[-_/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None


def _entity_record_matches(expected: Mapping[str, Any], predicted: Mapping[str, Any]) -> bool:
    fields = set(expected) | set(predicted)
    if not fields:
        return True
    return all(normalize_entity_value(expected.get(field)) == normalize_entity_value(predicted.get(field)) for field in fields)


def entity_resolution_accuracy(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return exact per-query entity-resolution accuracy.

    Each mapping contains ``expected`` and ``predicted`` dictionaries.  Every
    expected and returned field must match after Unicode/case/separator
    normalisation; an unexpected predicted value for an unknown expected field
    is therefore counted as an incorrect guess.
    """

    rows = list(cases)
    if not rows:
        return 0.0
    matched = 0
    for row in rows:
        expected = row.get("expected") or {}
        predicted = row.get("predicted") or {}
        if not isinstance(expected, Mapping) or not isinstance(predicted, Mapping):
            raise TypeError("expected and predicted must be mappings")
        matched += int(_entity_record_matches(expected, predicted))
    return matched / len(rows)
