"""Migrate legacy PAM/config files into the configured StorageService.

Examples:
    python -m scripts.migrate_storage_objects --dry-run
    python -m scripts.migrate_storage_objects --limit 100
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

from services.storage_migration_service import migrate_legacy_storage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate_legacy_storage(limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("failed", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
