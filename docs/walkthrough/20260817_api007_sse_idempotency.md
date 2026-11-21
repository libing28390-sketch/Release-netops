# 2026-08-17 API-007 SSE 幂等与重连

## 验证目标

验证 Copilot 的 Abort、取消和重连不会重复发送 token，也不会重复写入同一会话消息；同时保证 stream 只能在原租户、用户和请求范围内恢复。

## 验证结果

后端 API-006/API-007 聚焦测试 8/8、前端全量 21 files / 100 tests 通过。每个 SSE 事件带 `nxa.sse.v1`、`stream_id` 和单调 `sequence`，客户端按 `last_event_id` 去重；完成流回放只读缓存，不重新调用模型。TypeScript lint、Vite build、Python compile 和 diff check 均通过。

## 数据与安全边界

本任务没有 PostgreSQL migration 或生产写入。registry 只保留有界事件窗口，request fingerprint 为哈希，不保存原始 prompt/history；跨租户或跨用户复用 stream id 会得到 `SSE_STREAM_CONFLICT`。持久化 session/task 语义留给 API-008/009。
