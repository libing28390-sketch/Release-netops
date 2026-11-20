# ING-018 Source Freshness Contract

## Scope

ING-018 defines freshness handling for user-initiated Source Registry fetches.
There is no periodic source refresh: external URLs are accessed only when a
user explicitly imports or refreshes a source. The fetch reuses the CAT-004
outbound security boundary and does not change the V1 `ai_document` path.

## Immutable facts and observations

`kb_source_version` remains append-only. A conditional `304 Not Modified`, or
a `200` response whose SHA-256 already exists, must not rewrite
`source_etag`, `source_last_modified`, or `content_hash` on an old version.
Each check appends an ID-only, hash-only observation to
`kb_source_refresh_observation`. A changed hash appends one new source version
through the existing Source Registry write boundary and records the same
observation.

The response body is held only in memory long enough to compute its hash. It is
never returned in the refresh result, observation, or audit payload.

## Conditional request and outcome rules

Only server-owned values from the newest fetched/verified source version are
sent as `If-None-Match` and `If-Modified-Since`. Arbitrary request headers are
rejected. `304` without a known immutable baseline fails closed. The stable
outcomes are:

- `not_modified`: 304, no source-version insert, observation references the prior version hash.
- `unchanged`: 200, source-version insert is deduplicated by `(tenant_id, source_registry_id, content_hash)`.
- `changed`: 200, a new immutable source version is appended.
- `failed`: no source-version write; only a stable redacted error code is retained.

## Operations

No APScheduler job is registered for source freshness and the backend does not
poll saved source URLs. Operators can explicitly fetch one source through
`POST /api/knowledge-v2/sources/{source_id}/fetch` and inspect bounded history through
`GET /api/knowledge-v2/sources/{source_id}/refresh-observations`.

The append-only observation timeline remains available for explicit fetches;
no V1 row or immutable source fact is deleted or rewritten.
