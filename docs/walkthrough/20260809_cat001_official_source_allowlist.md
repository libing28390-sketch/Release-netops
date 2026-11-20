# CAT-001 Official Source Allowlist Walkthrough

## Outcome

CAT-001 is complete. The first knowledge-engineering catalog batch accepts only
Huawei CloudEngine 6800/VRP8 and Cisco Catalyst 9300/IOS-XE official sources.
The machine-readable contract is default-deny and enforces HTTPS/443, exact
host, registered path prefix, redirect revalidation, provenance, and V1-safe
rollback boundaries.

## Verification

- CAT-001 + DB-006 + DB-008 contract tests: 18 passed.
- V1 baseline: 10/10 cases; retrieval/citation accuracy and recall 1.0;
  wrong-vendor and version-conflict rates 0.
- `npm run lint`: PASS.
- `npm run build`: PASS (Vite emitted only the existing large-chunk warning).
- Compileall, YAML parse, `git diff --check`, and secret scan: PASS; 0 secret
  matches.

## Safety

No network device, remote source, PostgreSQL table, API, or frontend behavior
was mutated. Huawei Support's authenticated 403 is an access failure and does
not broaden the allowlist. CAT-003 will implement registry lifecycle, and
CAT-004 will enforce SSRF/redirect/security gates before activation.
