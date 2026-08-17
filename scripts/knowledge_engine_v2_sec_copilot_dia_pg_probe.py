"""PostgreSQL-only acceptance probe for SEC/COP/DIA V2 contracts.

The probe uses unique tenant/request IDs, deletes only its own rows, and never
prints prompt bodies, credentials, CLI output, or provider payloads.
"""

from __future__ import annotations

import json
import uuid

from ai.security.security_service import (
    audit_provider_adapters,
    create_security_incident,
    list_security_events,
    list_security_incidents,
    record_security_event,
    resolve_security_incident,
)
from database.core import _USE_PG, get_db_connection
from database.migrations import run_migrations
from services.diagnostic_orchestrator import DiagnosticOrchestrator


def main() -> None:
    assert _USE_PG, "SEC/COP/DIA acceptance requires PostgreSQL"
    suffix = uuid.uuid4().hex[:12]
    tenant = f"pg-sec-dia-{suffix}"
    other_tenant = f"pg-sec-dia-other-{suffix}"
    with get_db_connection() as conn:
        applied = run_migrations(conn, use_pg=True)
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            ).fetchall()
        }
        required = {
            "ai_security_events", "ai_security_incidents", "ai_tenant_security_controls",
            "ai_conversation_feedback", "ai_diagnostic_cases", "ai_diagnostic_runs",
            "ai_diagnostic_steps", "ai_attachment_security_events",
        }
        assert required <= tables
        event_columns = {
            str(row[0])
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'ai_security_events'"
            ).fetchall()
        }
        forbidden = {"payload", "prompt", "raw_payload", "secret", "credential", "body"}
        assert not forbidden.intersection(event_columns)
        assert conn.execute(
            "SELECT data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'ai_security_events' AND column_name = 'finding_categories_json'"
        ).fetchone()[0] == "jsonb"

    event_id = record_security_event(
        request_id=f"req-{suffix}", tenant_id=tenant, policy_version="sec-v2-test",
        classification="INTERNAL", data_region="unknown", decision="MINIMIZE",
        disposition="prepared", finding_categories=["serial_number"], provider_id="provider-test", model_id="model-test",
    )
    assert list_security_events(tenant_id=tenant)[0]["finding_categories"] == ["serial_number"]
    assert list_security_events(tenant_id=other_tenant) == []
    incident = create_security_incident(
        tenant_id=tenant, incident_type="adapter_bypass", severity="high", category="gateway",
        request_id=f"req-{suffix}", evidence={"event_id": event_id, "raw_prompt": "must-not-persist"},
    )
    assert "raw_prompt" not in incident["evidence_keys"]
    assert list_security_incidents(tenant_id=other_tenant) == []
    assert resolve_security_incident(tenant_id=tenant, incident_id=incident["id"], resolved_by="pg-probe")["status"] == "resolved"

    plan = DiagnosticOrchestrator().build_plan(
        symptom="interface down", playbook="interface_down", vendor="cisco", platform="ios_xe", target="fixture"
    )
    result = __import__("asyncio").run(DiagnosticOrchestrator().run(plan=plan, authorized_steps=[]))
    assert result["read_only"] is True and result["write_operations_enabled"] is False
    assert all(step["error_code"] == "DIA_NOT_AUTHORIZED" for step in result["steps"])
    audit = audit_provider_adapters()
    assert audit["decision"] == "PASS"

    with get_db_connection() as conn:
        conn.execute("DELETE FROM ai_security_incidents WHERE id = ? AND tenant_id = ?", (incident["id"], tenant))
        conn.execute("DELETE FROM ai_security_events WHERE id = ? AND tenant_id = ?", (event_id, tenant))
        conn.commit()
    print(json.dumps({"postgresql": True, "migrations_applied": applied, "tables_checked": len(required), "security_event": True, "tenant_isolation": True, "incident_lifecycle": True, "diagnostics_read_only": True, "adapter_audit": audit["decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
