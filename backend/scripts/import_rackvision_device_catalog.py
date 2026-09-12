"""Import the generated RackVision network-device catalog into ``device_types``.

The default is a read-only preview.  Use ``--apply`` only after reviewing the
report; existing non-empty CMDB values are preserved and conflicts block the
whole import.  The source workbook is never read or modified by this command.

Examples::

    python backend/scripts/import_rackvision_device_catalog.py --json
    python backend/scripts/import_rackvision_device_catalog.py --apply --report-file reports/rackvision-catalog-import.json
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
from services.rack_catalog_import_service import import_device_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RackVision device catalog dry-run/apply import")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only preview changes (default)")
    mode.add_argument("--apply", action="store_true", help="Apply only a conflict-free catalog import")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("assets/catalog/network_devices.json"),
        help="Generated network_devices.json path",
    )
    parser.add_argument("--json", action="store_true", help="Print the complete JSON report")
    parser.add_argument("--report-file", type=Path, default=None, help="Write the JSON report to a file")
    args = parser.parse_args(argv)

    # Schema initialization and migration are explicit maintenance-command
    # actions, never application-startup data processing.
    database.init_db()
    conn = database.get_db_connection()
    try:
        report = import_device_catalog(
            conn,
            args.source,
            apply=bool(args.apply),
            commit=bool(args.apply),
        )
    finally:
        conn.close()

    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.report_file:
        report_path = args.report_file.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(encoded + "\n", encoding="utf-8")
    if args.json or args.report_file:
        print(encoded)
    else:
        summary = report["summary"]
        print(
            f"RackVision catalog {report['mode']}: rows={summary['catalog_rows']} "
            f"new={summary['new']} updated={summary['updated']} "
            f"unchanged={summary['unchanged']} conflicts={summary['conflicts']} "
            f"invalid={summary['invalid_rows']}"
        )
        if report.get("apply_blocked"):
            print(f"Apply blocked: {report['apply_block_reason']}")
    return 0 if not report.get("apply_blocked") and report["summary"]["invalid_rows"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

