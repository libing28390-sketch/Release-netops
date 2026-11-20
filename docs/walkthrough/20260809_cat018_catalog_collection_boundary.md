# CAT-018 walkthrough

## Boundary demonstrated

1. `GET /api/knowledge-v2/catalog` returns official rows marked `official_catalog`, `read_only=true`, and `mutable=false`.
2. `GET /api/knowledge-v2/collections/boundary` exposes the immutable official/custom policy.
3. `POST /api/knowledge-v2/collections` creates a draft custom row with a server-generated ID and opaque catalog references.
4. `PATCH /api/knowledge-v2/collections/{collection_id}` requires the current `expected_updated_at` value.
5. `POST /api/knowledge-v2/collections/{collection_id}/archive` requires explicit `confirm=true`.

## Safety checks

- A catalog row cannot be mutated through the custom service or catalog router.
- A custom request cannot supply `collection_kind`, `official`, source identity, tenant identity, or unknown fields.
- Viewer actions are read-only; Platform Maintainer actions include create/update/archive.
- Cross-tenant reads do not reveal custom rows, and stale updates return a conflict.
- Audit failure does not commit an update or archive.

## Verification

See [CAT-018 Evidence](../knowledge-engine-v2/evidence/CAT-018.md) and the frozen contract [CAT-018-CATALOG-COLLECTION-BOUNDARY.yaml](../knowledge-engine-v2/architecture/CAT-018-CATALOG-COLLECTION-BOUNDARY.yaml).
