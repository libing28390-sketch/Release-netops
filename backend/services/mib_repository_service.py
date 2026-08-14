"""Local MIB repository helpers.

The repository keeps the raw LibreNMS/custom files on the local data volume.
The database stores only catalog, hash, parser status, and OID index metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = BACKEND_DIR / "data" / "mib_repository"
MIB_FILE_SUFFIXES = {"", ".mib", ".my", ".txt", ".asn"}
PARSER_VERSION = "mib-regex-v2"

_VENDOR_NAMES = {
    "rfc": "Standard",
    "iana": "Standard",
    "ietf": "Standard",
    "net-snmp": "Standard",
    "comware": "H3C",
    "h3c": "H3C",
    "cisco": "Cisco",
    "huawei": "Huawei",
    "juniper": "Juniper",
    "arista": "Arista",
    "ruijie": "Ruijie",
    "fortinet": "Fortinet",
    "mikrotik": "MikroTik",
    "zte": "ZTE",
    "zyxel": "Zyxel",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repository_root() -> Path:
    configured = os.environ.get("MIB_REPOSITORY_ROOT", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_REPOSITORY_ROOT


def ensure_repository_layout() -> Path:
    root = repository_root()
    for child in ("sources", "compiled", "imports"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def stable_source_id(source_type: str, source_name: str, source_commit: str) -> str:
    value = f"{source_type}\0{source_name}\0{source_commit}".encode("utf-8")
    return f"source-{hashlib.sha256(value).hexdigest()[:24]}"


# A source identifies the logical upstream catalog, not one immutable snapshot.
# The current commit is stored on source/import-run rows for provenance; it must
# not be part of the MIB row identity or every upstream update becomes a new
# active catalog.
LIBRENMS_SOURCE_ID = stable_source_id("librenms", "librenms", "catalog")


def safe_component(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("._") or fallback


def source_snapshot_dir(source_type: str, source_name: str, source_commit: str) -> Path:
    root = ensure_repository_layout()
    path = root / "sources" / safe_component(source_type) / safe_component(source_name) / safe_component(source_commit, "local")
    path.mkdir(parents=True, exist_ok=True)
    return path


def git_commit(repo_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "local"
    commit = (result.stdout or "").strip()
    return commit if result.returncode == 0 and commit else "local"


def iter_mib_files(mibs_dir: Path) -> list[Path]:
    """Return all MIB candidates, including files directly under ``mibs/``."""
    root = mibs_dir.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.suffix.lower() not in MIB_FILE_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().lower())


def relative_mib_path(path: Path, mibs_dir: Path) -> str:
    return path.resolve().relative_to(mibs_dir.resolve()).as_posix()


def vendor_key_from_relative_path(relative_path: str) -> str:
    first = relative_path.split("/", 1)[0].strip().lower()
    return first or "standard"


def vendor_name_from_key(vendor_key: str) -> str:
    key = (vendor_key or "standard").strip().lower()
    return _VENDOR_NAMES.get(key, key.replace("_", " ").replace("-", " ").title())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    *,
    source_type: str,
    source_name: str,
    source_commit: str,
    source_root: Path,
    files: Iterable[dict[str, Any]],
) -> Path:
    """Write an atomic local manifest for one source snapshot."""
    target_dir = source_snapshot_dir(source_type, source_name, source_commit)
    target = target_dir / "manifest.json"
    file_list = list(files)
    payload = {
        "schema_version": 1,
        "source_type": source_type,
        "source_name": source_name,
        "source_commit": source_commit,
        "source_root": str(source_root.resolve()),
        "file_count": len(file_list),
        "generated_at": utc_now(),
        "files": file_list,
    }
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target
