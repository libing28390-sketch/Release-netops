# Copilot 联网查询、Token/缓存展示与斜杠指令完善实施计划

- 创建时间：2026-11-22 22:20
- 目标目录：`D:\netops\netsops-main`

## 1. 任务目标

针对 Copilot 对话框的 3 项核心体验诉求完成端到端实现：
1. 打通受控互联网查询（前端提供「联网」开关 + `/web` 指令，后端支持国内可达搜索源且保持内网凭据/IP DLP 拦截）；
2. 在每条 AI 回复底部轻量化展示每次调用的「输入 Token / 输出 Token / 缓存命中 Token」；
3. 将 `/` 快捷指令升级为支持实时过滤、键盘 `↑/↓/Tab/Enter/Esc` 导航与带参执行的完整斜杠命令体验。

## 2. 现状与问题

1. `web_retrieval.py` 默认关闭且仅允许 DuckDuckGo + 仅限网络运维词条，国内环境与日常查询无法触发。
2. 后端 `openai_compatible.py` 未透传 DeepSeek `prompt_cache_hit_tokens` / OpenAI `prompt_tokens_details.cached_tokens`，前端已隐藏 Token 行导致无法看到输入/输出/缓存消耗。
3. `CopilotComposer.tsx` 的快捷指令仅插入写死的静态示例文本，不支持前缀过滤、键盘选择和带参执行。

## 3. 影响范围与拟修改文件

- `backend/ai/providers/openai_compatible.py`：解析并透传 `cached_tokens`（兼容 DeepSeek `prompt_cache_hit_tokens` 与 OpenAI `prompt_tokens_details.cached_tokens`）。
- `backend/ai/gateway/llm_gateway.py` & `backend/ai/api/assistant.py`：透传 `cached_tokens` 至 SSE `done` 事件；当 `context.web_search` 为真时触发受控联网检索并把结果注入上下文。
- `backend/ai/services/web_retrieval.py`：支持显式 `web_search` 放行通用查询，新增国内可达搜索源（Bing CN HTML / wttr.in 天气回退）并保留硬 DLP 过滤。
- `src/api/ai.ts`、`src/pages/ai/Copilot/CopilotComposer.tsx`、`src/pages/ai/Copilot/AssistantTab.tsx`：新增「联网」开关、完整 `/` 斜杠指令键盘交互与参数展开、轻量 Token（输入 / 输出 / 缓存）展示行。

## 4. 实施步骤

1. 后端透传 `cached_tokens` 并增强 `web_retrieval.py` 显式联网查询能力。
2. 前端 `CopilotComposer.tsx` 实现「联网」开关与完整 `/` 斜杠指令（过滤、键盘导航、带参转换）。
3. 前端 `AssistantTab.tsx` 恢复轻量一行 Token 展示（输入 / 输出 / 缓存命中）。
4. 运行 `npm run lint`、`npx vitest run src/pages/ai/Copilot`、`npm run build` 与后端 `test_web_retrieval.py` 验证。

## 5. 验证计划

- 后端 `pytest backend/tests/ai/test_web_retrieval.py` 通过。
- 前端 `npm run lint`、`npx vitest run src/pages/ai/Copilot`、`npm run build` 全部通过。

## 6. 风险与回滚思路

联网检索仍严格经过 `_hard_dlp_detected` 与内网敏感信息校验，不外泄内网凭据/IP；所有改动均局限在 Copilot 与 `web_retrieval` 模块，可按文件独立回滚。
