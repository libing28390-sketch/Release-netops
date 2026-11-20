# 2026-08-17 OBS-001 检索可观测性

## 验证目标

让一次回答的检索过程能回看规范化 query、实体、服务端 filters、候选排序分数和最终 Chunk 选择，同时不把原始 query 或知识正文写入审计/接口。

## 实现与验证

assistant 在请求边界构造 observation，trace store 生成 `nxa.retrieval.observation.v1`。raw query 只证明“已捕获”并保留哈希/长度；候选和最终 Chunk 只保留有界分数、上下文数量和 opaque hash。测试覆盖敏感 query、租户隔离和 100/50 上限；AI 236 项回归通过。

该取舍遵循已冻结的 DB-012/RET-001：raw query 不能进入 debug、audit 或数据库。
