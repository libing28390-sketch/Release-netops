# ING-019 Official Source Change Detection

## Operational behavior

1. The scheduled source refresh performs the existing SSRF/DNS/TLS-safe fetch.
2. A first successful fetch establishes a baseline only.
3. A later same-hash response or `304` is non-destructive.
4. A later changed hash is recorded as `version_updated`; the source stays active
   until a later approval/publication workflow decides how to use the new version.
5. An official `404` or `410` is recorded as `removed`, creates a durable action,
   and quarantines the source plus linked published documents.
6. A material official redirect is recorded as `replacement` and follows the same
   action path. Equivalent URL normalization does not trigger quarantine.

## Operator checks

```text
GET /api/knowledge-v2/sources/{source_id}/refresh-observations?limit=50
```

Review `detection_type`, `http_status`, `content_hash`, `source_version_id`, and
the stable error code. Do not expect response bodies, provider headers, secrets,
or raw exception text in this endpoint.

## Recovery

If a document lifecycle transition fails, the action is retained as `failed` with
a stable error code. A later retry claims the same tenant-scoped action and is
idempotent. To halt behavior immediately, disable the refresh/change-action
writer; do not delete immutable observations or source versions.

## Release note

`m0121_knowledge_v2_source_change_detection` is additive and release-gated.
Apply it after `m0120` using the standard migration runner before enabling the
production writer. It does not alter V1 `ai_document` or `ai_document_chunk`.
