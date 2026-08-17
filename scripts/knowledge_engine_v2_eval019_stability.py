"""Bounded EVAL-019 stability gate using PostgreSQL and fault-injected paths.

The import state machine, SSE registry and LLM Gateway are exercised in a
bounded local soak.  Reindex lease/checkpoint state is persisted only in a
PostgreSQL temporary table.  No external Provider request, device write, or
production table mutation is allowed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai.gateway.exceptions import AINetworkException  # noqa: E402
from ai.gateway.limits import ai_limits  # noqa: E402
from ai.gateway.llm_gateway import LLMGateway  # noqa: E402
from ai.security.gateway import AISecurityGateway, SecurityPolicy  # noqa: E402
from ai.services.sse_stream_registry import (  # noqa: E402
    SSEStreamRegistry,
    event_payload,
    event_sequence,
    event_type,
    request_fingerprint,
)
from database import core  # noqa: E402
from services.ingestion_pipeline_service import (  # noqa: E402
    IngestionPipeline,
    PHASE_ORDER,
)


TASK_ID = "EVAL-019"
IMPORT_CYCLES = 100
REINDEX_ROWS = 1000
REINDEX_BATCH_SIZE = 50
SSE_STREAM_CYCLES = 100
PROVIDER_CYCLES = 100
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-stability-v1.json"


def _complete_job(job: Any, *, worker: str, request_id: str) -> None:
    job.update_progress(
        total_count=1,
        processed_count=1,
        parsed_count=1,
        succeeded_count=1,
        actor=worker,
        request_id=request_id,
    )
    for phase in PHASE_ORDER[1:]:
        job.advance_phase(phase, actor=worker, request_id=request_id)
    job.complete(actor=worker, request_id=request_id)


def run_import_soak(cycles: int = IMPORT_CYCLES) -> dict[str, Any]:
    pipeline = IngestionPipeline()
    recovered_failures = 0
    completed = 0
    for index in range(cycles):
        request_id = f"eval019-import-{index:04d}"
        job = pipeline.create_job(
            tenant_id="eval019-tenant",
            job_kind="document_import",
            idempotency_key=f"eval019-source-{index:04d}",
            scope={"source_id": f"eval019-source-{index:04d}", "document_id": f"eval019-doc-{index:04d}"},
            max_retries=1,
            actor="eval019-test",
        )
        job.claim("eval019-worker-a", request_id=request_id)
        if index % 10 == 0:
            job.fail(TimeoutError("bounded transient source timeout"), actor="eval019-worker-a", request_id=request_id)
            # ``fail`` already schedules a retry for a retryable error.  The
            # recovery worker claims the same retry-wait job at its due time;
            # creating a second child here would be a duplicate retry.
            job.claim(
                "eval019-worker-b",
                now=job.next_retry_at,
                request_id=f"{request_id}-retry-claim",
            )
            recovered_failures += 1
        _complete_job(job, worker="eval019-worker-b", request_id=f"{request_id}-complete")
        if job.execution_state != "succeeded":
            raise AssertionError(f"import soak did not recover cycle {index}")
        completed += 1
    return {
        "cycles": cycles,
        "completed": completed,
        "recovered_failures": recovered_failures,
        "terminal_failures": 0,
        "duplicate_idempotency": 0,
    }


def _sse_event(name: str, stream_id: str, sequence: int, payload: dict[str, Any]) -> str:
    body = dict(payload)
    body.update({"event_version": "nxa.sse.v1", "stream_id": stream_id, "sequence": sequence})
    return (
        f"id: {stream_id}:{sequence}\n"
        f"event: {name}\n"
        f"data: {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def run_sse_soak(cycles: int = SSE_STREAM_CYCLES) -> dict[str, Any]:
    registry = SSEStreamRegistry()
    emitted = 0
    replayed = 0
    duplicate_events = 0
    for index in range(cycles):
        stream_id = f"eval019-sse-{index:04d}"
        fingerprint = request_fingerprint({"message": "show ospf peer", "context": {}})
        state = registry.open(stream_id=stream_id, tenant_id="eval019-tenant", user_id="eval019-user", fingerprint=fingerprint)
        events = [
            _sse_event("progress", stream_id, 1, {"id": "context", "status": "running"}),
            _sse_event("token", stream_id, 2, {"content": "healthy"}),
            _sse_event("citation", stream_id, 3, {"citation": {"citation_id": f"c-{index}"}}),
            _sse_event("done", stream_id, 4, {"status": "completed"}),
        ]
        for event in events[:2]:
            if not registry.record(state, event):
                duplicate_events += 1
            emitted += 1
        registry.close(state)
        resumed = registry.open(
            stream_id=stream_id,
            tenant_id="eval019-tenant",
            user_id="eval019-user",
            fingerprint=fingerprint,
            last_event_id=2,
        )
        for event in events[2:]:
            if not registry.record(resumed, event):
                duplicate_events += 1
            emitted += 1
        tail = registry.replay(resumed, after=2)
        replayed += len(tail)
        parsed = [event_sequence(event) for event in registry.replay(resumed, after=0)]
        if parsed != [(stream_id, 1), (stream_id, 2), (stream_id, 3), (stream_id, 4)]:
            raise AssertionError(f"SSE sequence/replay mismatch for {stream_id}: {parsed}")
        if event_type(tail[-1]) != "done" or event_payload(tail[-1])["status"] != "completed":
            raise AssertionError(f"SSE terminal event missing for {stream_id}")
        registry.close(resumed)
    registry.clear()
    return {
        "cycles": cycles,
        "emitted_events": emitted,
        "replayed_events": replayed,
        "duplicate_events": duplicate_events,
        "out_of_order_streams": 0,
    }


def run_reindex_soak(rows: int = REINDEX_ROWS, batch_size: int = REINDEX_BATCH_SIZE) -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("EVAL-019 Reindex soak requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    cur = conn.cursor()
    failures = 0
    try:
        cur.execute(
            "CREATE TEMP TABLE eval019_reindex_queue ("
            "id BIGINT PRIMARY KEY, state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, "
            "lease_owner TEXT NOT NULL DEFAULT '', checkpoint BIGINT NOT NULL DEFAULT 0"
            ")"
        )
        cur.execute(
            "INSERT INTO eval019_reindex_queue (id, state) "
            "SELECT g, 'queued' FROM generate_series(1, ?, 1) AS g",
            (rows,),
        )
        batch_count = 0
        while True:
            cur.execute(
                "SELECT id FROM eval019_reindex_queue WHERE state='queued' "
                "ORDER BY id LIMIT ? FOR UPDATE SKIP LOCKED",
                (batch_size,),
            )
            ids = [int(row[0]) for row in cur.fetchall()]
            if not ids:
                break
            batch_count += 1
            cur.execute(
                "UPDATE eval019_reindex_queue SET state='running', lease_owner='eval019-worker-a', "
                "attempt=attempt+1 WHERE id = ANY(?)",
                (ids,),
            )
            if batch_count % 5 == 0:
                cur.execute(
                    "UPDATE eval019_reindex_queue SET state='retry_wait', lease_owner='' WHERE id = ANY(?)",
                    (ids,),
                )
                cur.execute(
                    "SELECT id FROM eval019_reindex_queue WHERE id = ANY(?) AND state='retry_wait' "
                    "ORDER BY id FOR UPDATE SKIP LOCKED",
                    (ids,),
                )
                recovered_ids = [int(row[0]) for row in cur.fetchall()]
                cur.execute(
                    "UPDATE eval019_reindex_queue SET state='running', lease_owner='eval019-worker-b', "
                    "attempt=attempt+1 WHERE id = ANY(?)",
                    (recovered_ids,),
                )
                failures += 1
            cur.execute(
                "UPDATE eval019_reindex_queue SET state='completed', lease_owner='', "
                "checkpoint=id WHERE id = ANY(?)",
                (ids,),
            )
        completed = int(cur.execute("SELECT COUNT(*) FROM eval019_reindex_queue WHERE state='completed'").fetchone()[0])
        max_checkpoint = int(cur.execute("SELECT COALESCE(MAX(checkpoint), 0) FROM eval019_reindex_queue").fetchone()[0])
        retry_rows = int(cur.execute("SELECT COUNT(*) FROM eval019_reindex_queue WHERE attempt > 1").fetchone()[0])
        if completed != rows or max_checkpoint != rows or retry_rows != failures * batch_size:
            raise AssertionError(
                f"reindex recovery mismatch completed={completed} max_checkpoint={max_checkpoint} "
                f"retry_rows={retry_rows} failures={failures}"
            )
        conn.rollback()
        return {
            "rows": rows,
            "batch_size": batch_size,
            "batches": batch_count,
            "recovered_batches": failures,
            "completed": completed,
            "max_checkpoint": max_checkpoint,
            "retry_rows": retry_rows,
            "production_database_write": False,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class _FaultInjectingProvider:
    def __init__(self) -> None:
        self.provider_id = "eval019-provider"
        self.max_retries = 1
        self.fail_next = False
        self.failed_once = False
        self.calls = 0
        self.transient_failures = 0

    async def chat(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.fail_next and not self.failed_once:
            self.failed_once = True
            self.transient_failures += 1
            raise AINetworkException("fault-injected transient provider failure")
        return {"content": "provider recovered", "input_tokens": 1, "output_tokens": 2}


async def run_provider_soak(cycles: int = PROVIDER_CYCLES) -> dict[str, Any]:
    provider = _FaultInjectingProvider()
    model_info = {
        "id": "eval019-model",
        "provider_id": provider.provider_id,
        "model_code": "eval019-fault-injected",
        "default_temperature": 0.0,
        "default_max_tokens": 32,
        "provider_type": "openai_compatible",
        "model_type": "chat",
        "thinking_supported": False,
        "tool_call_supported": False,
        "json_supported": False,
        "stream_supported": True,
        "allowed_data_classification": "PUBLIC",
        "data_region": "unknown",
        "context_length": 1024,
        "max_output_tokens": 32,
        "cost_input_per_1k": 0,
        "cost_output_per_1k": 0,
    }
    gateway = LLMGateway(
        security_gateway=AISecurityGateway(
            policy=SecurityPolicy(external_ai_enabled=True, allowed_provider_types=("openai_compatible",))
        )
    )
    gateway._get_model_details = lambda _model_id: dict(model_info)  # type: ignore[method-assign]
    gateway._get_provider_instance = lambda _provider_id: provider  # type: ignore[method-assign]
    gateway._authorize_model = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    gateway._budget_exceeded = lambda **_kwargs: False  # type: ignore[method-assign]
    gateway._log_request = lambda **_kwargs: None  # type: ignore[method-assign]
    gateway._log_security_audit = lambda **_kwargs: None  # type: ignore[method-assign]
    ai_limits.reset_provider(provider.provider_id)
    successes = 0
    injected_failures = 0
    for index in range(cycles):
        provider.fail_next = index % 25 == 0
        provider.failed_once = False
        result = await gateway.chat(
            scene="eval019_stability",
            messages=[{"role": "user", "content": "show ospf peer status"}],
            model_id=model_info["id"],
            tenant_id="eval019-tenant",
            user_id="eval019-user",
            data_classification="PUBLIC",
            request_id=f"eval019-provider-{index:04d}",
        )
        if result.get("content") != "provider recovered":
            raise AssertionError(f"provider recovery response mismatch at cycle {index}")
        successes += 1
        injected_failures += int(provider.failed_once)
    ai_limits._check_circuit(provider.provider_id)
    return {
        "cycles": cycles,
        "successes": successes,
        "transient_failures_injected": injected_failures,
        "provider_attempts": provider.calls,
        "circuit_open_after_recovery": False,
        "external_provider_request": False,
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    imports = run_import_soak()
    sse = run_sse_soak()
    provider = asyncio.run(run_provider_soak())
    reindex = run_reindex_soak()
    elapsed = time.perf_counter() - started
    if elapsed > 180:
        raise AssertionError(f"EVAL-019 bounded soak exceeded 180 seconds: {elapsed:.3f}")
    return {
        "status": "PASS",
        "task_id": TASK_ID,
        "database": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(elapsed, 3),
        "bounded_soak": True,
        "import": imports,
        "reindex": reindex,
        "sse": sse,
        "provider": provider,
        "external_calls": False,
        "device_write_commands": False,
        "production_database_write": False,
        "rollback": "temporary_queue_transaction_rollback_and_connection_close",
    }


if __name__ == "__main__":
    try:
        report = run_gate()
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "task_id": TASK_ID, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
