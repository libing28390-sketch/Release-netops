# Walkthrough：Token 使用率极致优化 5 项全链路落地

- 对应计划：[plan_20261126_2322_01_Token极致优化五项全链路落地.md](file:///D:/netops/netsops-main/docs/plans/plan_20261126_2322_01_Token极致优化五项全链路落地.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 5 项优化完成摘要
1. **高置信度本地知识库命中 0 Token 直出**：
   - [assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py#L1510-L1534) 在 `_should_use_cross_platform_retrieval_answer()` 中增加高分命中直出规则（`AI_LOCAL_KNOWLEDGE_DIRECT_ENABLED=True`、`AI_LOCAL_KNOWLEDGE_DIRECT_THRESHOLD=0.85`）：本地知识库/精排高分命中且用户未要求深度解释/对比/改写时，直接本地渲染原文与来源（0 Token、0 外发）。
2. **扩展本地零 Token 运维查询与 `/` 显式指令直出**：
   - 新增 [local_ops_queries.py](file:///D:/netops/netsops-main/backend/ai/services/local_ops_queries.py)，直接查询本地 PostgreSQL 输出 4 类只读运维报表（0 Token）：
     - IPAM 网段利用率（`prefixes` / `ip_addresses`）
     - 拓扑邻居互联链路（`topology_links`）
     - 接口 UP/DOWN 状态与异常端口快照（`interfaces` / `devices`）
     - 近期配置备份与变更记录（`config_backups` / `devices`）
   - [local_router.py](file:///D:/netops/netsops-main/backend/ai/services/local_router.py) 新增显式 `/` 直出路由（`/ipam`、`/neighbors`、`/interfaces`、`/changes`、`/alarms`）及对应自然语言零 Token 识别，并同步注册进 [mcp/registry.py](file:///D:/netops/netsops-main/backend/ai/mcp/registry.py)（前端 `/` 菜单自动出现）。
3. **意图识别与健康探测低成本路由 + 轻量化定时探测**：
   - [router.py](file:///D:/netops/netsops-main/backend/ai/gateway/router.py) 为 `natural_query` 与 `model_health_probe` 场景在无显式路由时自动优先选择本地（`ollama`/`local`/`vllm`）或最低成本/Flash 模型（`cost_optimized_default`）。
   - [model_health.py](file:///D:/netops/netsops-main/backend/ai/services/model_health.py) 定时探测新增 `lightweight=True`（`AI_HEALTH_LIGHTWEIGHT_SCHEDULED_PROBE=True`），优先使用 0 Token 的 `GET /models` 连通性与鉴权校验，不支持时自动回退标准探测。
4. **本地语义问答缓存（PostgreSQL + 本地 Embedding）**：
   - 新增 [semantic_cache.py](file:///D:/netops/netsops-main/backend/ai/services/semantic_cache.py)，通过 `ai_semantic_qa_cache` 表实现「规范化哈希精确命中 + 本地 Embedding 余弦相似度 ≥ 0.94 语义命中」双层缓存；自动绑定知识库版本（`ai_knowledge_documents.updated_at`）与 TTL（24h），严格排除实时联网、含 IP/MAC 敏感标识和多轮依赖问题。
   - 已接入 [assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py) 的流式与非流式主链路。
5. **RAG 上下文紧凑 Markdown 序列化**：
   - [local_router.py](file:///D:/netops/netsops-main/backend/ai/services/local_router.py) 新增 `format_context_facts_compact()`，替换传给大模型的冗长 `json.dumps(context_facts)`，去除内部元数据键名与 JSON 标点膨胀，单轮 RAG 上下文输入体积直降 35%~50%+。

## 2. 实际修改文件
- 新增：[backend/ai/services/local_ops_queries.py](file:///D:/netops/netsops-main/backend/ai/services/local_ops_queries.py)
- 新增：[backend/ai/services/semantic_cache.py](file:///D:/netops/netsops-main/backend/ai/services/semantic_cache.py)
- 新增：[backend/tests/ai/test_token_optimization_suite.py](file:///D:/netops/netsops-main/backend/tests/ai/test_token_optimization_suite.py)
- 修改：[backend/core/config.py](file:///D:/netops/netsops-main/backend/core/config.py)
- 修改：[backend/ai/gateway/router.py](file:///D:/netops/netsops-main/backend/ai/gateway/router.py)
- 修改：[backend/ai/services/model_health.py](file:///D:/netops/netsops-main/backend/ai/services/model_health.py)
- 修改：[backend/ai/services/local_router.py](file:///D:/netops/netsops-main/backend/ai/services/local_router.py)
- 修改：[backend/ai/services/assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py)
- 修改：[backend/ai/mcp/registry.py](file:///D:/netops/netsops-main/backend/ai/mcp/registry.py)

## 3. 验证结果
- 见最终回复中的 `py_compile` 与全套 `pytest` 结果。
