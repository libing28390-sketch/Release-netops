"""Live PostgreSQL read-only probe for OBS-008 database observability."""

from __future__ import annotations

import json

import database.core as database_core
from ai.services.database_observability import snapshot


def main() -> None:
    if not database_core._USE_PG:
        raise SystemExit("OBS-008 requires the configured PostgreSQL authority")
    result = snapshot()
    assert result["backend"] == "postgresql"
    assert result["read_only"] is True
    assert result["production_authority"] == "postgresql"
    assert result["cache"]["status"] == "PASS"
    assert result["capacity"]["synthetic_rows_inserted"] is False
    assert result["slow_queries"]["query_text_included"] is False
    assert result["redaction"] == {
        "query_text": False,
        "parameters": False,
        "credentials": False,
        "tenant_ids": False,
        "document_content": False,
    }
    bounded = {
        "status": result["status"],
        "relation_stats_status": result["relation_stats"]["status"],
        "cache_hit_rate": result["cache"]["hit_rate"],
        "slow_query_source": result["slow_queries"].get("source", "pg_stat_statements"),
        "slow_query_status": result["slow_queries"]["status"],
        "slow_query_count": result["slow_queries"].get("slow_query_count", 0),
        "capacity_status": result["capacity"]["status"],
        "redacted": True,
    }
    print(json.dumps(bounded, sort_keys=True))


if __name__ == "__main__":
    main()
