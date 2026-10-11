from __future__ import annotations

import hashlib

import httpx
import pytest


def _internal_payload(url: str = "https://kb.internal.example/docs/manifest") -> dict:
    return {
        "source_type": "internal",
        "source_kind": "internal",
        "canonical_url": url,
        "name": "ING-009 fixture",
        "metadata": {"owner": "network-team"},
    }


def _public(*_args):
    return ["93.184.216.34"]


def _transport(handler):
    return httpx.MockTransport(handler)


def test_ing009_record_source_version_persists_server_owned_manifest(isolated_db, make_user):
    from services.source_registry_service import create_source, enable_source, record_source_version
    from services.source_version_manifest_service import validate_source_version_manifest

    operator = make_user("ing009-manifest", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload(), operator)
    enable_source(source["id"], operator)
    body = b"immutable source body"
    version = record_source_version(
        source["id"],
        {
            "content": body,
            "fetched_at": "2026-08-10T06:00:00+00:00",
            "parser_name": "nexora-txt",
            "parser_version": "1.0.0",
            "source_etag": '"manifest-v1"',
            "source_last_modified": "Mon, 10 Aug 2026 06:00:00 GMT",
            "fetch_url": "https://kb.internal.example/docs/manifest",
            "response_content_type": "text/plain",
            "http_status": 200,
            "verification_method": "ing009_test_v1",
            "metadata": {"collector": "fixture"},
            "status": "fetched",
        },
        operator,
    )
    manifest = version["metadata"]["source_manifest"]
    assert manifest["manifest_version"] == "1.0"
    assert manifest["source"]["registry_id"] == source["id"]
    assert manifest["source"]["canonical_url"] == source["canonical_url"]
    assert manifest["capture"] == {
        "fetched_at": "2026-08-10T06:00:00+00:00",
        "content_hash": hashlib.sha256(body).hexdigest(),
        "byte_size": len(body),
    }
    assert manifest["http"] == {
        "fetch_url": source["canonical_url"],
        "status": 200,
        "content_type": "text/plain",
        "etag": '"manifest-v1"',
        "last_modified": "Mon, 10 Aug 2026 06:00:00 GMT",
    }
    assert manifest["parser"] == {"name": "nexora-txt", "version": "1.0.0"}
    assert manifest["raw_content"]["storage"] == "hash_only_memory_boundary"
    assert "content" not in manifest
    assert validate_source_version_manifest(manifest) == manifest


def test_ing009_collect_source_captures_http_headers_and_fetch_time(isolated_db, make_user):
    from services.source_registry_service import collect_source, create_source, enable_source

    operator = make_user("ing009-http", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload("https://kb.internal.example/docs/http"), operator)
    enable_source(source["id"], operator)
    body = b"http manifest"
    result = collect_source(
        source["id"],
        {"method": "GET"},
        operator,
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8", "etag": '"v2"', "last-modified": "Tue, 11 Aug 2026 06:00:00 GMT"}, content=body, request=request)),
        resolver=_public,
    )
    manifest = result["version"]["metadata"]["source_manifest"]
    assert manifest["capture"]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert manifest["capture"]["byte_size"] == len(body)
    assert manifest["capture"]["fetched_at"]
    assert manifest["http"]["status"] == 200
    assert manifest["http"]["content_type"] == "text/plain"
    assert manifest["http"]["etag"] == '"v2"'
    assert manifest["parser"]["name"] == "html"
    assert manifest["parser"]["version"] == "1.0.0"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"http_status": 99}, "MANIFEST_HTTP_STATUS_INVALID"),
        ({"fetched_at": "2026-08-10T06:00:00"}, "MANIFEST_CAPTURE_TIME_INVALID"),
        ({"raw_content_ref": "C:\\secrets\\source.txt"}, "MANIFEST_RAW_REFERENCE_FORBIDDEN"),
    ],
)
def test_ing009_manifest_rejects_unbounded_or_unsafe_facts(isolated_db, make_user, changes, code):
    from services.source_registry_service import SourceRegistryError, create_source, enable_source, record_source_version

    operator = make_user("ing009-negative", role="Administrator", tenant_id="tenant-default")
    source = create_source(_internal_payload(f"https://kb.internal.example/docs/{code.lower()}"), operator)
    enable_source(source["id"], operator)
    payload = {"content": b"negative", "parser_name": "nexora-txt", "parser_version": "1.0.0", "status": "fetched"}
    payload.update(changes)
    with pytest.raises(SourceRegistryError) as exc:
        record_source_version(source["id"], payload, operator)
    assert exc.value.code == code


def test_ing009_manifest_helper_never_accepts_body_or_filesystem_reference():
    from services.source_version_manifest_service import SourceVersionManifestError, build_source_version_manifest

    source = {"id": "source-1", "tenant_id": "tenant-1", "canonical_url": "https://docs.example/guide"}
    with pytest.raises(SourceVersionManifestError) as exc:
        build_source_version_manifest(
            source,
            content_hash="a" * 64,
            byte_size=1,
            fetched_at="2026-08-10T06:00:00+00:00",
            parser_name="p",
            parser_version="1",
            fetch_url="https://docs.example/guide",
            raw_content_ref="D:\\raw\\body.bin",
        )
    assert exc.value.code == "MANIFEST_RAW_REFERENCE_FORBIDDEN"


def test_ing009_api_contract_keeps_manifest_fields_explicit():
    from api.knowledge_sources import SourceVersionCreateRequest

    fields = SourceVersionCreateRequest.model_fields
    assert {"content_hash", "byte_size", "fetched_at", "parser_name", "parser_version", "source_etag", "source_last_modified", "fetch_url", "response_content_type", "http_status", "raw_content_storage", "verification_method"} <= set(fields)
