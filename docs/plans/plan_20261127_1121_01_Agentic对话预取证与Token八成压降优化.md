# 实施计划：Agentic 对话 0-Token 预取证与 Token 压降优化

- **创建时间**：2026-11-27 11:21
- **目标仓库**：`D:\netops\netsops-main`
- **背景来源**：第 3 轮全新空白会话消耗 11,324 Input Tokens / 30 秒（因 1 轮拆成 3 次 API 调用 + 肥工具 Schema + 冗长 Markdown 工具原文）

## 1. 任务目标
在不降低原生 LLM 多轮推理质量、坚持 100% 本地真实数据的前提下，将典型单轮/跨模块查询的 Input Token 从 **~11,300** 压降至 **~1,500–2,500（降幅 75%~80%）**，并将端到端延迟从 **~30 秒** 压降至 **~5–8 秒**；顺带修复 `sanitizer.py` 对独立行 `display snmp-agent community` 误替换为 `<REDACTED>` 的瑕疵。

## 2. 优化方案
1. **本地 0-Token 实体与模块预取证（`prefetch_local_facts`）**：
   - 在调大模型之前，毫秒级扫描用户问题中的明确设备（IP / 主机名，最多 3 台）与数据维度（告警、接口、PAM、配置/漂移、工单、机柜、IPAM、总览），在 Python 层并行查完本地 PostgreSQL 并浓缩为 ≤ 900 字的高密度事实块。
   - 若本轮所需本地事实已通过预取证 + 长期记忆自动激活齐备（且非“记住”写入或未预取的知识库查询），**直接单次 `chat_stream(..., tools=None)` 流式输出推理结论**，省去 2 轮规划调用与整套 Tool Schema 前缀。
2. **Tool Schema 与工具返回瘦身**：
   - 精简 9 个工具的 JSON Schema 描述（体积压降 ~60%），将 `MAX_TOOL_RESULT_CHARS` 从 `1800` 压降至 `900`。
   - 系统提示词明确：若 `[已激活的长期运维记忆]` 或 `[本地已预取实锤数据]` 已含所需信息，直接基于其推理回答，禁止重复调用工具。
3. **修复 `sanitizer.py` 只读 SNMP 查看命令误脱敏**：
   - 放行不带实际密钥值的 `display snmp-agent community` / `show snmp community`。

## 3. 拟修改文件
- `backend/ai/services/copilot_tools.py`：精简 Tool Schema、`MAX_TOOL_RESULT_CHARS=900`、新增 `prefetch_local_facts()`。
- `backend/ai/services/assistant.py`：在 `_run_agentic_chat` / `_run_agentic_chat_stream` 接入 `prefetch_local_facts()`；当预取已覆盖当前诉求时直走单次流式推理（省去 2 轮规划调用）。
- `backend/ai/security/sanitizer.py`：修复独立行 `display snmp-agent community` 误替换为 `<REDACTED>`。
- `backend/tests/ai/test_copilot_agentic_tools.py`：新增 0-Token 预取证单次合成与 `sanitizer.py` 只读命令放行单测。

## 4. 验证计划
- `py_compile` + `pytest backend/tests/ai/test_copilot_agentic_tools.py backend/tests/ai/test_neural_memory_graph.py -q`。

## 5. 风险与回滚
- 仅优化预取证与 Schema 体积，不影响数据边界与安全校验，可随时按文件回退。
