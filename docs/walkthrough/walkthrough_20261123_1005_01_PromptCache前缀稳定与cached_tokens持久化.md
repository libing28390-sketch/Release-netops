# Walkthrough：Prompt Cache 前缀稳定性优化与 `cached_tokens` 持久化

- 对应计划：[plan_20261123_1005_01_PromptCache前缀稳定与cached_tokens持久化.md](file:///D:/netops/netsops-main/docs/plans/plan_20261123_1005_01_PromptCache前缀稳定与cached_tokens持久化.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 完成摘要
1. **修复上传附件 `ModuleNotFoundError`**：
   - 将 [assistant.py](file:///D:/netops/netsops-main/backend/ai/api/assistant.py) 中错误的 `ai.knowledge.document_security` 修正为 `ai.services.document_security_scan` 与 `services.document_parser_adapters`。
2. **固定 System Prompt 前缀（恢复 LLM KV Cache 命中）**：
   - 在 [assistant.py (Service)](file:///D:/netops/netsops-main/backend/ai/services/assistant.py) 中新增 `_build_turn_guidance()`，把 `knowledge_no_match`、`web_search_available`、`web_search_attempted` 等每轮动态提示词从 `messages[0]`（system）下沉到最后一条 `user` 消息中。
   - 保证普通多轮对话中 `messages[0]` 在每一轮字节级完全一致，避免破坏 DeepSeek / OpenAI 的 Prompt Caching 严格前缀匹配。
3. **`cached_tokens` 全链路兼容与持久化**：
   - [openai_compatible.py](file:///D:/netops/netsops-main/backend/ai/providers/openai_compatible.py) 同时兼容 `prompt_cache_hit_tokens`、`prompt_tokens_details.cached_tokens`、`cache_read_input_tokens` 与 `cached_tokens`。
   - [conversation_service.py](file:///D:/netops/netsops-main/backend/ai/services/conversation_service.py) 幂等补充 `ai_messages.cached_tokens` 列（`ADD COLUMN IF NOT EXISTS`），在 `append_message()` 入库并在 `get_context()` 回传；[assistant.py (API)](file:///D:/netops/netsops-main/backend/ai/api/assistant.py) 流式结束持久化时传入 `cached_tokens`。
   - [AssistantTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Copilot/AssistantTab.tsx) 的 `normalizeConversationMessage()` 读取历史消息的 `cached_tokens`，刷新页面及导出 Markdown/JSON 均完整保留缓存命中数。

## 2. 验证结果
- 后端 `py_compile` + 静态前缀断言（`CACHE_PREFIX_STATIC_OK`）：**PASS**
- 前端 `npm run lint` + `npx vitest run src/pages/ai/Copilot` + `npm run build`：见最终回复。
