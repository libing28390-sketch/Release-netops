# API-001 API 边界走查

## 入口

- `GET /api/v2/kb`：读取 Knowledge Engine V2 canonical manifest。
- `GET /api/knowledge-v2`：验证旧客户端兼容别名仍返回同一 manifest。
- `/api/v2/kb/{resource}`：验证 sources、documents、catalog、collections、ingestion、evaluation、retrieval-traces 请求都经过同一 V2 handler 和租户/RBAC 依赖。
- `/api/v1/ai/chat`、`/api/v1/ai/chat/stream`：保持 `nxa.ai.v1` 请求、响应和 SSE 事件合同。

## 验收点

1. canonical 和兼容路径合同均为 `nxa.kb.v2`，兼容路径不复制业务逻辑。
2. 请求携带 `X-Request-ID` 时，响应回传同一个 ID；日志上下文继续使用该 ID。
3. V2 Knowledge 请求不会回退到 V1 AI Chat，V1 Chat 也不暴露知识库内部存储字段。
4. 前端知识 API 统一调用 `/api/v2/kb`，旧路径只用于兼容已有外部客户端。

自动化证据：`backend/tests/ai/test_api_v2_boundary.py` 2 passed；`scripts/knowledge_engine_v2_api001_probe.py` PASS。
