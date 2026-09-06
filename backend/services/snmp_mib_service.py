"""SNMP MIB Repository and ASN.1 Symbol Node Parser Service.

Parses RFC standard and multi-vendor proprietary MIB definition files (.mib, .my, .txt),
extracts OID symbols, SYNTAX types, and descriptions, and provides fast search
and OID-to-metric mappings.
"""

from __future__ import annotations

import io
import hashlib
import logging
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database import get_db_connection
from services.mib_repository_service import PARSER_VERSION

logger = logging.getLogger(__name__)

SUPPORTED_MIB_FILE_SUFFIXES = (".mib", ".my", ".txt", ".asn", ".smi")

# Standard well-known root OID symbol mappings
STANDARD_ROOT_OIDS: dict[str, str] = {
    "iso": "1",
    "org": "1.3",
    "dod": "1.3.6",
    "internet": "1.3.6.1",
    "directory": "1.3.6.1.1",
    "mgmt": "1.3.6.1.2",
    "mib-2": "1.3.6.1.2.1",
    "transmission": "1.3.6.1.2.1.10",
    "experimental": "1.3.6.1.3",
    "private": "1.3.6.1.4",
    "enterprises": "1.3.6.1.4.1",
    "snmpV2": "1.3.6.1.6",
    "snmpModules": "1.3.6.1.6.3",
    # MIB-2 Subtrees
    "system": "1.3.6.1.2.1.1",
    "interfaces": "1.3.6.1.2.1.2",
    "ifTable": "1.3.6.1.2.1.2.2",
    "ifEntry": "1.3.6.1.2.1.2.2.1",
    "at": "1.3.6.1.2.1.3",
    "ip": "1.3.6.1.2.1.4",
    "icmp": "1.3.6.1.2.1.5",
    "tcp": "1.3.6.1.2.1.6",
    "udp": "1.3.6.1.2.1.7",
    "egp": "1.3.6.1.2.1.8",
    "snmp": "1.3.6.1.2.1.11",
    "host": "1.3.6.1.2.1.25",
    "ifMIB": "1.3.6.1.2.1.31",
    "ifMIBObjects": "1.3.6.1.2.1.31.1",
    "ifXTable": "1.3.6.1.2.1.31.1.1",
    "ifXEntry": "1.3.6.1.2.1.31.1.1.1",
    "entityMIB": "1.3.6.1.2.1.47",
    "entitySensorMIB": "1.3.6.1.2.1.99",
    # Cisco Enterprise SMI
    "cisco": "1.3.6.1.4.1.9",
    "ciscoProducts": "1.3.6.1.4.1.9.1",
    "ciscoLocal": "1.3.6.1.4.1.9.2",
    "ciscoTemporary": "1.3.6.1.4.1.9.3",
    "ciscoExperiment": "1.3.6.1.4.1.9.7",
    "ciscoAdmin": "1.3.6.1.4.1.9.8",
    "ciscoMgmt": "1.3.6.1.4.1.9.9",
    "ciscoModules": "1.3.6.1.4.1.9.12",
    # Huawei Enterprise SMI
    "huawei": "1.3.6.1.4.1.2011",
    "huaweiMgmt": "1.3.6.1.4.1.2011.5",
    "hwDatacomm": "1.3.6.1.4.1.2011.5.25",
    "huaweiUtility": "1.3.6.1.4.1.2011.6",
    # H3C Enterprise SMI
    "hh3c": "1.3.6.1.4.1.25506",
    "hh3cCommon": "1.3.6.1.4.1.25506.2",
    "hh3cEntities": "1.3.6.1.4.1.25506.2.6",
    "h3c": "1.3.6.1.4.1.2011.10",
    # Arista Enterprise SMI
    "arista": "1.3.6.1.4.1.30065",
    "aristaProducts": "1.3.6.1.4.1.30065.1",
    "aristaModules": "1.3.6.1.4.1.30065.2",
    "aristaMibs": "1.3.6.1.4.1.30065.3",
    "aristaExperiment": "1.3.6.1.4.1.30065.4",
    # Juniper Enterprise SMI
    "juniperMIB": "1.3.6.1.4.1.2636",
    "jnxProducts": "1.3.6.1.4.1.2636.1",
    "jnxServices": "1.3.6.1.4.1.2636.2",
    "jnxMibs": "1.3.6.1.4.1.2636.3",
    "jnxExperiment": "1.3.6.1.4.1.2636.4",
    # Ruijie Enterprise SMI
    "ruijie": "1.3.6.1.4.1.4881",
    "ruijieProducts": "1.3.6.1.4.1.4881.1",
    "ruijieModules": "1.3.6.1.4.1.4881.1.1",
    # Other Vendors
    "zte": "1.3.6.1.4.1.3902",
    "raisecom": "1.3.6.1.4.1.8886",
    "fortinet": "1.3.6.1.4.1.12356",
    "fnCoreMib": "1.3.6.1.4.1.12356.100",
    "fnFortiGateMib": "1.3.6.1.4.1.12356.101",
    "dell": "1.3.6.1.4.1.674",
    "hp": "1.3.6.1.4.1.11",
    "hpicfObjects": "1.3.6.1.4.1.11.2.14.11.5",
    "mikrotik": "1.3.6.1.4.1.14988",
    "maipu": "1.3.6.1.4.1.5651",
    "dptech": "1.3.6.1.4.1.35084",
    "f5": "1.3.6.1.4.1.3375",
    "checkpoint": "1.3.6.1.4.1.2620",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def detect_vendor_from_name(name: str, content: str = "") -> str:
    """Infer the equipment vendor from MIB file name or text content."""
    text = (name + " " + content[:2000]).upper()
    if "CISCO" in text:
        return "Cisco"
    if "HUAWEI" in text or "HW" in text:
        return "Huawei"
    if "HH3C" in text or "H3C" in text or "COMWARE" in text:
        return "H3C"
    if "ARISTA" in text:
        return "Arista"
    if "JUNIPER" in text or "JUNOS" in text:
        return "Juniper"
    if "RUIJIE" in text or "RG-" in text or "RGOS" in text:
        return "Ruijie"
    if "ZTE" in text or "ZXROS" in text:
        return "ZTE"
    if "RAISECOM" in text or "ROS_5." in text or "ISCOM" in text:
        return "Raisecom"
    if "FORTINET" in text or "FORTIOS" in text:
        return "Fortinet"
    if "DPTECH" in text:
        return "Dptech"
    if "MAIPU" in text:
        return "Maipu"
    if "RFC" in text or "IF-MIB" in text or "HOST-RESOURCES" in text or "ENTITY" in text:
        return "Standard"
    return "General"


class MibParser:
    """High-performance ASN.1 MIB tokenizer and multi-pass DAG symbol parser."""

    def __init__(self, raw_text: str, external_symbols: dict[str, str] | None = None):
        self.raw_text = raw_text
        self.clean_text = self._strip_comments(raw_text)
        self.module_name = self._extract_module_name()
        self.symbol_table: dict[str, str] = dict(STANDARD_ROOT_OIDS)
        if external_symbols:
            self.symbol_table.update(external_symbols)
        self.nodes: list[dict[str, Any]] = []

    def _strip_comments(self, text: str) -> str:
        # Remove ASN.1 comments (-- comment to end of line)
        lines = []
        for line in text.splitlines():
            comment_idx = line.find("--")
            if comment_idx >= 0:
                line = line[:comment_idx]
            lines.append(line)
        return "\n".join(lines)

    def _extract_module_name(self) -> str:
        match = re.search(r"^\s*([A-Za-z0-9_-]+)\s+DEFINITIONS\s*::=\s*BEGIN", self.clean_text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return "UNKNOWN-MIB"

    def parse(self) -> list[dict[str, Any]]:
        """Parse all ASN.1 declarations and extract structured OID symbol nodes."""
        # 1. Strip IMPORTS and EXPORTS blocks to prevent keyword collision
        body_text = re.sub(r"\b(?:IMPORTS|EXPORTS)\b[\s\S]*?;", "", self.clean_text, flags=re.I)

        # 2. Extract all top-level ASN.1 constructs with OID assignments
        construct_pattern = re.compile(
            r"\b([A-Za-z0-9_-]+)\s+(MODULE-IDENTITY|OBJECT-IDENTITY|OBJECT\s+IDENTIFIER|OBJECT-TYPE|NOTIFICATION-TYPE|MODULE-COMPLIANCE|OBJECT-GROUP|NOTIFICATION-GROUP)\b([\s\S]*?)::=\s*\{\s*([^}]+)\s*\}",
            re.I,
        )

        raw_definitions: dict[str, dict[str, Any]] = {}
        for match in construct_pattern.finditer(body_text):
            name = match.group(1).strip()
            kind = match.group(2).upper().replace(" ", "-")
            inner_body = match.group(3)
            oid_body = match.group(4).strip()

            is_type = kind in ("OBJECT-TYPE", "NOTIFICATION-TYPE")
            syntax = ""
            access = "read-only"
            status = "current"
            description = ""

            if is_type:
                syntax_m = re.search(r"SYNTAX\s+([\s\S]*?)(?=(?:UNITS|MAX-ACCESS|ACCESS|STATUS|DESCRIPTION|INDEX|AUGMENTS|DEFVAL|$))", inner_body, re.I)
                syntax = re.sub(r"\s+", " ", (syntax_m.group(1) if syntax_m else "").strip())[:64]

                access_m = re.search(r"(?:MAX-ACCESS|ACCESS)\s+([A-Za-z0-9_-]+)", inner_body, re.I)
                access = (access_m.group(1) if access_m else "read-only").strip().lower()[:32]

                status_m = re.search(r"STATUS\s+([A-Za-z0-9_-]+)", inner_body, re.I)
                status = (status_m.group(1) if status_m else "current").strip().lower()[:32]

                desc_m = re.search(r'DESCRIPTION\s+"([^"]*)"', inner_body, re.I)
                raw_desc = (desc_m.group(1) if desc_m else "").strip()
                description = "\n".join(l.strip() for l in raw_desc.splitlines() if l.strip())[:2000]

            raw_definitions[name] = {
                "kind": kind,
                "raw_oid": oid_body,
                "is_type": is_type,
                "syntax": syntax,
                "access": access,
                "status": status,
                "description": description,
            }

        # 3. Multi-pass iterative DAG symbol resolution (handles arbitrary inheritance depth)
        for _ in range(15):
            progress = False
            for name, item in raw_definitions.items():
                if name in self.symbol_table:
                    continue
                tokens = item["raw_oid"].split()
                if not tokens:
                    continue
                # Pure numbers: e.g. 1 3 6 1 4 1
                if all(t.isdigit() for t in tokens):
                    self.symbol_table[name] = ".".join(tokens)
                    progress = True
                    continue
                # Parent symbol + sub_ids: e.g. aristaExperiment 1
                parent = tokens[0].split('(')[0]
                if parent in self.symbol_table:
                    sub_ids = [t.split('(')[-1].rstrip(')') for t in tokens[1:] if t.isdigit() or t.rstrip(')').isdigit()]
                    if sub_ids:
                        self.symbol_table[name] = self.symbol_table[parent] + "." + ".".join(sub_ids)
                        progress = True
            if not progress:
                break

        # 4. Assemble final node list
        self.nodes = []
        for name, item in raw_definitions.items():
            if not item["is_type"]:
                continue
            calculated_oid = self.symbol_table.get(name, "")
            parent_oid = ".".join(calculated_oid.split(".")[:-1]) if calculated_oid else ""
            self.nodes.append({
                "node_name": name,
                "oid": calculated_oid,
                "parent_oid": parent_oid,
                "syntax_type": item["syntax"],
                "access_type": item["access"],
                "status": item["status"],
                "description": item["description"],
            })

        # Return all discovered nodes (including those with resolved OIDs)
        return self.nodes

    def _register_oid_definition(self, name: str, body: str) -> None:
        resolved, _ = self._resolve_oid(body)
        if resolved:
            self.symbol_table[name] = resolved

    def _resolve_oid(self, body: str) -> tuple[str, str]:
        """Convert an ASN.1 OID body like '{ cpmCPUTotalEntry 1 }' or '{ 1 3 6 1 4 1 9 9 109 1 1 1 1 8 }' to dotted decimal."""
        tokens = body.split()
        if not tokens:
            return "", ""

        # Case A: pure numbers: 1 3 6 1 2 1
        if all(t.isdigit() for t in tokens):
            return ".".join(tokens), ".".join(tokens[:-1])

        # Case B: ParentSymbol ChildSubId, e.g. "ciscoMgmt 109" or "system 1"
        first_token = tokens[0]
        # Match parent(number) syntax, e.g., "iso(1)"
        first_match = re.match(r"^([A-Za-z0-9_-]+)(?:\((\d+)\))?$", first_token)
        parent_name = first_match.group(1) if first_match else first_token

        base_oid = self.symbol_table.get(parent_name, "")
        if not base_oid and parent_name in STANDARD_ROOT_OIDS:
            base_oid = STANDARD_ROOT_OIDS[parent_name]

        if base_oid:
            sub_ids = []
            for t in tokens[1:]:
                sub_match = re.match(r"^(?:[A-Za-z0-9_-]+\()?(\d+)\)?$", t)
                if sub_match:
                    sub_ids.append(sub_match.group(1))
                elif t.isdigit():
                    sub_ids.append(t)
            if sub_ids:
                full_oid = f"{base_oid}.{'.'.join(sub_ids)}"
                parent_oid = f"{base_oid}.{'.'.join(sub_ids[:-1])}" if len(sub_ids) > 1 else base_oid
                return full_oid, parent_oid
            return base_oid, ""

        return "", ""


def parse_and_store_mib(
    conn,
    filename: str,
    raw_text: str,
    vendor: str = "",
    source_type: str = "user_upload",
    description: str = "",
    external_symbols: dict[str, str] | None = None,
    *,
    source_id: str = "",
    source_commit: str = "",
    relative_path: str = "",
    raw_file_path: str = "",
    sha256: str = "",
    import_run_id: str = "",
    parser_version: str = PARSER_VERSION,
    store_content: bool = True,
    existing_id: str = "",
) -> dict[str, Any]:
    """Parse one MIB file text and persist it and its symbols to PostgreSQL/SQLite."""
    parser = MibParser(raw_text, external_symbols=external_symbols)
    nodes = parser.parse()
    module_name = parser.module_name if parser.module_name != "UNKNOWN-MIB" else filename.rsplit(".", 1)[0]
    detected_vendor = vendor or detect_vendor_from_name(module_name, raw_text)

    content_hash = sha256 or hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    mib_id = existing_id or f"mib-{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    file_size = len(raw_text.encode("utf-8"))
    parse_status = "parsed" if nodes else "zero_node"
    content_text = raw_text if store_content else ""

    # Source imports are identified by logical source/path, not module name or
    # commit hash. The hash is used to detect a no-op; a changed upstream file
    # updates the same current catalog row. A single module name may
    # legitimately exist in multiple vendor folders. User uploads retain the
    # legacy filename/hash replacement behavior when no source identity exists.
    existing = None
    if existing_id:
        existing = conn.execute("SELECT id FROM snmp_mibs WHERE id = ?", (existing_id,)).fetchone()
    elif source_id and relative_path:
        existing = conn.execute(
            "SELECT id FROM snmp_mibs WHERE source_id = ? AND relative_path = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (source_id, relative_path),
        ).fetchone()
    elif source_type == "user_upload":
        existing = conn.execute(
            "SELECT id FROM snmp_mibs WHERE source_type = ? AND filename = ? AND sha256 = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (source_type, filename, content_hash),
        ).fetchone()

    # Built-in seeds use a deterministic ID. Remove stale symbol rows before
    # either updating or upserting that ID so concurrent seed calls remain
    # idempotent.
    if existing_id:
        conn.execute("DELETE FROM snmp_mib_nodes WHERE mib_id = ?", (mib_id,))

    if existing:
        mib_id = str(existing[0] if isinstance(existing, tuple) else existing["id"])
        if not existing_id:
            conn.execute("DELETE FROM snmp_mib_nodes WHERE mib_id = ?", (mib_id,))
        conn.execute(
            """
            UPDATE snmp_mibs
            SET name = ?, vendor = ?, filename = ?, file_size = ?, node_count = ?,
                source_type = ?, description = ?, content_text = ?,
                source_id = ?, source_commit = ?, relative_path = ?,
                raw_file_path = ?, sha256 = ?, parse_status = ?, parse_error = '',
                parser_version = ?, import_run_id = ?, is_active = 1, updated_at = ?
            WHERE id = ?
            """,
            (
                module_name,
                detected_vendor,
                filename,
                file_size,
                len(nodes),
                source_type,
                description,
                content_text,
                source_id,
                source_commit,
                relative_path,
                raw_file_path,
                content_hash,
                parse_status,
                parser_version,
                import_run_id,
                now,
                mib_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO snmp_mibs
                (id, name, vendor, filename, file_size, node_count,
                 source_type, description, content_text, source_id, source_commit,
                 relative_path, raw_file_path, sha256, parse_status, parse_error,
                 parser_version, import_run_id, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name = excluded.name,
                vendor = excluded.vendor,
                filename = excluded.filename,
                file_size = excluded.file_size,
                node_count = excluded.node_count,
                source_type = excluded.source_type,
                description = excluded.description,
                content_text = excluded.content_text,
                source_id = excluded.source_id,
                source_commit = excluded.source_commit,
                relative_path = excluded.relative_path,
                raw_file_path = excluded.raw_file_path,
                sha256 = excluded.sha256,
                parse_status = excluded.parse_status,
                parse_error = excluded.parse_error,
                parser_version = excluded.parser_version,
                import_run_id = excluded.import_run_id,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                mib_id,
                module_name,
                detected_vendor,
                filename,
                file_size,
                len(nodes),
                source_type,
                description,
                content_text,
                source_id,
                source_commit,
                relative_path,
                raw_file_path,
                content_hash,
                parse_status,
                "",
                parser_version,
                import_run_id,
                1,
                now,
                now,
            ),
        )

    # Insert parsed nodes
    for node in nodes:
        node_id = f"node-{uuid.uuid4().hex[:14]}"
        conn.execute(
            """
            INSERT INTO snmp_mib_nodes
                (id, mib_id, node_name, oid, parent_oid, syntax_type,
                 access_type, status, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                mib_id,
                node["node_name"],
                node["oid"],
                node.get("parent_oid", ""),
                node.get("syntax_type", ""),
                node.get("access_type", ""),
                node.get("status", "current"),
                node.get("description", ""),
                now,
            ),
        )

    return {
        "id": mib_id,
        "name": module_name,
        "vendor": detected_vendor,
        "filename": filename,
        "file_size": file_size,
        "node_count": len(nodes),
        "source_type": source_type,
        "description": description,
        "source_id": source_id,
        "source_commit": source_commit,
        "relative_path": relative_path,
        "raw_file_path": raw_file_path,
        "sha256": content_hash,
        "parse_status": parse_status,
        "parser_version": parser_version,
        "symbols": parser.symbol_table,
    }


def is_valid_mib_zip_member(file_info: zipfile.ZipInfo) -> bool:
    """Filter out OS metadata and non-text binary formats from ZIP members."""
    if file_info.is_dir():
        return False
    norm_name = file_info.filename.replace("\\", "/").strip()
    parts = [p for p in norm_name.split("/") if p]
    if not parts or any(p.startswith(".") for p in parts) or "__MACOSX" in parts:
        return False
    ext = os.path.splitext(norm_name.lower())[1]
    if ext in (
        ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z", ".exe", ".bin",
        ".dll", ".so", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc", ".db", ".sqlite"
    ):
        return False
    return ext in SUPPORTED_MIB_FILE_SUFFIXES or ext == ""


def extract_mib_archive_to_repo(
    zip_bytes: bytes,
    target_mibs_dir: Path,
    max_files: int = 50000,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
) -> tuple[int, set[str]]:
    """Safely extract MIB files from a ZIP archive into the local repository directory.

    Handles archives with or without wrapper folder prefixes (e.g. 'mibs/', 'librenms-master/mibs/'),
    strips unsafe components (ZipSlip protection), cleans OS metadata (__MACOSX, .DS_Store),
    and normalizes files directly under target_mibs_dir.
    """
    target_mibs_path = Path(target_mibs_dir).resolve()
    target_mibs_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        members = [f for f in z.infolist() if not f.is_dir()]
        if len(members) > max_files:
            raise ValueError(f"ZIP archive contains too many files ({len(members)} > {max_files})")

        total_size = sum(max(0, int(f.file_size)) for f in members)
        if total_size > max_uncompressed_bytes:
            raise ValueError(
                f"ZIP archive is too large after decompression ({total_size} > {max_uncompressed_bytes} bytes)"
            )

        clean_members: list[tuple[zipfile.ZipInfo, str, list[str]]] = []
        for f in members:
            norm_name = f.filename.replace("\\", "/").strip()
            parts = [p for p in norm_name.split("/") if p]
            if not parts or any(p.startswith(".") for p in parts) or "__MACOSX" in parts:
                continue
            ext = os.path.splitext(norm_name.lower())[1]
            if ext in (
                ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z", ".exe", ".bin",
                ".dll", ".so", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc", ".db", ".sqlite"
            ):
                continue
            clean_members.append((f, norm_name, parts))

        if not clean_members:
            return 0, set()

        prefix_to_strip = ""
        first_parts = clean_members[0][2]
        if len(first_parts) > 1:
            common_first = first_parts[0]
            if all(parts[0] == common_first for _, _, parts in clean_members):
                common_lower = common_first.lower()
                known_vendors = (
                    "cisco", "huawei", "h3c", "comware", "rfc", "net-snmp", "iana", "ietf",
                    "juniper", "arista", "ruijie", "fortinet", "mikrotik", "zte", "dell", "hp", "hpe", "f5", "checkpoint"
                )
                if common_lower not in known_vendors:
                    prefix_to_strip = common_first + "/"

        extracted_count = 0
        detected_vendors: set[str] = set()

        for f, norm_name, _ in clean_members:
            if "/mibs/" in f"/{norm_name}":
                idx = norm_name.find("mibs/")
                rel_path = norm_name[idx + len("mibs/"):]
            elif prefix_to_strip and norm_name.startswith(prefix_to_strip):
                rel_path = norm_name[len(prefix_to_strip):]
            else:
                rel_path = norm_name

            rel_path = rel_path.strip("/")
            if not rel_path:
                continue

            # Path traversal safety check (ZipSlip)
            dest_file = (target_mibs_path / rel_path).resolve()
            if not str(dest_file).startswith(str(target_mibs_path)):
                continue

            dest_file.parent.mkdir(parents=True, exist_ok=True)
            data = z.read(f)
            dest_file.write_bytes(data)
            extracted_count += 1

            rel_parts = rel_path.split("/")
            if len(rel_parts) > 1:
                detected_vendors.add(rel_parts[0])

        return extracted_count, detected_vendors


def parse_and_store_zip(
    conn,
    zip_bytes: bytes,
    vendor: str = "",
    source_type: str = "user_upload",
    description: str = "",
    max_files: int = 20000,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
    errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Unzip and parse supported MIB files without extracting to disk.

    Each archive member is isolated by a database savepoint.  A malformed
    vendor file therefore does not poison the PostgreSQL transaction for the
    remaining valid files in the same ZIP.
    """
    results = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        members = [file_info for file_info in z.infolist() if not file_info.is_dir()]
        if len(members) > max_files:
            raise ValueError(f"ZIP archive contains too many files (maximum {max_files})")

        supported_members = [
            file_info
            for file_info in members
            if is_valid_mib_zip_member(file_info)
        ]
        total_uncompressed_bytes = sum(max(0, int(file_info.file_size)) for file_info in supported_members)
        if total_uncompressed_bytes > max_uncompressed_bytes:
            raise ValueError(
                "ZIP archive is too large after decompression "
                f"(maximum {max_uncompressed_bytes} bytes)"
            )

        for index, file_info in enumerate(supported_members):
            savepoint = f"snmp_mib_zip_{index}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                content = z.read(file_info).decode("utf-8", errors="replace")
                base_name = file_info.filename.split("/")[-1].split("\\")[-1]
                inferred_vendor = vendor or detect_vendor_from_name(base_name, content)
                res = parse_and_store_mib(
                    conn,
                    filename=base_name,
                    raw_text=content,
                    vendor=inferred_vendor,
                    source_type=source_type,
                    description=description,
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                results.append(res)
            except Exception as e:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    conn.rollback()
                    raise
                error_message = str(e)[:500] or type(e).__name__
                logger.warning("Failed to parse MIB in zip %s: %s", file_info.filename, error_message)
                if errors is not None:
                    errors.append({"filename": file_info.filename, "error": error_message})
    return results


def deduplicate_builtin_mibs(conn) -> int:
    """Remove duplicate built-in rows while retaining the richest copy.

    Built-in definitions are catalog seeds, not versioned user documents.  A
    concurrent first request used to seed the same definition twice because
    both requests could observe an empty repository.  The cleanup is limited
    to the built-in identity (name/vendor/filename) and keeps the row with the
    most parsed nodes, then the newest update, so user uploads and LibreNMS
    source records are never removed here.
    """
    rows = conn.execute(
        "SELECT id, name, vendor, filename, node_count, updated_at "
        "FROM snmp_mibs WHERE source_type = 'builtin' AND is_active = 1 "
        "ORDER BY name, vendor, filename, updated_at, id"
    ).fetchall()
    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for row in rows:
        key = tuple(str(row[index] or "").strip().lower() for index in (1, 2, 3))
        grouped.setdefault(key, []).append(row)

    removed = 0
    for candidates in grouped.values():
        if len(candidates) < 2:
            continue
        winner = max(
            candidates,
            key=lambda row: (
                int(row[4] or 0),
                str(row[5] or ""),
                str(row[0] or ""),
            ),
        )
        winner_id = str(winner[0])
        for row in candidates:
            loser_id = str(row[0])
            if loser_id == winner_id:
                continue
            conn.execute("DELETE FROM snmp_mib_nodes WHERE mib_id = ?", (loser_id,))
            conn.execute("DELETE FROM snmp_mibs WHERE id = ?", (loser_id,))
            removed += 1
    return removed


_MIB_LIST_COLUMNS = (
    "id, name, vendor, filename, file_size, node_count, source_type, "
    "source_id, source_commit, relative_path, sha256, parse_status, parse_error, "
    "parser_version, import_run_id, is_active, created_at, updated_at"
 )


def _mib_list_filter(search: str = "", vendor: str = "", status: str = "") -> tuple[str, list[Any]]:
    """Build the shared list filter without loading MIB source text."""
    where = ["is_active = 1"]
    params: list[Any] = []
    clean_search = search.strip().lower()
    if clean_search:
        # Keep list responses small: descriptions are detail-only data and are
        # intentionally not searched on every keystroke in the large list.
        where.append("(LOWER(name) LIKE ? OR LOWER(filename) LIKE ?)")
        term = f"%{clean_search}%"
        params.extend([term, term])
    clean_vendor = vendor.strip().lower()
    if clean_vendor:
        where.append("LOWER(vendor) LIKE ?")
        params.append(f"%{clean_vendor}%")

    clean_status = status.strip().lower()
    if clean_status == "unresolved_oid":
        where.append(
            "EXISTS ("
            "SELECT 1 FROM snmp_mib_nodes AS unresolved_node "
            "WHERE unresolved_node.mib_id = snmp_mibs.id "
            "AND TRIM(COALESCE(unresolved_node.oid, '')) = ''"
            ")"
        )
    elif clean_status in {"parsed", "zero_node", "failed"}:
        where.append("parse_status = ?")
        params.append(clean_status)
    return " AND ".join(where), params


def list_mibs(conn, search: str = "", vendor: str = "", status: str = "") -> list[dict[str, Any]]:
    """List all imported MIB modules for internal callers and tests.

    The HTTP endpoint uses :func:`list_mibs_page` so the browser never loads
    the whole repository into the DOM. This legacy helper remains unpaged for
    service callers that explicitly need the complete catalog.
    """
    where, params = _mib_list_filter(search, vendor, status)
    query = f"SELECT {_MIB_LIST_COLUMNS} FROM snmp_mibs WHERE {where} ORDER BY vendor, name"
    rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_mibs_page(
    conn,
    search: str = "",
    vendor: str = "",
    page: int = 1,
    page_size: int = 40,
    status: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Return one bounded MIB list page and the filtered total count."""
    safe_page = max(1, int(page))
    safe_page_size = max(10, min(100, int(page_size)))
    where, params = _mib_list_filter(search, vendor, status)

    count_row = conn.execute(
        f"SELECT COUNT(*) AS total FROM snmp_mibs WHERE {where}",
        tuple(params),
    ).fetchone()
    total = int(count_row[0] if isinstance(count_row, tuple) else count_row["total"]) if count_row else 0

    offset = (safe_page - 1) * safe_page_size
    rows = conn.execute(
        f"SELECT {_MIB_LIST_COLUMNS} FROM snmp_mibs WHERE {where} "
        "ORDER BY vendor, name LIMIT ? OFFSET ?",
        tuple(params + [safe_page_size, offset]),
    ).fetchall()
    return [dict(r) for r in rows], total


def get_mib_repository_stats(
    conn,
    search: str = "",
    vendor: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Return import/parse health for the current list filters.

    Vendor counts remain global so the vendor suggestions stay available while
    a vendor/search filter is active. The module and health counters use the
    same filters as the paged MIB list, keeping the summary and footer totals
    consistent.
    """
    filtered_where, filtered_params = _mib_list_filter(search, vendor, status)
    total_row = conn.execute(
        f"SELECT COUNT(*) FROM snmp_mibs WHERE {filtered_where}",
        tuple(filtered_params),
    ).fetchone()
    total = int(total_row[0] if isinstance(total_row, tuple) else total_row[0]) if total_row else 0
    status_counts: dict[str, int] = {}
    for row in conn.execute(
        f"SELECT parse_status, COUNT(*) FROM snmp_mibs WHERE {filtered_where} GROUP BY parse_status",
        tuple(filtered_params),
    ).fetchall():
        status_counts[str(row[0] or "unknown")] = int(row[1] or 0)

    vendor_counts: dict[str, int] = {}
    for row in conn.execute(
        "SELECT TRIM(vendor), COUNT(*) FROM snmp_mibs "
        "WHERE is_active = 1 AND TRIM(COALESCE(vendor, '')) <> '' "
        "GROUP BY TRIM(vendor) ORDER BY LOWER(TRIM(vendor))"
    ).fetchall():
        vendor_name = str(row[0] or "").strip()
        if vendor_name:
            vendor_counts[vendor_name] = int(row[1] or 0)

    unresolved_oid_row = conn.execute(
        "SELECT COUNT(*) FROM snmp_mib_nodes AS n "
        "WHERE TRIM(COALESCE(n.oid, '')) = '' "
        f"AND n.mib_id IN (SELECT id FROM snmp_mibs WHERE {filtered_where})",
        tuple(filtered_params),
    ).fetchone()
    unresolved_oid_node_count = int(unresolved_oid_row[0] or 0) if unresolved_oid_row else 0

    latest_row = conn.execute(
        "SELECT id, source_id, source_commit, status, total_files, processed_files, imported_files, "
        "updated_files, skipped_files, failed_files, duplicate_files, zero_node_files, total_nodes, "
        "current_path, error, started_at, completed_at FROM snmp_mib_import_runs "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    latest = dict(latest_row) if latest_row is not None and not isinstance(latest_row, tuple) else None
    if isinstance(latest_row, tuple):
        fields = (
            "id", "source_id", "source_commit", "status", "total_files", "processed_files",
            "imported_files", "updated_files", "skipped_files", "failed_files", "duplicate_files",
            "zero_node_files", "total_nodes", "current_path", "error", "started_at", "completed_at",
        )
        latest = dict(zip(fields, latest_row))
    if latest:
        latest.pop("current_path", None)

    return {
        "module_count": total,
        "status_counts": status_counts,
        "vendor_counts": vendor_counts,
        "parsed_module_count": status_counts.get("parsed", 0),
        "zero_node_module_count": status_counts.get("zero_node", 0),
        "failed_module_count": status_counts.get("failed", 0),
        "unresolved_oid_node_count": unresolved_oid_node_count,
        "latest_import": latest,
    }


def get_mib_detail(conn, mib_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, vendor, filename, file_size, node_count, source_type, description, "
        "source_id, source_commit, relative_path, sha256, parse_status, parse_error, "
        "parser_version, import_run_id, module_oid, is_active, created_at, updated_at "
        "FROM snmp_mibs WHERE id = ? AND is_active = 1",
        (mib_id,),
    ).fetchone()
    if not row:
        return None
    mib_data = dict(row)
    nodes = conn.execute(
        "SELECT id, node_name, oid, parent_oid, syntax_type, access_type, status, description "
        "FROM snmp_mib_nodes WHERE mib_id = ? ORDER BY oid",
        (mib_id,),
    ).fetchall()
    node_list = [dict(n) for n in nodes]
    resolved_node_count = sum(1 for node in node_list if str(node.get("oid") or "").strip())
    mib_data["nodes"] = node_list
    mib_data["resolved_node_count"] = resolved_node_count
    mib_data["unresolved_node_count"] = len(node_list) - resolved_node_count
    return mib_data


def delete_mib(conn, mib_id: str) -> bool:
    row = conn.execute("SELECT id FROM snmp_mibs WHERE id = ?", (mib_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM snmp_mibs WHERE id = ?", (mib_id,))
    return True


def search_mib_nodes(
    conn,
    query: str = "",
    vendor: str = "",
    mib_id: str = "",
    limit: int = 50,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """Fast search for OID symbol nodes across the MIB repository.

    Supports keyword search by node name (e.g., 'cpu', 'temp', 'fan'),
    dotted OID prefix, or description. ``scope='node'`` restricts keyword
    searches to the visible node name (and keeps dotted OID prefix search),
    which is useful when a caller needs every displayed result to match the
    node itself rather than hidden description or MIB metadata.
    """
    sql = """
    SELECT n.id, n.mib_id, m.name AS mib_name, m.vendor, n.node_name, n.oid,
           n.syntax_type, n.access_type, n.status, n.description
    FROM snmp_mib_nodes n
    JOIN snmp_mibs m ON n.mib_id = m.id
    WHERE 1=1
    """
    params: list[Any] = []

    clean_q = query.strip().lower()
    node_scope = scope.strip().lower() == "node"
    if clean_q:
        if re.match(r"^[0-9.]+$", clean_q):
            sql += " AND (n.oid LIKE ?)"
            params.append(f"{clean_q}%")
        elif node_scope:
            sql += " AND LOWER(n.node_name) LIKE ?"
            params.append(f"%{clean_q}%")
        else:
            sql += " AND (LOWER(n.node_name) LIKE ? OR LOWER(n.description) LIKE ? OR LOWER(m.name) LIKE ?)"
            term = f"%{clean_q}%"
            params.extend([term, term, term])

    if vendor.strip():
        sql += " AND LOWER(m.vendor) = ?"
        params.append(vendor.strip().lower())

    if mib_id.strip():
        sql += " AND n.mib_id = ?"
        params.append(mib_id.strip())

    safe_limit = max(1, min(200, limit))
    sql += f" ORDER BY (CASE WHEN LOWER(n.node_name) = ? THEN 0 WHEN LOWER(n.node_name) LIKE ? THEN 1 ELSE 2 END), n.node_name LIMIT {safe_limit}"
    params.extend([clean_q, f"{clean_q}%"])

    rows = conn.execute(sql, tuple(params)).fetchall()
    results = []
    for r in rows:
        item = dict(r)
        # Recommend metric mode based on SYNTAX
        syntax = str(item.get("syntax_type") or "").lower()
        if "counter64" in syntax:
            item["recommended_mode"] = "counter_rate_percent"
            item["recommended_counter_bits"] = 64
        elif "counter" in syntax:
            item["recommended_mode"] = "counter_rate_percent"
            item["recommended_counter_bits"] = 32
        elif "gauge" in syntax or "percent" in syntax:
            item["recommended_mode"] = "direct_percent"
        elif "temperature" in item["node_name"].lower() or "voltage" in item["node_name"].lower() or "power" in item["node_name"].lower():
            item["recommended_mode"] = "direct_value"
        elif "state" in item["node_name"].lower() or "status" in item["node_name"].lower():
            item["recommended_mode"] = "status_code"
        else:
            item["recommended_mode"] = "direct_value"
        results.append(item)
    return results
