# ING-003 URL security contract

ING-003 freezes the outbound boundary used by every Knowledge V2 URL import.
The implementation is deliberately shared with CAT-004 rather than creating a
second HTTP client: `validate_url_security` produces the canonical, redacted
decision and `safe_fetch` applies it immediately before every connection.

The boundary is fail-closed. Only an exact registered HTTPS host on port 443
and the registered path (or a descendant) is eligible. Userinfo, query and
fragment data, control characters, wildcard hosts, IP literals, and encoded
path separators are rejected. DNS answers are checked for every connection and
private, loopback, link-local, multicast, reserved, unspecified, non-global,
and cloud metadata addresses are denied. Environment proxy settings and
implicit redirect following are disabled.

Redirect responses are handled one hop at a time. The `Location` value is
canonicalized and checked against the original Source Registry row before the
next request. Cross-host redirects, HTTPS downgrade, path escapes, missing
locations, and hop-limit exhaustion fail without exposing the response body.

The response boundary validates content type and declared length before
streaming. Each chunk is checked before it is appended, and a wall-clock
deadline is checked during streaming. Retries are bounded to allowlisted 5xx
responses; 4xx responses are not retried. The resulting decision and errors
contain only bounded security facts, never headers, credentials, resolver
exception text, or body bytes.

See the machine-readable contract for the exact limits and the focused tests
for the negative matrix.
