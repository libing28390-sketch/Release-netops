# Walkthrough：Usage 名称展示、Health 全启用模型探测与 Copilot CMDB 零 Token 修复

- 对应计划：[plan_20261126_2258_01_Usage名称展示Health全模型探测与Copilot_CMDB零Token修复.md](file:///D:/netops/netsops-main/docs/plans/plan_20261126_2258_01_Usage名称展示Health全模型探测与Copilot_CMDB零Token修复.md)
- 目标仓库：`D:\netops\netsops-main`

## 1. 完成摘要
1. **`/ai/usage` 不再显示 Nexora 内部 ID**：
   - [usage.py](file:///D:/netops/netsops-main/backend/ai/api/usage.py) 关联 `ai_provider` 与 `ai_model` 表，在 `/api/ai/usage/summary`（`provider_breakdown`）和 `/api/ai/audit` 中返回真实 `provider_name`、`model_name`、`model_code`，已删除的历史 ID 自动映射为「历史模型 (已删除)」/「历史供应商 (已删除)」。
   - [UsageDashboardTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Usage/UsageDashboardTab.tsx) 的分布表、审计日志表和 CSV 导出全面切换为真实名称展示，彻底隐藏 `model_xxx` / `prov_xxx` / UUID。
2. **`/ai/health` 默认探测所有已启用模型**：
   - [model_health.py](file:///D:/netops/netsops-main/backend/ai/services/model_health.py) 的 `run_scheduled_model_health_checks()` 扩展至所有已启用的 `chat`、`reasoning`、`embedding` 模型（不再遗漏 `embedding`）。
   - [models.py](file:///D:/netops/netsops-main/backend/ai/api/models.py) 的 `health-summary` 将已启用的 `embedding` 纳入可监控状态，并新增 `POST /api/ai/models/health-check-all` 批量探测接口。
   - [ModelHealthDashboardTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Health/ModelHealthDashboardTab.tsx) 放开 `embedding` 模型的单次探测按钮，并在顶部新增 **「探测全部启用模型」** 一键按钮。
3. **`/ai/copilot` 修复「我们有多少台设备」未查 CMDB 且消耗 Token 的缺陷**：
   - 根因：[assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py#L1716-L1737) 的 `_merge_history_scope_continuation()` 在多轮历史会话中因短句包含 `"多少"`，将已被 `intent_parser` 确定性识别为 `asset_analysis` 的 CMDB 查询强行改写成了 `general_qa`，导致请求发往外部模型并消耗 4,541 Token。
   - 修复：保护确定性本地查询（`parse_status == "deterministic"` 且属于 `asset_analysis` / `alarm_search` / `ip_location` / `mac_location`），不再被历史续问规则降级，确保直接查询本地 PostgreSQL CMDB 且 **消耗 0 Token**（`token_source: "local_zero"`）。

## 2. 实际修改文件
- [backend/ai/api/usage.py](file:///D:/netops/netsops-main/backend/ai/api/usage.py)
- [backend/ai/services/model_health.py](file:///D:/netops/netsops-main/backend/ai/services/model_health.py)
- [backend/ai/api/models.py](file:///D:/netops/netsops-main/backend/ai/api/models.py)
- [backend/ai/services/assistant.py](file:///D:/netops/netsops-main/backend/ai/services/assistant.py)
- [src/api/ai.ts](file:///D:/netops/netsops-main/src/api/ai.ts)
- [src/pages/ai/Usage/UsageDashboardTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Usage/UsageDashboardTab.tsx)
- [src/pages/ai/Health/ModelHealthDashboardTab.tsx](file:///D:/netops/netsops-main/src/pages/ai/Health/ModelHealthDashboardTab.tsx)

## 3. 验证结果
- 后端 `py_compile` + 3 项核心断言（`ALL_3_BACKEND_CHECKS_PASS`）：**PASS**
- 前端 `npm run lint`、`npx vitest run src/pages/ai/Usage src/pages/ai/Copilot`、`npm run build`：见最终回复。
