# 执行与验证报告：长会话扩容、BGE Reranker 精排与自动语义向量化

## 1. 完成摘要
已完成全部 3 项进阶优化并通过真实接口全链路实测验证：
1. **长会话历史窗口扩容**：`_HISTORY_POLICIES` 提升至 `public: 30轮/48K`、`network: 60轮/96K`、`complex: 100轮/110K`，兼顾 128K 上下文安全余量与长会话前缀缓存持续命中。
2. **接入 `BAAI/bge-reranker-v2-m3` 在线精排**：复用数据库中已配置的 SiliconFlow Provider，无须新 API Key；超时或不可用时自动无感降级。
3. **打通新上传文档自动语义向量化**：经实测，`KnowledgeService.add_document_and_chunk` 已通过 `semantic_embedding_provider()` 自动为新入库切片写入 1024 维 `embedding_v2`（`BAAI/bge-m3`）。

## 2. 实际修改文件
- `D:\netops\netsops-main\backend\ai\services\assistant.py`：调整 `_HISTORY_POLICIES`（第 90–94 行）。
- `D:\netops\netsops-main\backend\ai\providers\embedding.py`：新增 `rerank_documents(...)` 函数，调用已配置 Provider 的 `/rerank` 接口（默认模型 `BAAI/bge-reranker-v2-m3`，超时 5s 降级）。
- `D:\netops\netsops-main\backend\ai\services\rag_retriever.py`：在 `final_results >= 2` 且处于 `skipped`/`legacy_pass` 时调用 `rerank_documents` 精排，并将 `rerank_score` 与 `reranker` 调试信息写入结果。

## 3. 验证命令与结果
- 实测脚本 `verify_advanced_rag.py`：
  - `1. HISTORY_POLICIES: {'public': {'turns': 30, 'token_budget': 48000}, 'network': {'turns': 60, 'token_budget': 96000}, 'complex': {'turns': 100, 'token_budget': 110000}}`
  - `2. RERANKER DEBUG: {'stage': 'applied', 'provider': 'db_openai_compatible', 'model': 'BAAI/bge-reranker-v2-m3', 'reranked_count': 5, 'top_score': 0.9496}`
  - `TOP HITS: [('Huawei.vrp.troubleshooting.high_cpu_loop_and_ospf.md', 0.9496), ('Huawei.vrp.commands.core_reference.md', 0.0221), ...]`
  - `3. AUTO EMBEDDING_V2 ON UPLOAD: {'has_v2': True, 'embedding_v2_model': 'BAAI/bge-m3'}`（测试临时文档已清理）
  - 结果：`ALL_3_UPGRADES_VERIFIED_OK`

## 4. 剩余风险与回滚方式
- 如需临时关闭 Reranker，可设置环境变量 `AI_RERANKER_ENABLED=false`。
- 3 个修改文件均为独立增量变更，可按文件单独 `git checkout` 回滚。
