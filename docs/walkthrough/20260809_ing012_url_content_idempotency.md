# ING-012 Walkthrough

1. Canonicalize and validate the URL through the existing source registry gate.
2. Use a stable URL-derived default request key when the caller supplies none.
3. Fetch through CAT-004 and compute the server-owned SHA-256 hash.
4. Ask the pure idempotency service for the tenant/source/content decision.
5. Reuse an existing version for the same URL and hash, and expose replay metadata.
6. Create a new version for a changed hash; ING-013 owns document-version behavior.
7. Keep all reads and writes tenant-scoped and transactional.

The implementation is additive and V1-safe. It does not suppress a network fetch
because content identity is unknown until the safe fetch completes; refresh
validators belong to ING-018.
