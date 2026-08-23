import hashlib
import io
import json
import zipfile

import pytest

from ai.services.knowledge_bundle_import_service import (
    KnowledgeBundleImportError,
    _read_bundle,
    import_knowledge_bundle,
)


def _bundle(content: str = "---\n{\"vendor\": \"Huawei\"}\n---\n\nshow version\n") -> bytes:
    raw = content.encode()
    path = "documents/example.md"
    manifest = {
        "schema_version": "knowledge-export-v1",
        "document_count": 1,
        "embeddings_exported": False,
        "reindex_required_on_import": True,
        "documents": [{
            "path": path,
            "name": "example",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "content_bytes": len(raw),
            "vendor": "Huawei",
        }],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(path, raw)
    return output.getvalue()


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
