# ING-008 walkthrough

1. Ingestion passes the `CleanedDocument` from ING-007 to
   `scan_document_security`; raw HTML cannot bypass cleaning.
2. Rules run over each block and the complete normalized text. Prompt Injection
   and knowledge-pollution indicators are mapped to stable rule IDs; existing
   credential/private-key/full-dump classification is reused for sensitive
   knowledge payloads.
3. A finding stores only category, severity, bounded source locator and a
   short evidence hash. The matched text is never returned or persisted by
   this service.
4. Any finding produces `quarantined`, `decision=quarantine` and
   `publication_allowed=false`. Empty cleaned output follows the same gate.
5. A document without findings is `clean` and explicitly allowed. Durable
   source lifecycle/quarantine state remains the responsibility of ING-015.

Focused verification is in
`backend/tests/ai/test_ing008_document_security_scan.py`.
