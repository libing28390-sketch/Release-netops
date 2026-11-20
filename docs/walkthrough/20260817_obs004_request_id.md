# OBS-004 请求 ID 全链路验证

OBS-004 将前端生成的 `X-Request-ID` 贯穿 API middleware、Assistant Copilot、RAG retrieval trace、LLM Gateway 的 retry/fallback，以及 Provider 出站 header。缺失或含控制字符的请求 ID 会由后端替换为 bounded server-owned ID。

验证重点:

- 普通 API 与 Assistant SSE 自动生成并发送 `web_*` ID；显式调用者 ID 保留。
- SSE 每个 `nxa.sse.v1` event 带 request_id，重连仍由 stream_id/sequence 负责幂等。
- Gateway 的 chat/stream、primary/fallback 和 audit row 使用同一个 ID。
- Provider 只在 `X-Request-ID` header 传递 correlation，不把它写入模型 JSON body。
- Trace 保存 tenant-scoped request_id，但继续保持 raw query hash-only 与 OBS-003 脱敏约束。
