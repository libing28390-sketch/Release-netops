# Windows pgvector runtime asset

This directory contains the Windows pgvector asset for the PostgreSQL 18
baseline. The Windows release workflow downloads the same pinned asset before
creating the sanitized release tree and verifies its SHA-256 digest.

- Extension: pgvector `0.8.6`
- PostgreSQL: `18.x`
- Asset: `vector.v0.8.6-pg18.zip`
- Source: <https://github.com/andreiramani/pgvector_pgsql_windows/releases/tag/0.8.6_18>
- SHA-256: `bda17eb97d9e687e3da701adbf4b65a342943b3e0cdc81935ccf0b9833a1ed62`

The Windows launcher supports PostgreSQL 18 only. If the bundled asset is
missing, it downloads the same pinned asset on demand.
