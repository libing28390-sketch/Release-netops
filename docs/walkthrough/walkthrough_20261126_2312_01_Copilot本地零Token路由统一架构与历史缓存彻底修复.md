# Walkthrough：Copilot 本地零 Token 路由统一架构与多轮历史缓存彻底修复

- 对应计划：[plan_20261126_2312_01_Copilot本地零Token路由统一架构与历史缓存彻底修复.md](file:///D:/netops/netsops-main/docs/plans/plan_20261126_2312_01_Copilot本地零Token路由统一架构与历史缓存彻底修复.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 根本原因与系统性修复

本次没有继续打零散补丁，而是从架构层面根治了 **4 个相互耦合的结构性问题**：

1. **消除 `device_search` 双重无效 LLM 调用**
   - 原实现中，`assistant.py`（流式与非流式）对 `device_search` 会先调 `natural_query_service.execute_query()`（内部调第 1 次 LLM），随后又不 `return`，直接穿透到 `llm_gateway.chat_stream()`（第 2 次外部 LLM）。
   - 修复：`assistant.py` 中 `intent in {"asset_analysis", "device_search"}` 统一走本地 PostgreSQL 确定性聚合并直接返回 `execution_mode="local_operation"`, `input_tokens=0`, `output_tokens=0`, `token_source="local_zero"`，**0 次外部模型调用、0 内部主机名外发**。
2. **建立统一的本地零 Token 路由器（[local_router.py](file:///D:/netops/netsops-main/backend/ai/services/local_router.py)）**
   - 在外部 LLM 意图解析**之前**统一判定确定性本地意图：
     - 覆盖单轮列举式 CMDB 查询（如「有哪些思科设备」「列出所有华为交换机」「离线设备有哪些」），并设置严格守卫确保配置/命令/排障/硬件规格提问永不被误拦；
     - 覆盖多轮本地上下文继承：上一轮是 CMDB 资产报表时，短追问（「那华为设备呢」「思科的呢」「防火墙呢」「那全部设备呢」）自动继承 `asset_analysis`；上一轮是告警统计时，短追问（「那昨天的呢」「未处理的呢」）自动继承 `alarm_search`。
   - 收紧 `_merge_history_scope_continuation()`，禁止任何本地操作意图（`asset_analysis` / `device_search` / `alarm_search` / `ip_location` / `mac_location`）被降级为 `general_qa`。
3. **锁定长技术会话历史预算，根治 Prompt Cache 前缀震荡**
   - 原 `_history_policy()` 在 `public (48k)` 与 `network (96k)` / `complex (110k)` 之间随意图反复切换，导致头部历史被周期性裁切又恢复，造成 KV Cache 100% 穿透。
   - 修复：长技术会话一旦建立（最近历史含 >=2 轮网络技术问答），锁定统一预算，不再在 `48k` 与 `96k/110k` 间来回抖动。
4. **本地 CMDB/告警长报表进入历史时确定性摘要压缩**
   - 新增 `compact_local_report_for_history()` 并在 `_select_history_for_model()` 中调用：将 60 行逐台设备明细表确定性裁剪为首段摘要与分布概览（纯函数，字节级一致不破坏 KV Cache），大幅削减后续普通提问的无效输入 Token。

## 2. 实际修改文件
- 新增：[backend/ai/services/local_router.py](file:///D:/netops/netsops-main/backend/ai/services/local_router.py)
- 新增：[backend/tests/ai/test_local_router_and_cache_stability.py](file:///D:/netops/netsops-main/backend/tests/ai/test_local_router_and_cache_stability.py)
- 修改：[backend/ai/services/assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py)

## 3. 验证结果
- 见下方 pytest 回归测试结果。
