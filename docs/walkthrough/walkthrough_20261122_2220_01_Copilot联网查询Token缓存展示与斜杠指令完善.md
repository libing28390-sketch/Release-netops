# Walkthrough：Copilot 联网查询、Token 缓存展示与斜杠指令完善

- 对应计划：[plan_20261122_2220_01_Copilot联网查询Token缓存展示与斜杠指令完善.md](file:///D:/netops/netsops-main/docs/plans/plan_20261122_2220_01_Copilot联网查询Token缓存展示与斜杠指令完善.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 完成摘要

本次完成了 Copilot 的三项核心体验修复：
1. **联网查询（受控公开检索）**：
   - 在 `D:\netops\netsops-main\.env` 开启 `AI_WEB_SEARCH_ENABLED=true`。
   - 后端 `AIAssistantService._should_lookup_web()` 支持显式 `context.web_search=true`（同时保留对天气/今天/最新等公开实时问句的自动识别，且仅作用于 `general_qa` / `knowledge` 意图，不越权影响内部运维操作）。
   - 前端 `CopilotComposer.tsx` 输入框新增 **「联网」**（`Globe` 图标）切换开关，并支持 `/web` 指令自动开启联网。
2. **每条回答展示 Token 输入 / 输出 / 缓存**：
   - 后端 `openai_compatible.py`（流式与非流式）解析 DeepSeek `prompt_cache_hit_tokens` 及 OpenAI `prompt_tokens_details.cached_tokens`，经 `llm_gateway.py`、`services/assistant.py`（SSE `done`）与 `api/assistant.py`（SSE `meta`）全链路透传 `cached_tokens`。
   - 前端 `src/api/ai.ts` 与 `AssistantTab.tsx` 接收并存储 `cached_tokens`，在每条已完成的 AI 回复底部操作栏右侧以单行低视觉噪音样式展示：`输入 X · 输出 Y · 缓存 Z`。
3. **斜杠快捷指令（`/`）完善为真实可用功能**：
   - 将 `CopilotComposer.tsx` 的静态占位按钮升级为 6 个真实可用指令：`/ip`、`/mac`、`/config`、`/troubleshoot`、`/sop`、`/web`。
   - 支持输入 `/` 前缀实时过滤、`↑` / `↓` 键选择、`Tab` / `Enter` 填入、`Esc` 关闭；提交时自动将带参指令展开为自然语言提问（例如 `/ip 10.0.0.1` → `10.0.0.1 在哪台交换机哪个端口？`，`/web 今天武汉天气` → `今天武汉天气` 并开启联网）。

## 2. 实际修改文件

- [openai_compatible.py](file:///D:/netops/netsops-main/backend/ai/providers/openai_compatible.py)：提取并透传 `cached_tokens`（兼容 DeepSeek `prompt_cache_hit_tokens` 与 OpenAI `prompt_tokens_details.cached_tokens`）。
- [llm_gateway.py](file:///D:/netops/netsops-main/backend/ai/gateway/llm_gateway.py)：流式结束时将 `cached_tokens` 写入 `route_meta`。
- [assistant.py (API)](file:///D:/netops/netsops-main/backend/ai/api/assistant.py)：SSE `route_meta` 同步透传 `cached_tokens`。
- [assistant.py (Service)](file:///D:/netops/netsops-main/backend/ai/services/assistant.py)：`_should_lookup_web` 支持 `explicit_web_search`；SSE `done` 事件附带 `cached_tokens`。
- `.env`（本地运行配置，不提交敏感信息）：追加 `AI_WEB_SEARCH_ENABLED=true`。
- [ai.ts](file:///D:/netops/netsops-main/src/api/ai.ts)：`AssistantStreamMeta` 与 `AssistantStreamDoneMeta` 新增 `cached_tokens?: number`。
- [AssistantTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Copilot/AssistantTab.tsx)：`ChatMessage` 新增 `cached_tokens` 并在 AI 回复底部展示 `输入 · 输出 · 缓存`。
- [CopilotComposer.tsx](file:///D:/netops/netsops-main/src/pages/ai/Copilot/CopilotComposer.tsx)：新增「联网」开关与可过滤、键盘导航、带参展开的 6 个 `/` 快捷指令。

## 3. 验证命令与结果

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 后端语法编译 | `.\.venv\Scripts\python.exe -m py_compile backend/ai/providers/openai_compatible.py backend/ai/gateway/llm_gateway.py backend/ai/api/assistant.py backend/ai/services/assistant.py` | PASS（退出码 0） |
| 后端联网检索单测 | `.\.venv\Scripts\python.exe -m pytest backend/tests/ai/test_web_retrieval.py -q` | PASS（5 passed） |
| 前端 TypeScript 检查 | `npm run lint` (`tsc --noEmit`) | PASS（0 errors） |
| 前端 Copilot 单元测试 | `npx vitest run src/pages/ai/Copilot` | PASS（13 files / 40 passed） |
| 前端生产构建 | `npm run build` | 执行中 / 见最终回复 |

## 4. 未执行验证及原因

- 后端服务（uvicorn）热重载/重启后的真实线上 `http://192.168.56.1:5400/ai/copilot` 端到端联网天气查询未自动执行，需重启后端进程以加载新的 `.env` 配置（`AI_WEB_SEARCH_ENABLED=true`）与 Python 代码改动。

## 5. 剩余风险与后续建议

- `.env` 修改后需重启后端服务才能生效；若当前宿主机网络无法访问默认公开检索端点（DuckDuckGo / Wikipedia），建议在 `.env` 中配置企业可用的 `AI_WEB_SEARCH_PROVIDER` 或代理。
- 历史消息持久化目前主要保存 `input_tokens` / `output_tokens`，刷新页面后历史消息的 `cached_tokens` 显示为 `0`，实时对话消息会准确显示模型返回的缓存命中数。
