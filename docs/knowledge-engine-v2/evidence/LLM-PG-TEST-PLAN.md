# LLM PostgreSQL 测试方案证据

Task ID: LLM-001..LLM-037

## 目标

将 AI 供应商、模型、路由、权限、密钥轮换、配额和审计的数据库验收统一到实际 PostgreSQL。项目不使用 SQLite 作为验收数据库；现有 SQLite 兼容性测试仅保留为非门禁遗留检查，不计入 LLM 任务通过数。

## 执行入口

- `scripts/knowledge_engine_v2_llm_pg_probe.py`
- `scripts/knowledge_engine_v2_v1_baseline_pg.py`
- `backend/tests/ai/test_llm_001_037_multi_provider.py`
- `npm.cmd run lint`
- `npm.cmd run build`

## 数据库与回滚

所有迁移/夹具验证在 PostgreSQL 事务中执行并回滚；禁止删除生产数据。必须记录 PostgreSQL 版本、`vector`/`pg_trgm` 版本、迁移版本和实际命令。

## 判定

只有真实 PostgreSQL 连接、SQL/索引/约束/租户隔离与回滚均通过，且前后端和安全检查通过，任务才能标记 PASS。缺少 PostgreSQL、扩展、凭据或权限时标记 BLOCKED，禁止以 SQLite 结果替代。

V1 PostgreSQL 基线已执行：10/10，retrieval_accuracy=1.0，wrong_vendor_rate=0.0，version_conflict_rate=0.0，citation_accuracy=1.0，事务回滚 PASS。PostgreSQL 18.4，vector 0.8.6，pg_trgm 1.6。

LLM PostgreSQL 契约探针已执行 PASS：m0139/m0140/m0141 幂等、Provider 多实例、Provider+Model 唯一边界、Fallback、租户 ACL、密钥轮换审计、用户默认模型、usage scope 和事务回滚均通过。
AI 合同测试：8 passed；AI/CIT/RET 回归：31 passed；Python 编译：PASS；前端 TypeScript lint：PASS；Vite production build：PASS（仅保留既有大 chunk warning）。SQLite 未执行、未计入任何门禁或任务统计。

最终状态：PASS
