# DB-002 Common Column Semantics

## Contract summary

Common knowledge columns use UUID identity where applicable and keep
`tenant_id`, `created_at`, `updated_at`, `created_by`, and `status` semantics
consistent across the V1 projection. Typed fields are indexed for frequent
filters; structured extensions remain in JSONB with a documented ownership
boundary.

## Migration and rollback

PostgreSQL is authoritative. Tenant scope is checked on every read and write,
and status transitions are explicit. A 回滚 retains V1 values, records
the migration boundary, and does not delete source evidence.

## Final conclusion

UUID, tenant, lifecycle, PostgreSQL, V1, and rollback semantics are explicit.

Final Conclusion: PASS
