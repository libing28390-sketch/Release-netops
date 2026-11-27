#!/usr/bin/env python3
"""Read-only impact check for the batch 6 AI guardrails.

Scans stored knowledge chunks and prompt templates with the same detectors
the security gateway uses and reports how many rows each rule affects:

``zh_credential``     Chinese credential assignment such as "缺省密码为Admin@123".
                      Informational: the gateway replaces the value with
                      <REDACTED> and the request continues, so the model never
                      sees it.  Worth cleaning up, but nothing is blocked.
``prompt_injection``  Chinese/English injection phrasing.  Marked untrusted
                      (L3, minimized) -- not blocked.  In a prompt template it
                      would mark every request of that scene, so it is REVIEW.
``cn_id_card``        Resident identity numbers -- tokenized per request.
``bank_card``         Bank-card numbers -- tokenized per request.

    python scripts/ai_guardrail_impact_check.py
    python scripts/ai_guardrail_impact_check.py --limit 20000

Status is REVIEW (exit code 1) only when a prompt table has a
prompt_injection hit; otherwise PASS (exit code 0).
The report contains counts and row ids only -- never any matched text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

BATCH_SIZE = 500
MAX_IDS = 50
CATEGORIES = ("zh_credential", "prompt_injection", "cn_id_card", "bank_card")

# table -> (id column, text columns)
TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ai_document_chunk", "id", ("content",)),
    ("ai_prompt", "id", ("system_prompt", "user_prompt_template")),
    ("ai_prompt_version", "id", ("system_prompt", "user_prompt_template")),
)
PROMPT_TABLES = frozenset({"ai_prompt", "ai_prompt_version"})


def _detectors() -> dict[str, Callable[[str], bool]]:
    from ai.security.classification import (
        find_cn_personal_info,
        iter_cn_secret_assignments,
        iter_prompt_injection,
    )

    def has_category(category: str) -> Callable[[str], bool]:
        return lambda text: any(item.category == category for item in find_cn_personal_info(text))

    return {
        "zh_credential": lambda text: next(iter(iter_cn_secret_assignments(text)), None) is not None,
        "prompt_injection": lambda text: next(iter(iter_prompt_injection(text)), None) is not None,
        "cn_id_card": has_category("cn_id_card"),
        "bank_card": has_category("bank_card"),
    }


def _table_exists(conn: Any, table: str, columns: Iterable[str]) -> bool:
    try:
        conn.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE 1 = 0").fetchall()
        return True
    except Exception:  # missing table/column: report as skipped, never fail
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def scan_table(conn: Any, table: str, id_column: str, text_columns: tuple[str, ...], *, limit: int | None, detectors: dict[str, Callable[[str], bool]]) -> dict[str, Any]:
    columns = (id_column, *text_columns)
    if not _table_exists(conn, table, columns):
        return {"skipped": True, "rows": 0}
    stats: dict[str, Any] = {"skipped": False, "rows": 0}
    for category in CATEGORIES:
        stats[category] = {"count": 0, "ids": []}
    offset = 0
    while limit is None or offset < limit:
        size = BATCH_SIZE if limit is None else min(BATCH_SIZE, limit - offset)
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY {id_column} LIMIT ? OFFSET ?",
            (size, offset),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            stats["rows"] += 1
            row_id = str(row[0])
            text = "\n".join(str(row[index] or "") for index in range(1, len(columns)))
            for category, detect in detectors.items():
                if text and detect(text):
                    entry = stats[category]
                    entry["count"] += 1
                    if len(entry["ids"]) < MAX_IDS:
                        entry["ids"].append(row_id)
        offset += len(rows)
        if len(rows) < size:
            break
    return stats


def run(*, limit: int | None = None, conn: Any = None) -> dict[str, Any]:
    detectors = _detectors()
    report: dict[str, Any] = {"limit": limit, "tables": {}}

    def _scan(connection: Any) -> None:
        for table, id_column, text_columns in TARGETS:
            report["tables"][table] = scan_table(connection, table, id_column, text_columns, limit=limit, detectors=detectors)

    if conn is not None:
        _scan(conn)
    else:
        import database.core as database_core

        with database_core.get_db_connection() as connection:
            _scan(connection)

    reasons: list[str] = []
    for table, stats in report["tables"].items():
        if stats.get("skipped"):
            continue
        if table in PROMPT_TABLES and stats["prompt_injection"]["count"]:
            reasons.append(f"{table}.prompt_injection")
    report["status"] = "REVIEW" if reasons else "PASS"
    report["review_reasons"] = reasons
    # How each category is handled at request time (no category blocks).
    report["handling"] = {
        "zh_credential": "redacted",
        "prompt_injection": "marked_untrusted",
        "cn_id_card": "tokenized",
        "bank_card": "tokenized",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="scan at most N rows per table")
    args = parser.parse_args(argv)
    limit = args.limit if args.limit is None or args.limit > 0 else None
    report = run(limit=limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
