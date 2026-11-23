# 实施计划：Prompt Cache 前缀稳定性优化与 `cached_tokens` 持久化

- 创建时间：2026-11-23 10:05
- 目标仓库：`D:\netops\netsops-main`

## 1. 任务目标
解决多轮长对话（如 40~100 轮）中 LLM Prompt Cache（KV Cache）始终为 `0` 的问题，确保：
1. **System Prompt 静态化**：将第 1 条 `system` 消息固定为稳定前缀，把每轮动态状态（知识库未命中/联网状态）下沉到最后一条 `user` 消息上下文中，避免破坏 KV Cache 前缀匹配。
2. **历史前缀稳定化**：避免 `_history_policy` 因意图微调导致历史预算忽大忽小（如 `66k → 45k → 75k → 44k`），并在超预算时按固定步长（chunk）裁剪头部，确保连续多轮共享完全一致的历史前缀。
3. **`cached_tokens` 全链路兼容与持久化**：
   - Provider 层兼容 `prompt_cache_hit_tokens`、`prompt_tokens_details.cached_tokens`、`cache_read_input_tokens`、`cached_tokens`；
   - 会话消息持久化并回传 `cached_tokens`，刷新页面及导出历史会话时完整保留缓存命中数。

## 2. 拟修改文件
- `backend/ai/providers/openai_compatible.py`（兼容更多上游 `cached_tokens` 字段）
- `backend/ai/services/assistant.py`（静态 System Prompt + 动态状态注入末条 user 消息 + 稳定历史前缀）
- `backend/ai/services/conversation_service.py` & `backend/ai/api/assistant.py`（持久化与回传 `cached_tokens`）
- `src/pages/ai/Copilot/AssistantTab.tsx`（`normalizeConversationMessage` 读取 `cached_tokens`）

## 3. 验证计划
- 后端：`py_compile` + 单元测试验证相同会话连续多轮 `messages[0]`（system）字节级一致、历史前缀稳定、`cached_tokens` 提取与读写正确。
- 前端：`npm run lint`、`npx vitest run src/pages/ai/Copilot`、`npm run build`。

## 4. 风险与回滚思路
- `cached_tokens` 持久化优先存入已有 `metadata` / 幂等新增列（PostgreSQL `ADD COLUMN IF NOT EXISTS`），不破坏存量数据；回滚仅需还原上述文件。
