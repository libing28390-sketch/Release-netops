# CAT-013 Product Catalog Management Contract

CAT-013 exposes the reviewed product hierarchy and Alias conflict queue to authorized operators. Until the DB-006 physical catalog migration is released, the UI and API are deliberately read-only adapters over the reviewed CAT-005, CAT-006, and CAT-010 seed artifacts.

The API is tenant-scoped and exposes only `GET /api/knowledge-v2/catalog`, `GET /api/knowledge-v2/catalog/aliases`, and the dry-run `POST /api/knowledge-v2/catalog/resolve`. No catalog write route, migration, driver selection, credential selection, or write-command authorization is introduced. Ambiguous aliases remain candidates and require clarification; draft seed rows are labelled as draft.

The management tab displays the persistence boundary, product hierarchy, Alias queue, conflict state, and resolver outcome. Input bounds and control characters fail closed, and unavailable/malformed seed artifacts return a stable service error rather than a partial catalog.
