"""LibreNMS Full MIB Repository Synchronizer and Parser Service.

Clones or pulls the official LibreNMS `mibs/` directory from GitHub
(https://github.com/librenms/librenms) using git sparse-checkout, then parses
all vendor MIB definition files into the Nexora SNMP MIB repository.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from database import get_db_connection
from services.snmp_mib_service import STANDARD_ROOT_OIDS, parse_and_store_mib
from services.mib_repository_service import (
    LIBRENMS_SOURCE_ID,
    PARSER_VERSION,
    git_commit,
    iter_mib_files,
    new_id,
    relative_mib_path,
    sha256_file,
    utc_now,
    vendor_key_from_relative_path,
    vendor_name_from_key,
    write_manifest,
)

logger = logging.getLogger("librenms_mib_service")

BACKEND_DIR = Path(__file__).resolve().parent.parent
LIBRENMS_REPO_URL = "https://github.com/librenms/librenms.git"
TARGET_DIR = BACKEND_DIR / "data" / "librenms_repo"
MIBS_DIR = TARGET_DIR / "mibs"
SYMBOL_INDEX_MAX_PASSES = 8

# Vendor folder name normalizer
VENDOR_DIR_MAP: dict[str, str] = {
    "cisco": "Cisco",
    "huawei": "Huawei",
    "h3c": "H3C",
    "comware": "H3C",
    "juniper": "Juniper",
    "arista": "Arista",
    "ruijie": "Ruijie",
    "fortinet": "Fortinet",
    "mikrotik": "MikroTik",
    "paloalto": "Palo Alto",
    "dell": "Dell",
    "hp": "HP",
    "hpe": "HPE",
    "aruba": "Aruba",
    "arubaos-cx": "Aruba",
    "f5": "F5",
    "checkpoint": "Check Point",
    "zte": "ZTE",
    "dlink": "D-Link",
    "zyxel": "Zyxel",
    "netgear": "Netgear",
    "rad": "RAD",
    "synology": "Synology",
    "qnap": "QNAP",
    "rfc": "Standard",
    "net-snmp": "Standard",
    "iana": "Standard",
    "ietf": "Standard",
}


def normalize_vendor_from_dir(dir_name: str) -> str:
    key = dir_name.lower().strip()
    if key in VENDOR_DIR_MAP:
        return VENDOR_DIR_MAP[key]
    return dir_name.capitalize()


def fetch_librenms_mibs(target_dir: Path = TARGET_DIR) -> bool:
    """Clone or pull only the `mibs/` directory from LibreNMS repository using sparse checkout."""
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    mibs_path = target_dir / "mibs"

    if (target_dir / ".git").exists():
        logger.info("Existing LibreNMS repository found at %s. Pulling latest updates...", target_dir)
        try:
            subprocess.run(["git", "pull", "--depth", "1"], cwd=target_dir, check=True, capture_output=True, text=True)
            return True
        except Exception as exc:
            logger.warning("Git pull failed: %s; using existing local MIB files", exc)
            return mibs_path.exists()

    logger.info("Cloning LibreNMS repository (sparse checkout: mibs/ only) from %s...", LIBRENMS_REPO_URL)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=target_dir, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", LIBRENMS_REPO_URL], cwd=target_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "core.sparseCheckout", "true"], cwd=target_dir, check=True, capture_output=True)
        sparse_file = target_dir / ".git" / "info" / "sparse-checkout"
        sparse_file.parent.mkdir(parents=True, exist_ok=True)
        sparse_file.write_text("mibs/\n", encoding="utf-8")
        subprocess.run(["git", "pull", "--depth", "1", "origin", "master"], cwd=target_dir, check=True, capture_output=True, text=True)
        logger.info("Successfully fetched LibreNMS mibs directory to %s", mibs_path)
        return True
    except Exception as exc:
        logger.error("Failed to clone LibreNMS mibs directory: %s", exc)
        return False


def read_mib_text(file_path: Path) -> str:
    """Read a repository MIB using the common UTF-8/Latin-1 fallback."""
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return file_path.read_text(encoding="latin-1", errors="replace")


_INDEX_OID_DECLARATION_PATTERN = re.compile(
    r"\b([A-Za-z0-9_-]+)\s+"
    r"(MODULE-IDENTITY|OBJECT-IDENTITY|OBJECT\s+IDENTIFIER|OBJECT-TYPE|"
    r"NOTIFICATION-TYPE|MODULE-COMPLIANCE|OBJECT-GROUP|NOTIFICATION-GROUP)\b"
    r"[\s\S]*?::=\s*\{\s*([^}]+)\s*\}",
    re.I,
)


def extract_oid_definitions(raw_text: str) -> dict[str, str]:
    """Extract only symbol-to-parent declarations for the fast index pass."""
    lines = []
    for line in raw_text.splitlines():
        comment_idx = line.find("--")
        lines.append(line[:comment_idx] if comment_idx >= 0 else line)
    clean_text = "\n".join(lines)
    body_text = re.sub(r"\b(?:IMPORTS|EXPORTS)\b[\s\S]*?;", "", clean_text, flags=re.I)
    return {
        match.group(1): match.group(3).strip()
        for match in _INDEX_OID_DECLARATION_PATTERN.finditer(body_text)
    }


def resolve_indexed_oid(raw_oid: str, symbols: dict[str, str]) -> str:
    """Resolve the same simple ASN.1 OID forms supported by MibParser."""
    tokens = raw_oid.split()
    if not tokens:
        return ""
    if all(token.isdigit() for token in tokens):
        return ".".join(tokens)

    parent = tokens[0].split("(", 1)[0]
    base_oid = symbols.get(parent, "")
    if not base_oid:
        return ""
    sub_ids = []
    for token in tokens[1:]:
        sub_match = re.match(r"^(?:[A-Za-z0-9_-]+\()?([0-9]+)\)?$", token)
        if sub_match:
            sub_ids.append(sub_match.group(1))
    return f"{base_oid}.{'.'.join(sub_ids)}" if sub_ids else ""


def build_symbol_index(
    files: list[Path],
    mibs_dir: Path,
    max_passes: int = SYMBOL_INDEX_MAX_PASSES,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Build dependency symbols before persisting MIB nodes."""
    root_definitions: dict[str, str] = {}
    vendor_definitions: dict[str, dict[str, str]] = {}
    for file_path in files:
        try:
            raw_text = read_mib_text(file_path)
            if len(raw_text) < 20:
                continue
            definitions = extract_oid_definitions(raw_text)
        except Exception as exc:
            logger.debug("Could not read MIB for dependency index %s: %s", file_path.name, exc)
            continue
        relative_path = relative_mib_path(file_path, mibs_dir)
        vendor_key = vendor_key_from_relative_path(relative_path)
        target = root_definitions if "/" not in relative_path else vendor_definitions.setdefault(vendor_key, {})
        for name, raw_oid in definitions.items():
            target.setdefault(name, raw_oid)

    global_symbols = dict(STANDARD_ROOT_OIDS)
    symbols_by_vendor: dict[str, dict[str, str]] = {
        vendor_key: {} for vendor_key in vendor_definitions
    }
    pass_count = 0

    for pass_number in range(max(1, max_passes)):
        added = 0
        for name, raw_oid in root_definitions.items():
            if name not in global_symbols:
                oid = resolve_indexed_oid(raw_oid, global_symbols)
                if oid:
                    global_symbols[name] = oid
                    added += 1

        for vendor_key, definitions in vendor_definitions.items():
            vendor_symbols = symbols_by_vendor[vendor_key]
            scope_symbols = dict(global_symbols)
            scope_symbols.update(vendor_symbols)
            for name, raw_oid in definitions.items():
                if name in global_symbols or name in vendor_symbols:
                    continue
                oid = resolve_indexed_oid(raw_oid, scope_symbols)
                if oid:
                    vendor_symbols[name] = oid
                    scope_symbols[name] = oid
                    added += 1

        pass_count = pass_number + 1
        logger.info("MIB dependency index pass %d: %d new symbols", pass_count, added)
        if added == 0:
            break

    logger.info(
        "MIB dependency index ready after %d pass(es): %d shared symbols, %d vendor scopes",
        pass_count,
        len(global_symbols),
        len(symbols_by_vendor),
    )
    return global_symbols, symbols_by_vendor


def import_mibs_from_directory(
    mibs_dir: Path = MIBS_DIR,
    target_vendors: list[str] | None = None,
    max_files: int | None = None,
) -> dict[str, Any]:
    """Scan and parse a local LibreNMS snapshot into the MIB repository."""
    mibs_path = Path(mibs_dir).resolve()
    if not mibs_path.exists():
        logger.error("MIBs directory does not exist: %s", mibs_path)
        return {"success": False, "imported": 0, "errors": 1, "message": "MIBs directory not found"}

    start_time = time.time()
    now = utc_now()
    source_commit = git_commit(mibs_path.parent)
    source_id = LIBRENMS_SOURCE_ID
    target_vendors_set = {v.strip().lower() for v in target_vendors or [] if v.strip()} or None
    all_files = iter_mib_files(mibs_path)
    files = [
        path
        for path in all_files
        if not target_vendors_set
        or vendor_key_from_relative_path(relative_mib_path(path, mibs_path)) in target_vendors_set
        or vendor_name_from_key(vendor_key_from_relative_path(relative_mib_path(path, mibs_path))).lower() in target_vendors_set
    ]
    if max_files is not None:
        files = files[: max(0, max_files)]

    global_symbols, symbols_by_vendor = build_symbol_index(all_files, mibs_path)
    conn = get_db_connection()

    run_id = new_id("mib-run")
    manifest_entries: list[dict[str, Any]] = []
    seen_relative_paths: set[str] = set()
    deactivated_files = 0
    stats = {
        "total_files": len(files),
        "processed_files": 0,
        "imported_files": 0,
        "updated_files": 0,
        "skipped_files": 0,
        "failed_files": 0,
        "duplicate_files": 0,
        "zero_node_files": 0,
        "total_nodes": 0,
    }

    def _value(row, key: str, index: int = 0):
        if row is None:
            return None
        if isinstance(row, tuple):
            return row[index]
        return row[key]

    def _upsert_source() -> None:
        source_row = conn.execute("SELECT id FROM snmp_mib_sources WHERE id = ?", (source_id,)).fetchone()
        if source_row:
            conn.execute(
                "UPDATE snmp_mib_sources SET source_commit = ?, root_path = ?, file_count = ?, "
                "status = 'ready', error = '', updated_at = ? WHERE id = ?",
                (source_commit, str(mibs_path.resolve()), len(files), now, source_id),
            )
        else:
            conn.execute(
                "INSERT INTO snmp_mib_sources "
                "(id, source_type, source_name, source_commit, root_path, manifest_path, file_count, status, error, created_at, updated_at) "
                "VALUES (?, 'librenms', 'librenms', ?, ?, '', ?, 'ready', '', ?, ?)",
                (source_id, source_commit, str(mibs_path.resolve()), len(files), now, now),
            )

    def _record_item(
        *,
        file_path: Path,
        relative_path: str,
        vendor_key: str,
        vendor_name: str,
        file_hash: str,
        file_size: int,
        status: str,
        mib_id: str = "",
        module_name: str = "",
        node_count: int = 0,
        error: str = "",
    ) -> None:
        conn.execute(
            "INSERT INTO snmp_mib_import_items "
            "(id, run_id, source_id, relative_path, vendor_key, vendor_name, filename, sha256, file_size, "
            "raw_file_path, status, mib_id, module_name, node_count, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("mib-item"),
                run_id,
                source_id,
                relative_path,
                vendor_key,
                vendor_name,
                file_path.name,
                file_hash,
                file_size,
                str(file_path.resolve()),
                status,
                mib_id,
                module_name,
                node_count,
                error,
                now,
                utc_now(),
            ),
        )

    def _update_run(status: str = "running", error: str = "", current_path: str = "") -> None:
        completed_at = utc_now() if status in {"completed", "failed"} else ""
        conn.execute(
            "UPDATE snmp_mib_import_runs SET status = ?, total_files = ?, processed_files = ?, "
            "imported_files = ?, updated_files = ?, skipped_files = ?, failed_files = ?, "
            "duplicate_files = ?, zero_node_files = ?, total_nodes = ?, current_path = ?, error = ?, "
            "completed_at = ?, updated_at = ? WHERE id = ?",
            (
                status,
                stats["total_files"],
                stats["processed_files"],
                stats["imported_files"],
                stats["updated_files"],
                stats["skipped_files"],
                stats["failed_files"],
                stats["duplicate_files"],
                stats["zero_node_files"],
                stats["total_nodes"],
                current_path,
                error,
                completed_at,
                utc_now(),
                run_id,
            ),
        )

    def _path_is_in_scope(relative_path: str) -> bool:
        if not target_vendors_set:
            return True
        vendor_key = vendor_key_from_relative_path(relative_path)
        return (
            vendor_key in target_vendors_set
            or vendor_name_from_key(vendor_key).lower() in target_vendors_set
        )

    def _deactivate_missing_files() -> int:
        """Retire removed upstream files without touching uploads or built-ins."""
        if max_files is not None or not files:
            return 0
        rows = conn.execute(
            "SELECT id, relative_path FROM snmp_mibs "
            "WHERE source_type = 'librenms' AND is_active = 1 AND relative_path <> ''"
        ).fetchall()
        retired = 0
        retired_at = utc_now()
        for row in rows:
            mib_id = str(_value(row, "id", 0) or "")
            relative_path = str(_value(row, "relative_path", 1) or "")
            if not mib_id or not _path_is_in_scope(relative_path) or relative_path in seen_relative_paths:
                continue
            conn.execute(
                "UPDATE snmp_mibs SET is_active = 0, updated_at = ? WHERE id = ?",
                (retired_at, mib_id),
            )
            retired += 1
        return retired

    logger.info("Scanning %d MIB candidates in %s...", len(files), mibs_path)
    try:
        _upsert_source()
        conn.execute(
            "INSERT INTO snmp_mib_import_runs "
            "(id, source_id, source_type, source_commit, source_path, parser_version, status, total_files, started_at, created_at, updated_at) "
            "VALUES (?, ?, 'librenms', ?, ?, ?, 'running', ?, ?, ?, ?)",
            (run_id, source_id, source_commit, str(mibs_path.resolve()), PARSER_VERSION, len(files), now, now, now),
        )
        conn.commit()

        for file_path in files:
            relative_path = relative_mib_path(file_path, mibs_path)
            seen_relative_paths.add(relative_path)
            vendor_key = vendor_key_from_relative_path(relative_path)
            vendor_name = vendor_name_from_key(vendor_key)
            file_hash = sha256_file(file_path)
            file_size = file_path.stat().st_size
            manifest_entries.append(
                {
                    "relative_path": relative_path,
                    "vendor_key": vendor_key,
                    "vendor_name": vendor_name,
                    "sha256": file_hash,
                    "file_size": file_size,
                }
            )

            try:
                exact_row = conn.execute(
                    "SELECT m.id, m.name, m.node_count, m.parse_status, "
                    "(SELECT COUNT(*) FROM snmp_mib_nodes AS n "
                    " WHERE n.mib_id = m.id AND TRIM(COALESCE(n.oid, '')) <> '') AS resolved_node_count "
                    "FROM snmp_mibs AS m "
                    "WHERE m.source_type = 'librenms' AND m.is_active = 1 "
                    "AND m.relative_path = ? AND m.sha256 = ? "
                    "ORDER BY CASE WHEN m.source_id = ? THEN 0 ELSE 1 END, m.updated_at DESC LIMIT 1",
                    (relative_path, file_hash, source_id),
                ).fetchone()
                exact_mib_id = str(_value(exact_row, "id", 0) or "") if exact_row else ""
                exact_node_count = int(_value(exact_row, "node_count", 2) or 0) if exact_row else 0
                exact_resolved_count = int(_value(exact_row, "resolved_node_count", 4) or 0) if exact_row else 0
                needs_oid_repair = bool(exact_row and exact_node_count > 0 and exact_resolved_count < exact_node_count)
                if exact_row and str(_value(exact_row, "parse_status", 3) or "") in {"parsed", "zero_node"} and not needs_oid_repair:
                    mib_id = str(_value(exact_row, "id", 0))
                    node_count = int(_value(exact_row, "node_count", 2) or 0)
                    stats["processed_files"] += 1
                    stats["skipped_files"] += 1
                    stats["duplicate_files"] += 1
                    stats["total_nodes"] += node_count
                    stats["zero_node_files"] += int(node_count == 0)
                    _record_item(
                        file_path=file_path,
                        relative_path=relative_path,
                        vendor_key=vendor_key,
                        vendor_name=vendor_name,
                        file_hash=file_hash,
                        file_size=file_size,
                        status="skipped_existing",
                        mib_id=mib_id,
                        module_name=str(_value(exact_row, "name", 1) or ""),
                        node_count=node_count,
                    )
                    continue

                path_row = conn.execute(
                    "SELECT m.id, m.name, m.node_count, m.parse_status, "
                    "(SELECT COUNT(*) FROM snmp_mib_nodes AS n "
                    " WHERE n.mib_id = m.id AND TRIM(COALESCE(n.oid, '')) <> '') AS resolved_node_count "
                    "FROM snmp_mibs AS m "
                    "WHERE m.source_type = 'librenms' AND m.relative_path = ? "
                    "ORDER BY m.is_active DESC, CASE WHEN m.source_id = ? THEN 0 ELSE 1 END, "
                    "m.updated_at DESC LIMIT 1",
                    (relative_path, source_id),
                ).fetchone()
                path_mib_id = str(_value(path_row, "id", 0) or "") if path_row else ""

                legacy_row = conn.execute(
                    "SELECT id FROM snmp_mibs WHERE source_id = '' AND source_type = 'librenms' "
                    "AND filename = ? AND LOWER(vendor) = LOWER(?) ORDER BY updated_at DESC LIMIT 1",
                    (file_path.name, vendor_name),
                ).fetchone()
                existing_id = (
                    exact_mib_id
                    if needs_oid_repair
                    else (path_mib_id or str(_value(legacy_row, "id", 0) or ""))
                )

                raw_text = read_mib_text(file_path)

                if not raw_text or len(raw_text) < 20:
                    stats["processed_files"] += 1
                    stats["skipped_files"] += 1
                    _record_item(
                        file_path=file_path,
                        relative_path=relative_path,
                        vendor_key=vendor_key,
                        vendor_name=vendor_name,
                        file_hash=file_hash,
                        file_size=file_size,
                        status="skipped_empty",
                        error="empty_or_too_small",
                    )
                    continue

                if not existing_id:
                    builtin_row = conn.execute(
                        "SELECT id FROM snmp_mibs WHERE source_type = 'builtin' AND is_active = 1 "
                        "AND LOWER(filename) = LOWER(?) AND LOWER(vendor) = LOWER(?) AND sha256 = ? "
                        "ORDER BY updated_at DESC LIMIT 1",
                        (file_path.name, vendor_name, file_hash),
                    ).fetchone()
                    existing_id = str(_value(builtin_row, "id", 0)) if builtin_row else ""

                vendor_symbols = dict(global_symbols)
                vendor_symbols.update(symbols_by_vendor.get(vendor_key, {}))
                result = parse_and_store_mib(
                    conn,
                    filename=file_path.name,
                    raw_text=raw_text,
                    vendor=vendor_name,
                    source_type="librenms",
                    description=f"Official LibreNMS MIB for {vendor_name} ({relative_path})",
                    external_symbols=vendor_symbols,
                    source_id=source_id,
                    source_commit=source_commit,
                    relative_path=relative_path,
                    raw_file_path=str(file_path.resolve()),
                    sha256=file_hash,
                    import_run_id=run_id,
                    parser_version=PARSER_VERSION,
                    store_content=False,
                    existing_id=existing_id,
                )

                node_count = int(result.get("node_count", 0) or 0)
                stats["processed_files"] += 1
                stats["total_nodes"] += node_count
                stats["zero_node_files"] += int(node_count == 0)
                if existing_id:
                    stats["updated_files"] += 1
                    item_status = "updated"
                else:
                    stats["imported_files"] += 1
                    item_status = "imported"
                if node_count == 0:
                    item_status = "zero_node"
                _record_item(
                    file_path=file_path,
                    relative_path=relative_path,
                    vendor_key=vendor_key,
                    vendor_name=vendor_name,
                    file_hash=file_hash,
                    file_size=file_size,
                    status=item_status,
                    mib_id=str(result.get("id", "")),
                    module_name=str(result.get("name", "")),
                    node_count=node_count,
                )
            except Exception as exc:
                stats["processed_files"] += 1
                stats["failed_files"] += 1
                _record_item(
                    file_path=file_path,
                    relative_path=relative_path,
                    vendor_key=vendor_key,
                    vendor_name=vendor_name,
                    file_hash=file_hash,
                    file_size=file_size,
                    status="failed",
                    error=str(exc)[:2000],
                )
                logger.warning("Failed parsing MIB %s: %s", relative_path, exc)

            if stats["processed_files"] % 50 == 0:
                _update_run(current_path=relative_path)
                conn.commit()
                logger.info(
                    "Processed %d/%d MIB files (%d nodes, %d failures)",
                    stats["processed_files"],
                    stats["total_files"],
                    stats["total_nodes"],
                    stats["failed_files"],
                )

        deactivated_files = _deactivate_missing_files()
        if deactivated_files:
            logger.info("Retired %d MIB files removed from the current LibreNMS snapshot", deactivated_files)

        manifest_path = write_manifest(
            source_type="librenms",
            source_name="librenms",
            source_commit=source_commit,
            source_root=mibs_path,
            files=manifest_entries,
        )
        conn.execute(
            "UPDATE snmp_mib_sources SET manifest_path = ?, file_count = ?, updated_at = ? WHERE id = ?",
            (str(manifest_path), len(manifest_entries), utc_now(), source_id),
        )
        _update_run(status="completed", current_path="")
        conn.commit()
    except Exception as exc:
        logger.exception("MIB import run %s failed", run_id)
        _update_run(status="failed", error=str(exc)[:2000])
        conn.commit()
        raise
    finally:
        conn.close()

    elapsed = time.time() - start_time
    logger.info(
        "Import completed in %.2fs: %d files processed, %d new, %d updated, %d skipped, %d failed, %d zero-node",
        elapsed,
        stats["processed_files"],
        stats["imported_files"],
        stats["updated_files"],
        stats["skipped_files"],
        stats["failed_files"],
        stats["zero_node_files"],
    )

    return {
        "success": stats["failed_files"] == 0,
        "run_id": run_id,
        "source_id": source_id,
        "source_commit": source_commit,
        "imported": stats["imported_files"],
        "updated": stats["updated_files"],
        "processed": stats["processed_files"],
        "total_files": stats["total_files"],
        "nodes": stats["total_nodes"],
        "errors": stats["failed_files"],
        "skipped": stats["skipped_files"],
        "duplicates": stats["duplicate_files"],
        "zero_node": stats["zero_node_files"],
        "deactivated": deactivated_files,
        "elapsed_seconds": round(elapsed, 2),
    }
