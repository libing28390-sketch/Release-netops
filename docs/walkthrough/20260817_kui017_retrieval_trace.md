# KUI-017 Retrieval Trace 管理员查看器

## 验证入口

进入 Knowledge Management（知识库管理），切换到 “Retrieval Trace / 追踪” 视图。完成一次 Copilot 或知识检索后点击刷新，列表会显示当前租户的检索摘要；点击一条记录可查看详情。

## 预期结果

- 列表按 `hit`、`no_match`、`not_run` 状态筛选，刷新和空态可用。
- 详情只展示 Trace/Query 哈希、请求实体、阶段计数、解析结果和引用元数据摘要。
- 页面明确显示默认脱敏；不显示 Query 正文、Chunk 正文、SQL、URL、文档/Chunk ID、用户名或凭据。
- 其他租户的 Trace ID 返回统一的 `RETRIEVAL_TRACE_NOT_FOUND`，不泄漏记录存在性。
- 当前读模型最多保存 200 条；服务重启后历史清空，持久化由后续 MIG-012 负责。

## 自动化验证

- 后端 Trace API、租户隔离、默认脱敏：`backend/tests/catalog/test_kui_017_retrieval_trace.py`
- PostgreSQL 环境探针：`scripts/knowledge_engine_v2_kui017_pg_probe.py`
- 前端列表、详情、空态：`src/pages/ai/Knowledge/RetrievalTracePanel.test.tsx`
