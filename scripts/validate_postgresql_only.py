#!/usr/bin/env python3
"""Enforce the PostgreSQL-only runtime and test policy.

The temporary baseline mode exists only to freeze pre-existing cleanup debt.
New violations always fail.  Once the cleanup reaches zero, CI must invoke
this script without ``--baseline`` and the baseline file must be removed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "backend", ROOT / "scripts", ROOT / "tests")
SELF = Path(__file__).resolve()


def _joined(*parts: str) -> str:
    """Build forbidden words without making this policy scanner self-match."""

    return "".join(parts)


RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "sqlite-import",
        re.compile(rf"^\s*(?:import|from)\s+{_joined('sqlite', '3')}\b"),
        "SQLite driver imports are forbidden",
    ),
    (
        "sqlite-api",
        re.compile(rf"\b{_joined('sqlite', '3')}\."),
        "SQLite driver API calls are forbidden",
    ),
    (
        "sqlite-catalog",
        re.compile(rf"\b{_joined('sqlite', '_master')}\b", re.IGNORECASE),
        "SQLite catalog queries are forbidden",
    ),
    (
        "sqlite-pragma",
        re.compile(
            rf"\b(?:execute|executemany)\s*\([^\n]*[\"'][^\"']*"
            rf"\b{_joined('PRA', 'GMA')}\b",
            re.IGNORECASE,
        ),
        "SQLite PRAGMA statements are forbidden",
    ),
    (
        "sqlite-memory",
        re.compile(re.escape(_joined(":mem", "ory:")), re.IGNORECASE),
        "SQLite in-memory databases are forbidden",
    ),
    (
        "sqlite-url",
        re.compile(rf"\b{_joined('sqlite', '')}(?:\+[a-z0-9_]+)?://", re.IGNORECASE),
        "SQLite database URLs are forbidden",
    ),
    (
        "sqlite-autoincrement",
        re.compile(rf"\b{_joined('AUTO', 'INCREMENT')}\b", re.IGNORECASE),
        "SQLite AUTOINCREMENT syntax is forbidden",
    ),
    (
        "sqlite-db-path",
        re.compile(r"\bDB_PATH\b"),
        "File-database DB_PATH fallback is forbidden",
    ),
    (
        "force-non-pg",
        re.compile(r"(?:_USE_PG\s*=\s*False|use_pg\s*=\s*False)"),
        "Forcing a non-PostgreSQL code path is forbidden",
    ),
    (
        "clear-database-url",
        re.compile(
            r"(?:setenv\(\s*['\"]DATABASE_URL['\"]\s*,\s*['\"]['\"]|"
            r"environ\s*\[\s*['\"]DATABASE_URL['\"]\s*\]\s*=\s*['\"]['\"])"
        ),
        "Clearing DATABASE_URL to trigger a fallback is forbidden",
    ),
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str
    source: str
    occurrence: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.path, self.rule, self.source, self.occurrence)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for scan_root in SCAN_ROOTS:
        if not scan_root.exists():
            continue
        files.extend(
            path
            for path in scan_root.rglob("*.py")
            if path.resolve() != SELF and "__pycache__" not in path.parts
        )
    return sorted(set(files))


def scan() -> list[Violation]:
    violations: list[Violation] = []
    occurrences: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for path in _python_files():
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            source = " ".join(raw_line.strip().split())
            for rule, pattern, message in RULES:
                if not pattern.search(raw_line):
                    continue
                occurrence_key = (relative, rule, source)
                occurrence = occurrences[occurrence_key]
                occurrences[occurrence_key] += 1
                violations.append(
                    Violation(
                        path=relative,
                        line=line_number,
                        rule=rule,
                        message=message,
                        source=source,
                        occurrence=occurrence,
                    )
                )
    return violations


def _load_baseline(path: Path) -> list[Violation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("policy") != "postgresql-only":
        raise ValueError(f"Invalid PostgreSQL-only baseline: {path}")
    return [Violation(**item) for item in payload.get("violations", [])]


def _write_baseline(path: Path, violations: list[Violation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "policy": "postgresql-only",
        "temporary": True,
        "removal_condition": "Delete this file when violations reach zero",
        "violations": [asdict(item) for item in violations],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_summary(violations: list[Violation], *, title: str) -> None:
    print(f"{title}: {len(violations)} violation(s)")
    by_rule = Counter(item.rule for item in violations)
    for rule, count in sorted(by_rule.items()):
        print(f"  {rule}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="Temporary known-debt baseline")
    parser.add_argument("--update-baseline", type=Path, help="Write the current debt baseline")
    parser.add_argument("--list", action="store_true", help="Print every current violation")
    args = parser.parse_args()

    current = scan()
    if args.update_baseline:
        target = args.update_baseline
        if not target.is_absolute():
            target = ROOT / target
        _write_baseline(target, current)
        _print_summary(current, title=f"Baseline written to {target.relative_to(ROOT)}")
        return 0

    if args.list:
        for item in current:
            print(f"{item.path}:{item.line}: [{item.rule}] {item.message}: {item.source}")

    if args.baseline:
        baseline_path = args.baseline
        if not baseline_path.is_absolute():
            baseline_path = ROOT / baseline_path
        baseline = _load_baseline(baseline_path)
        baseline_keys = {item.key for item in baseline}
        current_keys = {item.key for item in current}
        new = [item for item in current if item.key not in baseline_keys]
        removed = baseline_keys - current_keys
        _print_summary(current, title="Current PostgreSQL-only debt")
        print(f"Baseline debt: {len(baseline)}; removed: {len(removed)}; new: {len(new)}")
        if new:
            for item in new:
                print(f"NEW {item.path}:{item.line}: [{item.rule}] {item.source}")
            return 1
        print("PASS: no new SQLite violations; temporary debt did not increase")
        return 0

    _print_summary(current, title="PostgreSQL-only policy")
    if current:
        print("FAIL: remove all violations or use the temporary tracked baseline during cleanup")
        return 1
    print("PASS: active Python runtime and tests are PostgreSQL-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
