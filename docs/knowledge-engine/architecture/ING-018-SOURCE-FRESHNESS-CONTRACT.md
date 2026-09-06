# ING-018 Source Freshness Contract

## Scope

ING-018 adds a bounded periodic freshness check for active, validated Source
Registry entries. The check reuses the CAT-004 outbound security boundary and
does not change the V1 `ai_document` path.

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

APScheduler registers `knowledge_source_freshness_refresh` every 30 minutes,
with the existing `scheduler_locks` cross-instance lock and a 100-source
default batch (maximum 500). A source failure does not abort the rest of the
batch. Operators can inspect bounded history through
`GET /api/knowledge-v2/sources/{source_id}/refresh-observations`.

Rollback disables the scheduler/writer and retains the append-only timeline;
no V1 row or immutable source fact is deleted or rewritten.

