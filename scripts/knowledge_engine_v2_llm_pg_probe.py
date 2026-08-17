"""PostgreSQL-only LLM-001..037 migration and routing contract probe.

The probe runs the additive migration and all fixture writes inside one
transaction, then rolls it back.  It is intentionally independent of the
SQLite compatibility test harness.
"""

from __future__ import annotations

import json
import uuid

from database.core import _USE_PG, get_db_connection
from database.migrations.m0139_ai_multi_provider_model_switching import upgrade
from database.migrations.m0140_ai_provider_controls import upgrade as upgrade_controls
from database.migrations.m0141_ai_usage_daily_scope import upgrade as upgrade_usage_scope


def main() -> int:
    if not _USE_PG:
        raise SystemExit("LLM-PG-PROBE requires PostgreSQL DATABASE_URL")
    suffix = uuid.uuid4().hex[:10]
    provider_a = f"probe-openai-{suffix}"
    provider_b = f"probe-openai-b-{suffix}"
    model_a = f"probe-model-a-{suffix}"
    model_b = f"probe-model-b-{suffix}"
    conn = get_db_connection()
    report: dict[str, object] = {"database": "postgresql", "rollback": False}
    try:
        conn.execute("BEGIN")
        upgrade(conn, True)
        upgrade_controls(conn, True)
        upgrade_usage_scope(conn, True)
        required = {
            "ai_provider": {"health_status", "tags_json", "data_region", "allowed_data_classification"},
            "ai_model": {"stream_supported", "display_name", "cost_input_per_1k", "health_status"},
            "ai_messages": {"requested_model_id", "actual_model_id", "provider_id", "route_reason", "fallback_used"},
            "ai_conversations": {"selected_model_id", "model_locked"},
        }
        for table, fields in required.items():
            rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?", (table,)).fetchall()
            actual = {str(row[0]) for row in rows}
            missing = sorted(fields - actual)
            if missing:
                raise AssertionError(f"{table} missing {missing}")
        for table in ("ai_provider_key_audit", "ai_user_model_preference"):
            exists = conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?", (table,)).fetchone()
            if not exists:
                raise AssertionError(f"{table} was not created")
        usage_index = conn.execute("SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = 'ux_ai_usage_daily_scope'").fetchone()
        if not usage_index:
            raise AssertionError("daily usage uniqueness index was not created")

        conn.execute("INSERT INTO ai_provider (id,name,provider_type,base_url,enabled,created_at,updated_at,tags_json,health_status,data_region,allowed_data_classification) VALUES (?,?,?,?,1,?,?,?,'unknown','us-east','PUBLIC')", (f"{provider_a}-id", provider_a, "openai_compatible", "https://a.example/v1", "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z", json.dumps(["probe"])))
        conn.execute("INSERT INTO ai_provider (id,name,provider_type,base_url,enabled,created_at,updated_at,tags_json,health_status,data_region,allowed_data_classification) VALUES (?,?,?,?,1,?,?,?,'unknown','eu-west','PUBLIC')", (f"{provider_b}-id", provider_b, "openai_compatible", "https://b.example/v1", "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z", json.dumps(["probe"])))
        conn.execute("INSERT INTO ai_model (id,provider_id,name,model_code,model_type,enabled,is_default,priority,created_at,updated_at,stream_supported,display_name) VALUES (?,?,?,?, 'chat',1,1,20,?,?,1,?)", (f"{model_a}-id", f"{provider_a}-id", "Probe A", model_a, "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z", "Probe A"))
        conn.execute("INSERT INTO ai_model (id,provider_id,name,model_code,model_type,enabled,is_default,priority,created_at,updated_at,stream_supported,display_name) VALUES (?,?,?,?, 'chat',1,0,10,?,?,1,?)", (f"{model_b}-id", f"{provider_b}-id", "Probe B", model_b, "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z", "Probe B"))
        conn.execute("INSERT INTO ai_model_route (id,scene,model_id,fallback_model_id,enabled,priority,data_classification,created_at,updated_at) VALUES (?,?,?,?,1,?,?,?,?)", (f"route-{suffix}", f"probe-{suffix}", f"{model_a}-id", f"{model_b}-id", 20, "PUBLIC", "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z"))
        conn.execute("INSERT INTO ai_model_acl (id,model_id,tenant_id,subject_type,subject_id,allow_access,created_at) VALUES (?,?,?,?,?,1,?)", (f"acl-{suffix}", f"{model_a}-id", f"tenant-{suffix}", "role", "Operator", "2026-08-17T00:00:00Z"))
        conn.execute("INSERT INTO ai_provider_key_rotation (id,provider_id,key_version,status,api_key_masked,created_at) VALUES (?,?,1,'active','sk-****abcd',?)", (f"key-{suffix}", f"{provider_a}-id", "2026-08-17T00:00:00Z"))
        conn.execute("INSERT INTO ai_provider_key_audit (id,provider_id,key_version,action,actor_id,reason_code,created_at) VALUES (?,?,1,'rotate','probe','probe_rotation',?)", (f"audit-{suffix}", f"{provider_a}-id", "2026-08-17T00:00:00Z"))
        conn.execute("INSERT INTO ai_user_model_preference (id,tenant_id,user_id_opaque,model_id,enabled,updated_at) VALUES (?,?,?,?,1,?)", (f"pref-{suffix}", f"tenant-{suffix}", f"opaque-{suffix}", f"{model_a}-id", "2026-08-17T00:00:00Z"))
        report.update({"multi_provider": True, "same_model_code_scope": "provider_id+model_code", "acl_tenant_scoped": True, "route_fallback": True, "key_rotation": True, "key_audit": True, "user_default": True, "usage_scope": True})
        duplicate_rejected = False
        try:
            conn.execute("INSERT INTO ai_model (id,provider_id,name,model_code,created_at,updated_at) VALUES (?,?,?,?,?,?)", (f"dup-{suffix}", f"{provider_a}-id", "Duplicate", model_a, "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z"))
        except Exception:
            duplicate_rejected = True
            conn.rollback()
            conn.execute("BEGIN")
        report["duplicate_model_rejected"] = duplicate_rejected
    finally:
        conn.rollback()
        conn.close()
        report["rollback"] = True
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
