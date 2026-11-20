# ING-008 document security-scan contract

ING-008 is a publication gate after the ING-007 content cleaner. It accepts a
`CleanedDocument` (or a non-HTML `ParsedDocument`) and returns a
`DocumentSecurityScanResult`. HTML that bypasses ING-007 fails closed. A clean
document has an explicit `allow` decision; an empty, suspicious or sensitive
document has `quarantine` and `publication_allowed: false`.

The local scanner looks at each structural block and the complete cleaned text.
It detects prompt-injection directives (instruction overrides, role
reassignment, control tags, jailbreak modes, secret-prompt requests and
tool-execution directives), knowledge-pollution signals (authority/source
override, no-verify/no-citation instructions, unverified authority claims,
conflicting vendor declarations), and sensitive credential/configuration
payloads through the existing classifier. Invisible Unicode obfuscation is
also isolated.

Findings are safe to audit: code, category, severity, bounded block locator
and a short SHA-256 evidence hash. No matched phrase, raw body, dependency
exception or filesystem path is returned. The result includes only a document
hash, reason codes and scanner identity. `isolate_document` is the named
enforcement entry point for ingestion workers; durable quarantine lifecycle is
owned by ING-015.

The scanner performs no network, filesystem or database operation. Rollback
keeps the quarantine gate and may disable only additive rules; suspicious
documents must never be published through an unscanned fallback.
