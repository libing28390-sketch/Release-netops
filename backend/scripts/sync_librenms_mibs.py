"""LibreNMS Full MIB Repository Synchronizer and Parser (CLI Wrapper)."""

from __future__ import annotations

import argparse
import re
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
from services.librenms_rule_service import sync_rules_from_repository
from services.platform_registry_service import list_platform_vendor_names


def _vendor_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def main():
    parser = argparse.ArgumentParser(description="Synchronize LibreNMS MIBs for vendors registered in Nexora.")
    parser.add_argument("--fetch", action="store_true", default=True, help="Clone/pull from GitHub")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false", help="Do not fetch from GitHub, use local files")
    parser.add_argument("--vendors", nargs="+", help="Narrow to specific vendors already registered in the platform")
    parser.add_argument("--max-files", type=int, default=None, help="Limit maximum number of MIB files to import")
    parser.add_argument("--dir", type=str, default=str(MIBS_DIR), help="Custom MIB directory path")

    args = parser.parse_args()
    mibs_path = Path(args.dir)

    platform_vendors = list_platform_vendor_names()
    if not platform_vendors:
        parser.error("No platform vendors are registered for LibreNMS MIB synchronization")
    allowed_vendor_map = {_vendor_token(name): name for name in platform_vendors}
    allowed_vendor_map["standard"] = "Standard"
    for vendor_key, vendor_name in VENDOR_DIR_MAP.items():
        canonical_vendor = allowed_vendor_map.get(_vendor_token(vendor_name))
        if canonical_vendor:
            allowed_vendor_map[_vendor_token(vendor_key)] = canonical_vendor

    retire_out_of_scope = not bool(args.vendors)
    if args.vendors:
        unknown_vendors = [name for name in args.vendors if _vendor_token(name) not in allowed_vendor_map]
        if unknown_vendors:
            parser.error("Only registered platform vendors are allowed: " + ", ".join(unknown_vendors))
        target_vendors = list(dict.fromkeys(allowed_vendor_map[_vendor_token(name)] for name in args.vendors))
        if "standard" not in {_vendor_token(name) for name in target_vendors}:
            target_vendors.append("Standard")
    else:
        target_vendors = [*platform_vendors, "Standard"]

    if args.fetch:
        success = fetch_librenms_mibs(TARGET_DIR)
        if not success and not mibs_path.exists():
            logger.error("Could not fetch MIBs and local directory does not exist.")
            sys.exit(1)

    result = import_mibs_from_directory(
        mibs_dir=mibs_path,
        target_vendors=target_vendors,
        max_files=args.max_files,
        retire_out_of_scope=retire_out_of_scope,
    )
    result["platform_vendor_scope"] = target_vendors
    result["librenms_rules"] = sync_rules_from_repository(TARGET_DIR)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    main()
