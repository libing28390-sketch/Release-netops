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


def _field_value(row: Mapping[str, Any], prefix: str, field: str) -> Any:
    nested = row.get(prefix)
    if isinstance(nested, Mapping):
        return nested.get(field)
    return row.get(f"{prefix}_{field}")


def _exact_field_accuracy(cases: Iterable[Mapping[str, Any]], field: str) -> float:
    rows = list(cases)
    if not rows:
        return 0.0
    matched = 0
    for row in rows:
        expected = _field_value(row, "expected", field)
        predicted = _field_value(row, "predicted", field)
        matched += int(normalize_entity_value(expected) == normalize_entity_value(predicted))
    return matched / len(rows)


def product_match_accuracy(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return exact product identity accuracy after entity normalization."""

    return _exact_field_accuracy(cases, "product")


def os_match_accuracy(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return exact OS family/train identity accuracy after normalization."""

    return _exact_field_accuracy(cases, "os")


def version_match_accuracy(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return version-state accuracy with exact-release protection.

    ``expected_version_relation`` and ``predicted_version_relation`` must agree.
    An ``exact`` relation additionally requires normalized release equality;
    unspecified/conflict/unknown relations must not invent a release value.
    """

    rows = list(cases)
    if not rows:
        return 0.0
    matched = 0
    for row in rows:
        expected_relation = row.get("expected_version_relation")
        predicted_relation = row.get("predicted_version_relation")
        if expected_relation is None:
            expected_relation = _field_value(row, "expected", "version_relation")
        if predicted_relation is None:
            predicted_relation = _field_value(row, "predicted", "version_relation")
        if normalize_entity_value(expected_relation) != normalize_entity_value(predicted_relation):
            continue
        if normalize_entity_value(expected_relation) == "exact":
            expected_release = row.get("expected_version", _field_value(row, "expected", "version"))
            predicted_release = row.get("predicted_version", _field_value(row, "predicted", "version"))
            if normalize_entity_value(expected_release) != normalize_entity_value(predicted_release):
                continue
        elif normalize_entity_value(_field_value(row, "predicted", "version")) is not None:
            continue
        matched += 1
    return matched / len(rows)


def wrong_vendor_rate(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return the fraction of cases where the predicted vendor is wrong/guessed."""

    rows = list(cases)
    if not rows:
        return 0.0
    wrong = 0
    for row in rows:
        expected = _field_value(row, "expected", "vendor")
        predicted = _field_value(row, "predicted", "vendor")
        expected_norm = normalize_entity_value(expected)
        predicted_norm = normalize_entity_value(predicted)
        if (expected_norm is None and predicted_norm is not None) or (
            expected_norm is not None and predicted_norm is not None and expected_norm != predicted_norm
        ):
            wrong += 1
    return wrong / len(rows)


def _citations(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("citations") or row.get("citation_ids") or ()
    values: list[Any] = []
    for item in raw:
        if isinstance(item, Mapping):
            values.append(item.get("document_id", item.get("id")))
        else:
            values.append(item)
    return _unique_ids(values)


def official_source_rate(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return the fraction of cases whose answer citations are official."""

    rows = list(cases)
    if not rows:
        return 0.0
    passed = 0
    for row in rows:
        citations = row.get("citations") or ()
        outcome = normalize_entity_value(row.get("expected_outcome"))
        if outcome == "answer" and not citations:
            continue
        if all(isinstance(item, Mapping) and item.get("official") is True for item in citations):
            passed += 1
    return passed / len(rows)


def citation_accuracy(cases: Iterable[Mapping[str, Any]]) -> float:
    """Return strict per-case citation correctness against Gold IDs."""

    rows = list(cases)
    if not rows:
        return 0.0
    passed = 0
    for row in rows:
        outcome = normalize_entity_value(row.get("expected_outcome"))
        citations = set(_citations(row))
        gold = set(_unique_ids(row.get("gold_ids", row.get("gold_document_ids", ())) or ()))
        if outcome == "answer":
            passed += int(bool(citations) and citations.issubset(gold) and bool(citations & gold))
        else:
            passed += int(not citations)
    return passed / len(rows)


def evaluate_quality_cases(cases: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
    """Return the six EVAL-006 quality metrics as macro case rates."""

    rows = list(cases)
    return {
        "case_count": len(rows),
        "product_match": product_match_accuracy(rows),
        "os_match": os_match_accuracy(rows),
        "version_match": version_match_accuracy(rows),
        "wrong_vendor_rate": wrong_vendor_rate(rows),
        "official_source_rate": official_source_rate(rows),
        "citation_accuracy": citation_accuracy(rows),
    }
