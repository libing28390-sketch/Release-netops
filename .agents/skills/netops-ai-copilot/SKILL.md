---
name: netops-ai-copilot
description: >-
  Use when designing, modifying, or debugging Nexora AI Copilot, 12-module
  zero-token routing, conversation entity memory, RAG/semantic cache, MCP
  built-in tools, prompt caching, or AI Center usage/health/security flows.
---

# Nexora AI Copilot & 12-Module Architecture Skill

## 1. 十二大功能模块跨模块零 Token 架构
- Nexora Copilot 是十二大功能模块的统一智能入口，路由遵循 **「四向定性分流 → 实体解析/继承 → 12 大模块只读总线 → 问啥答啥渲染」**：
  1. **四向定性**：先区分 `FACT_QUERY`（查事实 → 0 Token 本地总线）、`HOW_TO`（问配法/命令/规格 → 知识库/语义缓存）、`ACTION_EXEC`（写操作/代登 → 0 Token 只读拦截+模块跳转）、`REASONING`（为什么/有关联吗/根因分析 → 携带精简本地事实进 LLM）。
  2. **会话实体工作记忆（Entity Context）**：每个会话持久化焦点对象（`device_id/hostname/ip/vendor/site/prefix/rack`），支持跨模块零 Token 串联（如 `1.1.1.1 设备信息` → `这台设备最近登录了几次` → `它有告警吗` → `最近配置改过吗`）。
  3. **六道边界护栏**：
     - 防焦点串台：仅在出现指代词或主语省略的属性追问时继承焦点；含全网词或独立统计句默认查全网，首行必须回显查询范围。
     - 防多目标歧义：候选实体 >1 时 0 Token 本地澄清，不瞎猜。
     - RBAC 权限与凭据隔离：复用 `core.rbac` 校验模块只读权限；物理级禁止查询密码、私钥、Community、Token 列。
     - 焦点持久化：随会话存 PostgreSQL（`entity_context_json`），重启/刷新不断片。
     - 问啥答啥：问告警先给“有/无 + 未恢复明细”；单设备给精简档案卡；禁止问 A 吐 8 节 B 报表。
     - 平滑移交：因果推理自动附带前序本地精简事实交给 LLM。

## 2. 零 Token 本地执行与 Token 压缩清单
- 本地操作意图（`asset_analysis`、`device_search`、`alarm_search`、`ip_location`、`mac_location`、`local_ops`）必须直接返回 `execution_mode="local_operation"`, `token_source="local_zero"`（0 LLM 调用，禁止落入 `chat_stream`）。
- 显式 `/` 指令（`/ip`、`/mac`、`/alarms`、`/neighbors`、`/ipam`、`/interfaces`、`/changes`）由 `backend/ai/mcp/registry.py` 统一注册并动态下发至前端 `/` 菜单，执行时 0 Token 跳过 LLM 意图解析。
- 知识库高分命中（默认 `score >= 0.85` 且非对比/深度解释）直接本地渲染原文+出处；重复单轮知识问答优先命中 `ai_semantic_qa_cache`；送入 LLM 的 `context_facts` 必须用紧凑 Markdown 而非冗长 `json.dumps()`。
- 后台轻量场景（`natural_query`、`model_health_probe`）无显式路由时优先选本地/最低成本/Flash 模型；定时健康探测优先使用 0 Token `GET /models`。

## 3. Prompt Cache（KV Cache）稳定性清单
- `messages[0]`（System Prompt）在普通多轮会话中必须保持 100% 静态字节一致；每轮动态状态（`knowledge_no_match`、`web_search`）一律下沉到最后一条 `user` 消息的 `Turn Guidance`。
- 长技术会话建立后锁定统一历史预算，禁止在 `48k` 与 `96k/110k` 间逐轮震荡。
- 历史中的本地大报表（CMDB/告警明细表）须经确定性纯函数压缩后再进入 LLM `history`。
- `cached_tokens` 必须兼容提取 `prompt_cache_hit_tokens`、`prompt_tokens_details.cached_tokens`、`cache_read_input_tokens`、`cached_tokens`，并持久化到 `ai_messages.cached_tokens`。
