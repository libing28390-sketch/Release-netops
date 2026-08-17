"""KUI-017 PostgreSQL/runtime and redaction probe."""

from __future__ import annotations

import json

from database.core import get_db_connection
from ai.services.retrieval_trace_store import (
    clear_retrieval_traces,
    get_retrieval_trace,
    list_retrieval_traces,
    record_retrieval_trace,
)


def main() -> dict[str, object]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT current_setting('server_version_num')").fetchone()
        pg_version = str(row[0] if row else "")
    clear_retrieval_traces()
    trace_id = record_retrieval_trace(
        tenant_id="tenant-kui017-probe",
        user_id="probe",
        query="show secret command",
        trace={
            "status": "no_match",
            "request": {"vendor": "Huawei"},
            "resolution": {"ambiguous": True, "platform_candidates": ["huawei_vrp", "cisco_ios_xe"], "evidence": "candidate"},
            "metadata_candidate_documents": 2,
            "candidate_count": 0,
            "citations": [{"citation_id": "cit_probe", "document_id": "secret", "url": "https://example.invalid/?token=secret"}],
        },
    )
    item = get_retrieval_trace(tenant_id="tenant-kui017-probe", trace_id=trace_id) or {}
    other = get_retrieval_trace(tenant_id="tenant-kui017-other", trace_id=trace_id)
    serialized = json.dumps(item, ensure_ascii=False).lower()
    checks = {
        "postgresql": bool(pg_version) and pg_version.isdigit(),
        "tenant_isolation": other is None and len(list_retrieval_traces(tenant_id="tenant-kui017-other")) == 0,
        "default_redaction": item.get("redaction", {}).get("default") is True,
        "hash_only_query": item.get("query_hash") != "show secret command" and len(str(item.get("query_hash") or "")) == 64,
        "no_raw_leak": not any(marker in serialized for marker in ("show secret", "secret", "document_id", "chunk_id", "https://")),
        "bounded": len(list_retrieval_traces(tenant_id="tenant-kui017-probe", limit=200)) <= 200,
    }
    if not all(checks.values()):
        raise SystemExit(json.dumps(checks, ensure_ascii=False))
    clear_retrieval_traces()
    return checks


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, sort_keys=True))
