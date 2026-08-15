"""LibreNMS Full MIB Repository Synchronizer and Parser (CLI Wrapper)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend path is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.librenms_mib_service import (  # noqa: F401
    TARGET_DIR,
    MIBS_DIR,
    LIBRENMS_REPO_URL,
    SYMBOL_INDEX_MAX_PASSES,
    VENDOR_DIR_MAP,
    normalize_vendor_from_dir,
    fetch_librenms_mibs,
    read_mib_text,
    extract_oid_definitions,
    resolve_indexed_oid,
    build_symbol_index,
    import_mibs_from_directory,
    logger,
)


def main():
    parser = argparse.ArgumentParser(description="Synchronize and import LibreNMS full MIB library into Nexora.")
    parser.add_argument("--fetch", action="store_true", default=True, help="Clone/pull from GitHub")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false", help="Do not fetch from GitHub, use local files")
    parser.add_argument("--vendors", nargs="+", help="Only import specific vendor directories (e.g. cisco huawei h3c rfc)")
    parser.add_argument("--max-files", type=int, default=None, help="Limit maximum number of MIB files to import")
    parser.add_argument("--dir", type=str, default=str(MIBS_DIR), help="Custom MIB directory path")

    args = parser.parse_args()
    mibs_path = Path(args.dir)

    if args.fetch:
        success = fetch_librenms_mibs(TARGET_DIR)
        if not success and not mibs_path.exists():
            logger.error("Could not fetch MIBs and local directory does not exist.")
            sys.exit(1)

    result = import_mibs_from_directory(
        mibs_dir=mibs_path,
        target_vendors=args.vendors,
        max_files=args.max_files,
    )
    print(f"\nResult: {result}")


if __name__ == "__main__":
    main()
