# ING-011 Entity Resolution Contract

ING-011 consumes the validated result from ING-010 and resolves Product, OS,
release train, and software version only against an active catalog snapshot for
the authenticated tenant. The reviewed YAML seed remains read-only contract
material until the gated DB-006/007/009 migrations exist.

Resolution is fail-closed: a full active model or approved exact/canonical Alias
can be unique; series, prefix, trigram, missing, unknown, and conflicting values
produce bounded candidates or review outcomes. Body text, a software train, a
version string, or a CLI hint never selects a product or driver by itself.

The service is read-only and returns a structured outcome, stable issue codes,
bounded deterministic candidates, clarification fields, a metadata hash, and a
retrieval eligibility flag. It never returns credentials, raw document body,
source URLs, or exception text. `driver_selection_allowed` is always false.

The legacy RAG adapter remains available when only the contract seed is present;
its query is tenant-scoped and preserves the existing V1 retrieval behavior.
