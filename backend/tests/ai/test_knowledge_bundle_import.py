import hashlib
import io
import json
import logging
import zipfile

import pytest

import ai.services.knowledge_bundle_import_service as bundle_module
from ai.services.knowledge_bundle_import_service import (
    KnowledgeBundleImportError,
    _read_bundle,
    import_knowledge_bundle,
)


def _bundle_documents(contents: list[str]) -> bytes:
    manifest_documents = []
    raw_documents = []
    for index, content in enumerate(contents, start=1):
        raw = content.encode()
        path = "documents/example.md" if len(contents) == 1 else f"documents/example-{index}.md"
        manifest_documents.append({
            "path": path,
            "name": f"example-{index}",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "content_bytes": len(raw),
            "vendor": "Huawei",
        })
        raw_documents.append((path, raw))
    manifest = {
        "schema_version": "knowledge-export-v1",
        "document_count": len(manifest_documents),
        "embeddings_exported": False,
        "reindex_required_on_import": True,
        "documents": manifest_documents,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for path, raw in raw_documents:
            archive.writestr(path, raw)
    return output.getvalue()


def _bundle(content: str = "---\n{\"vendor\": \"Huawei\"}\n---\n\nshow version\n") -> bytes:
    return _bundle_documents([content])


def _diagnostic_events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for record in caplog.records:
        message = record.getMessage()
        prefix = "knowledge_bundle_import "
        if not message.startswith(prefix):
            continue
        events.append(json.loads(message[len(prefix):]))
    return events


def test_export_bundle_manifest_and_hash_are_validated():
    manifest, documents = _read_bundle(_bundle())
    assert manifest["schema_version"] == "knowledge-export-v1"
    assert documents[0]["path"] == "documents/example.md"


def test_export_bundle_rejects_hash_tampering_before_database_work():
    data = bytearray(_bundle())
    # Rebuild the archive with a changed document but the original manifest.
    original = io.BytesIO(data)
    output = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w") as target:
        target.writestr("manifest.json", source.read("manifest.json"))
        target.writestr("documents/example.md", b"tampered")
    with pytest.raises(KnowledgeBundleImportError) as exc:
        _read_bundle(output.getvalue())
    assert exc.value.code == "KNOWLEDGE_BUNDLE_HASH_MISMATCH"


def test_export_bundle_rejects_path_traversal():
    raw = b"content"
    manifest = {
        "schema_version": "knowledge-export-v1",
        "document_count": 1,
        "embeddings_exported": False,
        "reindex_required_on_import": True,
        "documents": [{"path": "documents/../evil.md", "content_sha256": hashlib.sha256(raw).hexdigest(), "content_bytes": len(raw)}],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("documents/../evil.md", raw)
    with pytest.raises(KnowledgeBundleImportError) as exc:
        _read_bundle(output.getvalue())
    assert exc.value.code == "KNOWLEDGE_BUNDLE_PATH_INVALID"


def test_import_rejects_manifest_metadata_mismatch_before_any_database_work(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "ai.services.knowledge_bundle_import_service.knowledge_service.list_knowledge_bases",
        lambda **kwargs: calls.append("list") or [],
    )
    raw = "---\n{\"vendor\": \"Cisco\"}\n---\n\nshow version\n".encode()
    path = "documents/example.md"
    manifest = {
        "schema_version": "knowledge-export-v1",
        "document_count": 1,
        "embeddings_exported": False,
        "reindex_required_on_import": True,
        "documents": [{"path": path, "name": "example", "content_sha256": hashlib.sha256(raw).hexdigest(), "content_bytes": len(raw), "vendor": "Huawei"}],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(path, raw)
    with pytest.raises(KnowledgeBundleImportError) as mismatch:
        import_knowledge_bundle(output.getvalue(), tenant_id="tenant-b")
    assert mismatch.value.code == "KNOWLEDGE_BUNDLE_METADATA_MISMATCH"
    assert mismatch.value.details["reconciliation"]["metadata_mismatches"][0]["field"] == "vendor"
    assert calls == []


def test_import_failure_logs_stage_progress_and_rolls_back_without_secret(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    class FakeConnection:
        committed = False
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    connection = FakeConnection()
    calls: list[dict[str, object]] = []

    def fake_add_document(**kwargs):
        calls.append(kwargs)
        callback = kwargs["diagnostic_callback"]
        callback("embedding", "started", {"chunk_count": 1})
        if len(calls) == 2:
            raise RuntimeError("embedding dimension mismatch; password=supersecret")
        return {"document_id": f"doc-{len(calls)}"}

    monkeypatch.setattr(bundle_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(bundle_module.knowledge_service, "add_document_and_chunk", fake_add_document)
    caplog.set_level(logging.DEBUG, logger=bundle_module.logger.name)

    with pytest.raises(RuntimeError, match="supersecret"):
        import_knowledge_bundle(
            _bundle_documents([
                "---\n{\"vendor\": \"Huawei\"}\n---\n\nshow version 1\n",
                "---\n{\"vendor\": \"Huawei\"}\n---\n\nshow version 2\n",
            ]),
            tenant_id="tenant-diagnostic",
            knowledge_base_id="kb-diagnostic",
            request_id="web_diagnostic_001",
        )

    events = _diagnostic_events(caplog)
    failed = next(event for event in events if event.get("status") == "failed" and event.get("stage") == "embedding")
    assert failed["request_id"] == "web_diagnostic_001"
    assert failed["document_index"] == 2
    assert failed["processed_count"] == 1
    assert failed["transaction_state"] == "active"
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_summary"] == "embedding dimension mismatch; password=***"
    assert len(str(failed["document_ref"])) == 16
    assert "supersecret" not in json.dumps(failed, ensure_ascii=False)
    assert "documents/example-2.md" not in json.dumps(failed, ensure_ascii=False)

    rolled_back = next(event for event in events if event.get("status") == "rolled_back")
    assert rolled_back["transaction_state"] == "rolled_back"
    assert connection.rolled_back is True
    assert connection.committed is False


def test_bundle_validation_log_uses_stable_document_ref(caplog: pytest.LogCaptureFixture):
    data = bytearray(_bundle())
    original = io.BytesIO(data)
    output = io.BytesIO()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("manifest.json", source.read("manifest.json"))
        target.writestr("documents/example.md", b"tampered")

    caplog.set_level(logging.DEBUG, logger=bundle_module.logger.name)
    with pytest.raises(KnowledgeBundleImportError) as exc:
        import_knowledge_bundle(output.getvalue(), tenant_id="tenant-diagnostic", request_id="web_diagnostic_002")

    assert exc.value.code == "KNOWLEDGE_BUNDLE_HASH_MISMATCH"
    failed = next(event for event in _diagnostic_events(caplog) if event.get("status") == "failed")
    assert failed["stage"] == "read_bundle"
    assert failed["request_id"] == "web_diagnostic_002"
    assert failed["document_index"] == 1
    assert len(str(failed["document_ref"])) == 16
    assert failed["error_summary"] == "bundle_validation:KNOWLEDGE_BUNDLE_HASH_MISMATCH"
    assert "documents/example.md" not in json.dumps(failed, ensure_ascii=False)
