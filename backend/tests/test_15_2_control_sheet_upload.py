"""
Task 15.2 — Unit tests for POST /api/change-orders/{order_id}/control-sheet

Tests the new control-sheet upload endpoint:
  - MIME whitelist enforcement (pdf/doc/docx/xlsx only)
  - File size limit (≤ 20 MiB)
  - Status restriction (approved/implementing/completed/rolled_back)
  - Authorization (requester or Administrator only)
  - Successful upload persists row + emits audit event
  - Returns correct attachment metadata

Validates: Property 2 (design.md §Correctness Properties)
Requirements: 2.5
"""

from __future__ import annotations

import io
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────

def _make_upload_file(
    filename: str,
    content: bytes,
    content_type: str,
) -> MagicMock:
    """Create a mock UploadFile that behaves like FastAPI's UploadFile."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.content_type = content_type
    # read() is a coroutine in FastAPI
    mock_file.read = AsyncMock(return_value=content)
    return mock_file


def _invoke_upload(
    order_id: str,
    file_mock,
    actor: dict,
    note: str | None = None,
) -> tuple[int, object]:
    """Invoke api_upload_control_sheet and return (status_code, data_or_detail)."""
    import asyncio
    from fastapi import HTTPException
    from api.change_orders import api_upload_control_sheet

    async def _run():
        return await api_upload_control_sheet(
            order_id=order_id,
            file=file_mock,
            note=note,
            user=actor,
        )

    try:
        result = asyncio.get_event_loop().run_until_complete(_run())
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _create_approved_order(requester: dict, initial_reviewer: dict, final_approver: dict) -> str:
    """Create an order and drive it to 'approved' status, returning the order_id."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order, api_transition_change_order

    # Create draft
    body = ChangeOrderCreate(
        title="Control sheet upload test order",
        status="draft",
        assigned_initial_reviewer_id=initial_reviewer["user_id"],
        command_template={},
        commands=["show version"],
        rollback_plan="rollback",
    )
    result = api_create_change_order(body, user=requester)
    order_id = result["data"]["id"]

    # draft → initial_review
    api_transition_change_order(
        order_id,
        body={"status": "initial_review"},
        user=requester,
    )
    # initial_review → final_review
    api_transition_change_order(
        order_id,
        body={
            "status": "final_review",
            "assigned_final_approver_id": final_approver["user_id"],
        },
        user=initial_reviewer,
    )
    # final_review → approved
    api_transition_change_order(
        order_id,
        body={"status": "approved"},
        user=final_approver,
    )
    return order_id


# ── Tests ─────────────────────────────────────────────────────────────

class TestControlSheetUploadMimeValidation:
    """MIME whitelist enforcement."""

    def test_pdf_accepted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("report.pdf", b"%PDF-1.4 test content", "application/pdf")
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200, f"PDF should be accepted, got {status_code}: {data}"
        assert data["filename"] == "report.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size_bytes"] == len(b"%PDF-1.4 test content")

    def test_docx_accepted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        f = _make_upload_file("doc.docx", b"PK fake docx content", mime)
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200, f"DOCX should be accepted, got {status_code}: {data}"

    def test_xlsx_accepted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        f = _make_upload_file("sheet.xlsx", b"PK fake xlsx content", mime)
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200, f"XLSX should be accepted, got {status_code}: {data}"

    def test_exe_rejected(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("malware.exe", b"MZ fake exe", "application/x-msdownload")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 400, "EXE (application/x-msdownload) must be rejected"

    def test_zip_rejected(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("archive.zip", b"PK fake zip", "application/zip")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 400, "ZIP must be rejected"

    def test_unknown_mime_with_pdf_extension_accepted(
        self, isolated_db, requester, initial_reviewer, final_approver, tmp_path
    ):
        """When client sends empty/wrong MIME but extension is .pdf, fall back to extension."""
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("report.pdf", b"%PDF-1.4 content", "application/octet-stream")
        # octet-stream is not in whitelist, but .pdf extension should resolve it
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200, f"PDF by extension should be accepted, got {status_code}: {data}"
        assert data["mime_type"] == "application/pdf"


class TestControlSheetUploadSizeLimit:
    """File size enforcement (≤ 20 MiB)."""

    def test_small_file_accepted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        content = b"%PDF-1.4 " + b"x" * 1024  # 1 KiB
        f = _make_upload_file("small.pdf", content, "application/pdf")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200

    def test_oversized_file_rejected(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        # 20 MiB + 1 byte
        content = b"x" * (20 * 1024 * 1024 + 1)
        f = _make_upload_file("big.pdf", content, "application/pdf")
        status_code, detail = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 400, "File > 20 MiB must be rejected"
        assert "20 MiB" in str(detail) or "超过" in str(detail)

    def test_empty_file_rejected(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("empty.pdf", b"", "application/pdf")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 400, "Empty file must be rejected"


class TestControlSheetUploadStatusRestriction:
    """Order status must be in {approved, implementing, completed, rolled_back}."""

    def test_draft_order_rejected(self, isolated_db, requester, initial_reviewer, tmp_path):
        from api.change_orders import ChangeOrderCreate, api_create_change_order

        body = ChangeOrderCreate(
            title="Draft order",
            status="draft",
            assigned_initial_reviewer_id=initial_reviewer["user_id"],
            command_template={},
            commands=["show version"],
        )
        result = api_create_change_order(body, user=requester)
        order_id = result["data"]["id"]

        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, detail = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 400, f"Draft order must reject upload, got {status_code}"
        assert "draft" in str(detail).lower() or "状态" in str(detail)

    def test_approved_order_accepted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200

    def test_nonexistent_order_returns_404(self, isolated_db, requester, tmp_path):
        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, _ = _invoke_upload("nonexistent-id", f, actor=requester)
        assert status_code == 404


class TestControlSheetUploadAuthorization:
    """Only requester or Administrator can upload."""

    def test_requester_can_upload(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, _ = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200

    def test_administrator_can_upload(self, isolated_db, requester, initial_reviewer, final_approver, make_user, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        admin = make_user("admin_user", role="Administrator", change_groups=["final_approver"])
        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, _ = _invoke_upload(order_id, f, actor=admin)
        assert status_code == 200

    def test_other_operator_cannot_upload(self, isolated_db, requester, initial_reviewer, final_approver, make_user, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        other = make_user("other_operator", role="Operator", change_groups=["initial_reviewer"])
        f = _make_upload_file("doc.pdf", b"%PDF content", "application/pdf")
        status_code, detail = _invoke_upload(order_id, f, actor=other)
        assert status_code == 403, f"Non-requester Operator must be rejected, got {status_code}"


class TestControlSheetUploadPersistence:
    """Successful upload persists row and emits audit event."""

    def test_attachment_row_persisted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        from database import get_db_connection

        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("control.pdf", b"%PDF-1.4 content", "application/pdf")
        status_code, data = _invoke_upload(order_id, f, actor=requester, note="Initial upload")
        assert status_code == 200

        # Verify row in DB
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM change_order_control_sheet_attachments WHERE id = ?",
                (data["id"],),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "Attachment row must be persisted in DB"
        assert row["order_id"] == order_id
        assert row["file_name"] == "control.pdf"
        assert row["file_size"] == len(b"%PDF-1.4 content")

    def test_audit_event_emitted(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        from database import get_db_connection

        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        f = _make_upload_file("control.pdf", b"%PDF-1.4 content", "application/pdf")
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200

        # Verify audit event
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM audit_events WHERE event_type = 'change_order.control_sheet_uploaded' AND target_id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "Audit event must be emitted"
        assert row["actor_username"] == requester["username"]

    def test_response_contains_metadata(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        content = b"%PDF-1.4 test"
        f = _make_upload_file("sheet.pdf", content, "application/pdf")
        status_code, data = _invoke_upload(order_id, f, actor=requester, note="test note")
        assert status_code == 200
        assert "id" in data
        assert data["filename"] == "sheet.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size_bytes"] == len(content)
        assert "uploaded_at" in data
        assert data["note"] == "test note"

    def test_file_stored_on_disk(self, isolated_db, requester, initial_reviewer, final_approver, tmp_path):
        from database import get_db_connection

        order_id = _create_approved_order(requester, initial_reviewer, final_approver)
        content = b"%PDF-1.4 stored content"
        f = _make_upload_file("stored.pdf", content, "application/pdf")
        status_code, data = _invoke_upload(order_id, f, actor=requester)
        assert status_code == 200

        # Verify file exists on disk
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT file_path FROM change_order_control_sheet_attachments WHERE id = ?",
                (data["id"],),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None
        assert os.path.exists(row["file_path"]), "File must be stored on disk"
        with open(row["file_path"], "rb") as fh:
            assert fh.read() == content
