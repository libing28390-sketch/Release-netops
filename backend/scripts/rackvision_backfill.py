"""Audit or explicitly apply the RackVision legacy placement backfill.

Examples:

    python backend/scripts/rackvision_backfill.py --dry-run
    python backend/scripts/rackvision_backfill.py --dry-run --rack-id <rack-id> --json
    python backend/scripts/rackvision_backfill.py --apply --report-file reports/rackvision-backfill.json

The command never writes by default.  ``--apply`` still commits only after the
service completes; take the normal PostgreSQL backup and approval before using
it in an operational environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import database
from services.rack_data_backfill_service import run_backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RackVision dry-run-first legacy placement backfill")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only audit and print the proposed changes (default)")
    mode.add_argument("--apply", action="store_true", help="Apply safe conversions and persist quality issues")
    parser.add_argument("--rack-id", default="", help="Limit the run to one rack id")
    parser.add_argument("--json", action="store_true", help="Print the complete machine-readable report")
    parser.add_argument("--report-file", default="", help="Write the JSON report to this file")
    args = parser.parse_args(argv)

    # Startup schema initialization is explicit for this maintenance command,
    # never part of normal application boot-time data processing.
    database.init_db()
    conn = database.get_db_connection()
    try:
        report = run_backfill(
            conn,
            rack_id=args.rack_id,
            apply=bool(args.apply),
            commit=bool(args.apply),
        )
    finally:
        conn.close()

    if args.report_file:
        report_path = Path(args.report_file).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if args.json or args.report_file:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(
            f"RackVision backfill {report['mode']}: accepted={report['accepted']} "
            f"confirmed={report['confirmed']} estimated={report['estimated']} "
            f"unknown={report['unknown']} invalid={report['invalid']} issues={report['issue_count']}"
        )
        if report["issue_count"]:
            print("Use --json or --report-file to inspect the complete issue details.")
    return 0 if report["invalid"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
