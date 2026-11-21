# CAT-009 Alias Contract

CAT-009 implements persistence-neutral alias semantics for the future DB-006 `kb_product_alias` table:

```text
exact → canonical → prefix candidates → trigram candidates → UNKNOWN
```

Normalization is deterministic Unicode NFKC + casefold + whitespace collapse + dash-to-space, while the original alias remains an immutable evidence field. Exact/canonical collisions across models are `ambiguous_pending_review`; prefix and trigram are never unique identity. Tenant scope and active status are mandatory, and no first-match fallback is allowed.

The implementation lives in `backend/ai/services/product_alias_service.py`. It does not create production DDL; a later DB-006 migration/repository can persist the returned fields unchanged. Alias resolution never selects a network driver, credential or write authority.

Final Conclusion: PASS
