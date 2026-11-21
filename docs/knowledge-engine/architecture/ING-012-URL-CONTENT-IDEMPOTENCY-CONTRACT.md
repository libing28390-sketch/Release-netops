# ING-012 URL/Content Idempotency Contract

At the source-version write boundary, the identity is the authenticated tenant,
the canonical Source Registry URL, and the server-computed SHA-256 content hash.
If the same tenant and URL produce the same hash, ING-012 returns the existing
source version and marks the result `replay_same_url_same_content`; it never
creates a duplicate version or document write. This remains true when the two
requests use different caller idempotency keys.

A changed hash is a new version boundary and is handed to ING-013. The existing
m0116 unique tenant/source/hash constraint and transaction remain the database
guard; ING-012 adds only a stable decision object and response fields. No
production DDL or data rewrite is performed.

The hash is known only after the CAT-004 safe fetch, so this task does not claim
to suppress a second network request. ETag/Last-Modified conditional refresh is
the explicit ING-018 responsibility. Responses never include source bytes,
credentials, or raw exception text.
