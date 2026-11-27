# 实施计划：Copilot 本地零 Token 路由统一架构与多轮历史缓存彻底修复

- 创建时间：2026-11-26 23:12
- 目标仓库：`D:\netops\netsops-main`

## 1. 问题根因（系统性架构诊断）
经过对 `intent_parser.py`、`assistant.py`、`natural_query.py` 的全链路审计，确认导致“CMDB 查询误走大模型消耗 Token”以及“长会话 Prompt Cache 持续为 0”存在 **4 个结构性架构缺陷**：

1. **缺陷一：`device_search` 路径存在双重无效 LLM 调用**
   - `assistant.py` 中 `intent == "device_search"` 调用了 `natural_query_service.execute_query()`（内部调用第 1 次 `llm_gateway.chat()`），随后又丢弃摘要并继续穿透到 `llm_gateway.chat_stream()`（第 2 次外部 LLM 调用），导致本应纯本地 SQL 完成的 CMDB 设备查询消耗大量 Token 且存在内部主机名外发风险。
2. **缺陷二：无状态单句意图解析与多轮本地追问割裂**
   - `intent_parser.parse_intent()` 仅看当前单句，不感知上一轮所处的本地业务域（CMDB 资产统计 / 告警统计）；
   - 同时 `is_asset_analysis_query()` 漏掉了常见列举式查询（如「有哪些思科设备」「列出所有防火墙」「离线设备有哪些」），而 `_merge_history_scope_continuation()` 又用过于宽泛的关键词规则把短句强行降级为 `general_qa`。
3. **缺陷三：历史策略预算随意图跳变，直接摧毁 Prompt Cache 前缀**
   - `_HISTORY_POLICIES` 在 `public (48k)` / `network (96k)` / `complex (110k)` 之间按每轮意图来回切换，导致同一长会话内输入 Token 剧烈跳变（如 `66k → 45k → 75k → 44k → 83k`），头部消息反复被丢弃与恢复，造成 LLM KV Cache 100% 穿透。
4. **缺陷四：本地 CMDB/告警长报表原样进入后续大模型历史**
   - 0 Token 的 CMDB 明细表在下一轮普通问答时被整表送进 LLM `history`，造成单轮 4,000~6,000+ 无效输入 Token。

## 2. 根本性改造方案
1. **统一本地零 Token 路由层（`backend/ai/services/local_router.py`）**：
   - 将所有确定性本地查询收口到统一路由器 `resolve_local_intent(message, history)`，优先于外部 LLM 意图解析执行：
     - **单轮确定性规则**：IP/MAC 定位、告警聚合/列表查询、CMDB 资产统计/列举查询（补齐「有哪些 / 列出 / 清单 / 离线 / 在线 + 厂商/角色/设备」识别，同时严格排除配置/命令/排障/知识库提问）；
     - **多轮上下文继承**：根据上一轮真实业务域精准继承——上一轮为 CMDB 报表时，短追问（「那华为设备呢」「思科的呢」「离线的呢」）继承 `asset_analysis`；上一轮为告警统计时，短追问（「那昨天的呢」「未处理的呢」）继承 `alarm_search`。
2. **`device_search` 彻底改为本地零 Token 确定性返回**：
   - `assistant.py`（流式与非流式）对 `device_search` 直接调用 `natural_query_service.execute_asset_analysis()` 本地聚合并返回 `execution_mode="local_operation"`, `input_tokens=0`, `output_tokens=0`, `token_source="local_zero"`，彻底消除双 LLM 调用与 CMDB 明细外发。
3. **收紧 `_merge_history_scope_continuation()`**：
   - 禁止降级任何本地查询意图（`asset_analysis`、`device_search`、`alarm_search`、`ip_location`、`mac_location`）；仅在上一轮为产品/知识对话且当前仅需要澄清时才降级为 `general_qa`。
4. **稳定历史预算 + 确定性压缩本地大报表**：
   - 当会话已包含网络/技术上下文时，`_history_policy()` 锁定统一稳定预算（不再在 `48k` 与 `96k/110k` 间反复跳变），保证 KV Cache 前缀稳定；
   - `_select_history_for_model()` 对历史中的 `Nexora CMDB 资产核对结果` / `Nexora 告警统计` 长报表执行**确定性摘要压缩**（仅保留首段摘要与分布概览，省略逐台明细表），既大幅削减后续 Token 消耗，又保证每轮压缩结果字节级一致、不破坏 Prompt Cache。

## 3. 拟修改文件
- 新增：`backend/ai/services/local_router.py`
- 新增：`backend/tests/ai/test_local_router_and_cache_stability.py`
- 修改：`backend/ai/services/intent_parser.py`
- 修改：`backend/ai/services/assistant.py`

## 4. 验证计划
- 运行新增单元测试 `pytest backend/tests/ai/test_local_router_and_cache_stability.py`
- 运行现有回归测试 `pytest backend/tests/ai/test_asset_analysis.py backend/tests/ai/test_intent_parser_structured.py backend/tests/ai/test_assistant_public_chat_routing.py`
- `py_compile` 全部改动文件

## 5. 风险与回滚思路
- 仅优化本地路由与历史裁剪逻辑，不改动数据库表结构与前端 API 契约；所有配置/命令/排障/知识库问句均有明确排除守卫，并通过现有测试集回归验证防误拦截。
