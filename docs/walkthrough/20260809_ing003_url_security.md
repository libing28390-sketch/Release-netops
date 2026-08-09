# ING-003 walkthrough

```text
ING-002 URL request
      |
      v
canonical URL + CAT-001 host/path preflight (no DNS)
      |
      v
fresh DNS/SSRF decision immediately before each connection
      |
      +--> 3xx: canonicalize Location -> revalidate same host/path -> next hop
      |
      +--> 2xx: content type + declared length -> bounded streaming/deadline
      |
      v
hash-only Source Version manifest; no body in API/audit
```

`validate_url_security` is the single decision function. `safe_fetch` calls it
for the initial target and for every retry/redirect attempt, so DNS answers are
not trusted across time. The focused tests use `httpx.MockTransport`; they do
not contact vendor sites.

See [ING-003 Evidence](../knowledge-engine-v2/evidence/ING-003.md) and the
[ING-003 contract](../knowledge-engine-v2/architecture/ING-003-URL-SECURITY-CONTRACT.yaml).
