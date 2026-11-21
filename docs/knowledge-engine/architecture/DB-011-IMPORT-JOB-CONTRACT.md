# DB-011 Import Job Contract

## Contract summary

An Import Job records `execution_state`, `phase`, progress, retry (重试),
cancel (取消), error (错误), and progress details (进度). The service API exposes `def create_job`,
`def run_job`, `def retry`, and `_record_failure`; embedding failures are
represented explicitly as `embedding_failed`. `kb_import_job` is the
source-import boundary and `ai_knowledge_reindex_job` is the reindex boundary.

## Security and rollback

Job ownership is tenant- and RBAC-scoped. A cancelled or failed job does not
publish partial retrieval content. 回滚 removes the unpublished generation,
leaves the source version auditable, and keeps V1/DB-012 trace boundaries.

## Final conclusion

The Import Job, tenant, RBAC, retry/cancel/error/progress, DB-012, V1, and
回滚 evidence are present.

Final Conclusion: PASS
