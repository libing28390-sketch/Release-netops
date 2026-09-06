# CAT-011 Alias Conflict and Human Adjudication

CAT-011 adds the backend decision boundary on top of CAT-009. Every candidate
response is tenant-scoped and bounded to one row per product model. A
cross-model exact/canonical collision remains `ambiguous` until a reviewer
chooses one record; prefix and trigram matches remain candidate-only even
after review.

The adjudication service supports `approve`, `reject`, and `reset`. Approval
selects exactly one record, marks competing records rejected, preserves the
alias lifecycle, and records reviewer ID, timestamp, and a non-secret note.
Rejection makes the group resolve as `UNKNOWN`; reset returns it to
`pending_review`. No action grants a network driver or device write authority.

CAT-011 is persistence-neutral and creates no production DDL. A later catalog
migration may persist the immutable records and audit result without changing
the matching contract.

Final Conclusion: PASS
