# Windows pgvector runtime asset

The Windows release workflow downloads the PostgreSQL 17 asset below into this
directory before creating the sanitized Windows release tree. The ZIP is not
stored in the source repository; the release job verifies its SHA-256 digest.

- Extension: pgvector `0.8.6`
- PostgreSQL: `17.x` (the asset was tested by its publisher with PostgreSQL 17.6)
- Asset: `vector.v0.8.6-pg17.zip`
- Source: <https://github.com/andreiramani/pgvector_pgsql_windows/releases/tag/0.8.6_17>
- SHA-256: `420388e9e9f05d92f06d6967ce8772483629b27a66ca9255925fa0fdd445438e`

The Windows launcher also supports PostgreSQL 13–18 and downloads the matching
pinned asset on demand when a release archive does not contain it.
