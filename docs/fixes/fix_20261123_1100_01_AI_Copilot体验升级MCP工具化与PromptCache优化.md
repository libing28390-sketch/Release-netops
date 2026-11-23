# 修复与变更记录：AI Copilot 体验升级、MCP 工具化、本地文档上传与 Prompt Cache 优化

- 创建时间：2026-11-23 11:00
- 目标分支：`release/AI_DEV`

## 1. 问题现象与本次提交目的
本次提交汇总 AI Center / Copilot 的多轮体验升级、安全加固与性能优化：
1. **AI 安全机制加固与自拦截修复**：完成 5 项纵深加固，并修复 `gateway.py` 将 `system` 安全规则误判为 `change_command` 导致常规对话被拦的缺陷。
2. **Copilot Gemini 化体验升级**：重构极简顶栏与双行浮动输入框、新增受控「联网」查询开关、每条回复展示 `输入 · 输出 · 缓存` Token 统计、支持一键导出当前会话为 Markdown (`.md`) 与 JSON (`.json`)。
3. **内置服务 MCP 工具化与动态 `/` 目录**：新增 `backend/ai/mcp/registry.py`，提供 `GET /api/ai/assistant/tools` 与标准 MCP JSON-RPC 2.0 端点 `POST /api/ai/assistant/mcp`，前端 `/` 菜单动态加载后端注册服务。
4. **本地 Word / Excel / PDF 上传与安全预检**：新增 `backend/ai/services/document_parser.py` 与 `POST /api/ai/assistant/attachments/parse`，支持纯本地解析 `.docx`/`.xlsx`/`.pdf`/文本，仅对真实私钥/凭据硬拦截、其余自动脱敏放行。
5. **Prompt Cache（KV Cache）前缀稳定与 `cached_tokens` 持久化**：将每轮动态指导从 `system` 下沉到末条 `user` 消息，保持 `messages[0]` 字节级一致；全链路兼容并持久化 `cached_tokens`。
6. **RAG 推理提速、长会话扩容与知识库管理优化**：同步纳入工作区已验证的 RAG/知识库/治理优化及配套运维脚本。

## 2. 根因
- 原 `gateway.py` 未区分 `system` 与 `user` 消息导致安全规则自拦截；
- 原 `CopilotContext` 未声明 `web_search` 字段导致开启联网时报 `VALIDATION_ERROR`；
- 原 `_build_system_prompt()` 每轮拼接动态状态导致 LLM Prompt Cache 前缀穿透，且 `ai_messages` 未持久化 `cached_tokens`；
- 原附件上传预检直接复用知识库严格隔离策略，误拦普通导出会话与 SOP 文档。

## 3. 解决方案与实际修改范围
- 后端：`backend/ai/`（`mcp/registry.py`、`services/document_parser.py`、`services/assistant.py`、`services/conversation_service.py`、`api/assistant.py`、`providers/openai_compatible.py`、`gateway/llm_gateway.py`、`security/` 及测试）、`backend/api/knowledge_contracts.py` 等；
- 前端：`src/api/ai.ts`、`src/pages/ai/Copilot/`（`AssistantTab.tsx`、`CopilotComposer.tsx`、`CopilotHeader.tsx`、`exportUtils.ts` 及单测）、AI Center 各页面文案与组件；
- 脚本与配置：`scripts/`、`sidecars/`、`monitoring/`、`docker-compose.yml`、`.env.example`、`.gitignore`、`.dockerignore`；
- 归档文档：`docs/plans/`、`docs/walkthrough/` 及本修复记录 `docs/fixes/fix_20261123_1100_01_AI_Copilot体验升级MCP工具化与PromptCache优化.md`。

## 4. 验证命令与结果
- 后端 `py_compile` + `pytest backend/tests/ai/test_web_retrieval.py` + MCP/DOCX/静态前缀冒烟验证：**PASS**
- 前端 `npm run lint` (`tsc --noEmit`)：**PASS（0 errors）**
- 前端 `npx vitest run src/pages/ai/Copilot`：**PASS（14 files / 43 passed）**
- 前端 `npm run build`：**PASS**
- 浏览器端到端验证 `http://192.168.56.1:5400/ai/copilot`：**PASS**（动态 `/` 8 项工具、联网实时天气查询、Token 展示正常）

## 5. 未验证项
- 未在本次提交中纳入 `.env`、`logs/`、`output/`、`dist*`、`handoff.md` 及 `.agents/` 删除项。

## 6. 风险与回滚方式
- `ai_messages.cached_tokens` 通过幂等 `ADD COLUMN IF NOT EXISTS` 新增，兼容存量数据库；
- 如需回滚，可在 `AI_DEV` 分支执行 `git revert <commit_hash>`。
