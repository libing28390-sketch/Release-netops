# CAT-015 Catalog Versioning Walkthrough

1. Build a complete bundle containing `version`, all `models`, and all `aliases` for the authenticated tenant.
2. Call `POST /api/knowledge-v2/catalog/versions/preview`. Confirm `dry_run: true`, validation status, the baseline/candidate hashes, and bounded model/Alias diff counts.
3. Call `POST /api/knowledge-v2/catalog/versions/import` with the preview's `baseline.version_id` and `confirm: true`. The response returns the active version and a rollback target.
4. Call `GET /api/knowledge-v2/catalog/versions` to verify active/history pointers and the redacted audit event.
5. Call `POST /api/knowledge-v2/catalog/versions/{rollback_target}/rollback` with the active version and `confirm: true`. Confirm the prior snapshot is active again and history remains present.
6. Repeat an import with a stale `expected_active_version_id`, a missing confirmation, a cross-tenant row, or an active ambiguous Alias; each path fails closed.
