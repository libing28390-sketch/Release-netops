# ING-011 Walkthrough

## Flow

1. ING-010 supplies normalized metadata and its security/publication gate.
2. ING-011 rejects quarantined input before loading a catalog.
3. The resolver loads a read-only active snapshot for the requested tenant.
4. Exact model and exact/canonical Alias matches are bounded and deterministic.
5. Prefix, trigram, series, family, missing, and unknown values require review.
6. OS, generation, train, and release must match explicit reviewed scope.
7. Conflicts and dependency failures are returned as stable redacted outcomes.
8. Only a fully resolved result is retrieval eligible; no driver authority is granted.

## Compatibility

No migration or legacy row rewrite is performed. When the catalog service exposes
only its reviewed contract seed, the existing V1 RAG resolver remains in use and
now applies the request tenant predicate. A later DB-006/007/009 migration may
replace the seed adapter after its own gate.

## Verification target

`backend/tests/ai/test_ing011_entity_resolution.py` covers exact and canonical
matches, candidate ambiguity, unknown/body non-inference, vendor and OS conflict,
version review, tenant scope, seed handling, upstream quarantine, secret
redaction, and dependency failure.
