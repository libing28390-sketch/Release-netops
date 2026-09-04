# DB-021 Consistency and Orphan Contract

## Contract summary

The consistency patrol is a PostgreSQL read-only inspection of foreign-key
and `pg_constraint` relationships. It reports orphan candidates without
repairing rows in place. Tenant IDs and SHA-256 evidence identify the scope
of a scan and make the result reproducible.

## Operations and rollback

The scheduled window is `02:25`; the patrol is `read-only` and may report
`NOT_APPLICABLE` when a relation is outside the current contract. Any repair
must be an independently approved migration; rollback therefore preserves
the scan evidence and does not perform an implicit delete.

## Final conclusion

The DB-021 pg_constraint, PostgreSQL, NOT_APPLICABLE, tenant_id, SHA-256,
read-only, 02:25, V1, and 回滚 evidence is present.

Final Conclusion: PASS
