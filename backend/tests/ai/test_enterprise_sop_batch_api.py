from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import HTTPException, Response
from starlette.datastructures import Headers, UploadFile

from api import knowledge_ingestion


def _upload(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers=Headers({"content-type": content_type}))


def test_enterprise_sop_batch_returns_per_file_job_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_call(user, payload, *, content, filename, content_type):
        calls.append(filename)
        if filename == "broken.pdf":
            raise HTTPException(status_code=400, detail={"code": "IMPORT_FORMAT_INVALID", "message": "Invalid PDF"})
        return {"success": True, "continuation_required": True, "job": {"id": f"job-{filename}"}}

    monkeypatch.setattr(knowledge_ingestion, "_call_sop", fake_call)
    response = Response()
    result = asyncio.run(knowledge_ingestion.api_import_enterprise_sop_batch(
        response=response,
        files=[
            _upload("runbook.docx", b"PK\x03\x04document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            _upload("broken.pdf", b"%PDF-1.7 broken", "application/pdf"),
        ],
        owner="ops",
        department="noc",
        description="batch",
        request_id="req-1",
        max_retries=1,
        user={"id": "user-1", "tenant_id": "tenant-a", "role": "Admin"},
    ))

    assert response.status_code == 202
    assert calls == ["runbook.docx", "broken.pdf"]
    assert result["data"]["strategy"] == "file_level_commit"
    assert result["data"]["accepted"] == 1
    assert [item["status"] for item in result["data"]["items"]] == ["queued", "failed"]


def test_enterprise_sop_batch_rejects_empty_batch() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(knowledge_ingestion.api_import_enterprise_sop_batch(
            response=Response(),
            files=[],
            owner="",
            department="network-operations",
            description="batch",
            request_id="",
            max_retries=1,
            user={"id": "user-1", "tenant_id": "tenant-a", "role": "Admin"},
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SOP_BATCH_COUNT_INVALID"
