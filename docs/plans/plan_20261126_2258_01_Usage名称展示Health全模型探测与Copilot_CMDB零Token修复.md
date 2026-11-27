# 实施计划：Usage 名称展示、Health 全启用模型探测与 Copilot CMDB 零 Token 修复

- 创建时间：2026-11-26 22:58
- 目标仓库：`D:\netops\netsops-main`

## 1. 任务目标
解决用户反馈的 3 个 AI 中心问题：
1. **`/ai/usage`**：模型与供应商统计、审计日志中不再展示 Nexora 内部 ID（`model_xxx` / `prov_xxx` / UUID），改为展示真实的模型名称/代码与供应商名称（已删除的历史记录展示友好的兜底名称）。
2. **`/ai/health`**：默认定时探测与手动探测覆盖**所有已启用的模型**（包含 `chat`、`reasoning`、`embedding`、`rerank` 等），并在页面右上角提供「探测全部启用模型」一键触发能力。
3. **`/ai/copilot`**：修复在多轮历史会话中提问「我们有多少台设备」被 `_merge_history_scope_continuation()` 误降级为 `general_qa` 导致不查 CMDB 且消耗外部模型 Token 的缺陷，恢复本地 PostgreSQL 确定性 CMDB 聚合（0 Token）。

## 2. 根因分析
1. `backend/ai/api/usage.py` 直接返回 `ai_usage_daily` / `ai_request_log` 的原始 `provider_id` / `model_id`，未关联 `ai_provider.name` 与 `ai_model.name/model_code`；前端 `UsageDashboardTab.tsx` 直接渲染了原始 ID。
2. `backend/ai/services/model_health.py:401` 与 `src/pages/ai/Health/ModelHealthDashboardTab.tsx:144` 硬编码过滤了 `model_type IN ('chat', 'reasoning')`，排除了其他已启用模型（如 `embedding` / `rerank`）。
3. `backend/ai/services/assistant.py:1718-1737` 的 `_merge_history_scope_continuation()` 在存在历史消息且短句包含 `"多少"` 时，将已由 `intent_parser` 确定性识别为 `asset_analysis` 的 CMDB 查询强制改写成了 `general_qa`，绕过了本地 0 Token 的 `natural_query_service.execute_asset_analysis()`。

## 3. 拟修改文件
- `backend/ai/api/usage.py`
- `backend/ai/services/model_health.py`
- `backend/ai/api/models.py`
- `backend/ai/services/assistant.py`
- `src/api/ai.ts`
- `src/pages/ai/Usage/UsageDashboardTab.tsx`
- `src/pages/ai/Health/ModelHealthDashboardTab.tsx`

## 4. 验证计划
- 后端：`py_compile` + 单元测试验证 `usage` 名称映射、`model_health` 全启用模型查询、`assistant` 多轮历史下「我们有多少台设备」保持 `asset_analysis`（0 Token）。
- 前端：`npm run lint`、`npx vitest run src/pages/ai/Usage src/pages/ai/Copilot`、`npm run build`。

## 5. 风险与回滚思路
- 所有接口字段均为向后兼容增量字段（保留 `provider_id`/`model_id`，新增 `provider_name`/`model_name`/`model_code`），不影响已有调用方；回滚仅需还原上述文件。
