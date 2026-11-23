#!/usr/bin/env python3
"""Re-encrypt stored AI provider keys in the current format (review item M14).

Upgrades legacy ciphertexts (sha256 key, no AAD) and ciphertexts made with an
older master key id to ``aik:v2:<current kid>`` bound to the provider id.
The gateway also upgrades a key the first time it uses it; this script does
all of them at once, e.g. after adding a new master key to
AI_PROVIDER_KEY_ENCRYPTION_KEYS and setting AI_PROVIDER_KEY_ID.

    python scripts/ai_provider_key_reencrypt.py --dry-run
    python scripts/ai_provider_key_reencrypt.py

Read the summary: ``failed`` > 0 means a stored key cannot be decrypted with
the configured master keys (the old key is missing from the configuration);
those rows are left unchanged.  Never prints key material.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def run(*, dry_run: bool) -> dict:
    import database.core as database_core
    from ai.security.crypto import ProviderKeyDecryptError, current_kid, is_current_format, reencrypt_if_needed

    report = {"current_kid": current_kid(), "dry_run": dry_run, "tables": {}}
    targets = (
        ("ai_provider", "id", "id"),
        ("ai_provider_key_rotation", "id", "provider_id"),
    )
    with database_core.get_db_connection() as conn:
        for table, key_column, provider_column in targets:
            stats = {"rows": 0, "current": 0, "upgraded": 0, "failed": 0, "failed_ids": []}
            rows = conn.execute(
                f"SELECT {key_column}, {provider_column}, api_key_encrypted FROM {table} WHERE api_key_encrypted IS NOT NULL"
            ).fetchall()
            for row_id, provider_id, token in rows:
                stats["rows"] += 1
                if is_current_format(token):
                    stats["current"] += 1
                    continue
                try:
                    upgraded, changed = reencrypt_if_needed(token, provider_id=str(provider_id))
                except ProviderKeyDecryptError:
                    stats["failed"] += 1
                    stats["failed_ids"].append(str(row_id))
                    continue
                if changed:
                    stats["upgraded"] += 1
                    if not dry_run:
                        conn.execute(
                            f"UPDATE {table} SET api_key_encrypted = ? WHERE {key_column} = ? AND api_key_encrypted = ?",
                            (upgraded, row_id, token),
                        )
            stats["failed_ids"] = stats["failed_ids"][:50]
            report["tables"][table] = stats
        if not dry_run:
            conn.commit()
    failed = sum(item["failed"] for item in report["tables"].values())
    report["status"] = "PASS" if not failed else "REVIEW"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args(argv)
    report = run(dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
