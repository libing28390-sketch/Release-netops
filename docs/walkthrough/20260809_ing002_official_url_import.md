# ING-002 walkthrough

## Request

`POST /api/knowledge-v2/ingestion/official-url` accepts one URL and reviewed
source metadata. The service performs URL/allowlist preflight before creating
or reusing a source row.

## Successful path

```text
accepted -> scoped -> CAT-001/DB-008 preflight -> active Source Registry
         -> CAT-004 safe_fetch -> immutable kb_source_version
         -> fetched (continuation_required=true)
```

The response has fetch metadata and the source-version hash, never the body.
Calling the same tenant/idempotency key again returns the existing version and
does not make a second HTTP request.

## Failure path

Unsafe URL syntax, unallowlisted host/path, missing review evidence, SSRF,
oversized responses, and provider failures are recorded as safe ING-001 error
codes. No parser or Published Document is claimed at this stage.

See [ING-002 Evidence](../knowledge-engine-v2/evidence/ING-002.md) and the
[ING-002 contract](../knowledge-engine-v2/architecture/ING-002-OFFICIAL-URL-IMPORT.yaml).
