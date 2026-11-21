# DB-003 Lifecycle Behavior

## Contract summary

The lifecycle distinguishes visible active data, 禁用 records, 归档 records,
and irreversible 净化删除. 软删除 is a visibility transition and must not
be confused with `purged`; a `purged` record has its sensitive payload
removed according to the retention policy while its audit boundary remains.

## Migration and rollback

Lifecycle transitions are tenant-scoped and auditable. Reversible visibility
changes can be rolled back through an approved state transition. A 回滚 of a purged
payload is not reconstructed by rollback; the V1 audit and status evidence
remain intact.

## Final conclusion

The 软删除、禁用、归档、净化删除 and `purged` boundaries are documented for
V1 review.

Final Conclusion: PASS
