# 实施计划：Agentic 对话四项实战缺陷修复与 Token 压降

- **创建时间**：2026-11-27 10:52
- **目标仓库**：`D:\netops\netsops-main`
- **背景来源**：46 轮线上真实浏览器压测 + PostgreSQL `ai_request_log` 账单审计

## 1. 任务目标
修复 46 轮实测暴露的 4 项 P0/P1 实战缺陷，并将长对话输入 Token 消耗压降 60%~75%。

## 2. 现状与根因
1. **【P0】跑满 2 轮工具调用后进入最终 `chat_stream` 偶发空回复（11/46 轮，输出仅 1 Token）**：
   - `_run_agentic_chat_stream` 在第 2 轮工具调用结束后，把带 `tool_calls` 与 `role="tool"` 的 `messages` 发给 `llm_gateway.chat_stream(..., tools=None)`；Gemini OpenAI 兼容接口在请求含 `tool_calls`/`role="tool"` 但未提供 `tools` 声明时会直接返回空流或 1 Token 结束。
2. **【P0】脱敏占位符 `[[NXA_DEVICE_...]]` / `[[NXA_IP_...]]` 泄漏到前端回答**：
   - 一方面，流式或非流式 `task_id` 与上一轮存储的 `task_id` 不一致或跨轮历史里混入了未还原占位符；另一方面，当 `StreamingOutputResolver` 或 `resolve_output` 在多轮对话中遇到未命中当前 `task_id` 映射表的占位符（或工具返回结果在二次调用中被重复 tokenize）时直接透出给前端。
3. **【P1】正常只读 CLI 命令被过度脱敏**：
   - `display snmp-agent community` 等不含真实密钥值的只读查询命令被正则误判为 `snmp_community` 密钥值并替换为 `<REDACTED_CREDENTIAL>`。
4. **【P1】长对话输入 Token 偏高（46 轮 ~91.7 万）+ 缺少当天日期**：
   - Agentic 模式复用 `complex` 历史预算（100 轮 / 110K Tokens），导致每轮重复发送 1.5 万~3.7 万历史 Token；且静态 System Prompt 未包含按天固定的 `Current Date: YYYY-MM-DD`，导致模型偶发臆测历史日期（如 `2023-10-28`）。

## 3. 拟修改文件
- `backend/ai/services/assistant.py`：
  - 最终流式合成轮不再直接向不带 `tools` 的 `chat_stream` 发送裸 `tool_calls`/`role="tool"` 消息，而是将本轮工具取证结果折叠为紧凑的 `[本地工具核实事实]` 注入用户消息（或兼容传入 `tools=None` 的纯 `system/user/assistant` 消息链），彻底消除 Gemini 兼容层空流；同时若流式输出为空则自动降级非流式兜底。
  - 为 Agentic Chat 增加专用紧凑滑动窗口（默认最近 12 轮 / 12,000 Token 预算，配合 `AI_COPILOT_AGENTIC_HISTORY_TURNS` 配置）。
- `backend/ai/services/copilot_tools.py`：
  - 在 `build_agentic_system_prompt()` 中加入按天固定的 `Current Date: YYYY-MM-DD`（同日 24 小时完全静态，不破坏 KV Cache）。
- `backend/ai/security/classification.py`：
  - 收紧 `snmp_community` 脱敏正则，放行不带实际密钥参数的只读查看命令（如 `display snmp-agent community`、`show snmp community`）。
- `backend/ai/security/tokenization.py` / `backend/ai/security/output.py`：
  - 检查并修复 `[[NXA_...]]` 占位符还原路径，确保同一会话 `conversation_id` 内的全部工具调用轮次与最终流式输出共享同一个 `task_id` 映射池，且历史消息写入前已完成还原。
- `backend/tests/ai/test_copilot_agentic_tools.py`：
  - 补充针对上述 4 项缺陷的精准回归测试。

## 4. 验证计划
- `py_compile` 检查全部修改文件。
- 运行 `pytest backend/tests/ai/test_copilot_agentic_tools.py backend/tests/ai/test_twelve_module_entity_bus.py backend/tests/ai/test_local_router_and_cache_stability.py backend/tests/ai/test_token_optimization_suite.py -q` 以及安全网关相关单测。

## 5. 风险与回滚
- 改动局限于 Agentic 工具合成格式、历史窗口预算与安全正则边界，无表结构变更，可随时通过 `AI_COPILOT_AGENTIC_CHAT_ENABLED=false` 或文件回退恢复。
