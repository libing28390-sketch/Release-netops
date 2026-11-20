# 优化 Copilot 通用问答与 Trace 调试面板

## 任务背景
在用户使用 AI Copilot 时，发现以下三个体验与功能问题：
1. **通用问题（如“今天是几月几号”、“你是什么模型”）被机械式拒答**：
   - 根本原因：System Prompt 过于严苛地限制了“如果提供的数据事实中没有该项，则必须回答无法获取”，且 Prompt 中未注入系统当前真实日期与时间、未区分通用对话/常识与网络设备事实。
2. **通用提问时展示了不相关的“网络诊断摘要卡片”**：
   - 根本原因：`build_copilot_contract` 针对所有请求（包括 `general_qa`）无差别生成了 `missing: ['vendor', 'model', 'version', 'impact_scope']`，导致前端在用户询问普通问题时也渲染了网络设备排障卡片。
3. **开发者调试 Trace (Inspector) 面板部分字段显示“未上报”**：
   - 根本原因：流式 SSE 返回的 `route_meta`（包含实际路由模型 `model_id`、总耗时 `duration_ms`、`input_tokens`、`output_tokens`）未被前端完整保存到当前消息对象 `m` 中，导致 Inspector 抽屉中 Route Model 与 Token 开销显示为“未上报”。

## 拟修改文件
1. `backend/ai/services/assistant.py`：
   - System Prompt 中注入系统当前时间（`Current System Time`），并区分通用对话/常识与网络资产查询约束；
   - 在流式返回与直接返回中，确保 `route_meta` 携带完整遥测（`model_id`, `provider_id`, `input_tokens`, `output_tokens`, `latency_ms`）。
2. `backend/ai/services/copilot_contract.py`：
   - 当 `intent in {"general_qa", "consultation"}` 且没有关联具体网络设备上下文时，不生成冗余的硬件字段缺失清单与排障步骤建议。
3. `src/pages/ai/Copilot/AssistantTab.tsx`：
   - `ChatMessage` 接口扩充 `route_model`, `provider_id`, `input_tokens`, `output_tokens`, `latency_ms`；
   - SSE 处理函数中完整保存 `meta` 和 `done` 中的遥测数据；
   - 通用问答场景下仅在存在实际诊断上下文或待补证据时展示诊断卡片。
4. `src/pages/ai/Copilot/CopilotInspectorDrawer.tsx`：
   - 确保路由模型、Token 开销与耗时正常呈现。

## 实施步骤
1. 修改 `backend/ai/services/copilot_contract.py`，规范化 `general_qa` 下的合约内容。
2. 修改 `backend/ai/services/assistant.py`，优化 Prompt 引导、注入系统时间并完善遥测数据下发。
3. 修改 `src/pages/ai/Copilot/AssistantTab.tsx` 与 `CopilotInspectorDrawer.tsx`，完善前端数据绑定与卡片展示逻辑。
4. 运行 `pytest backend/tests/ai/` 与 `npm run lint` 验证。

## 验证计划
- 自动化测试：运行 pytest 确保所有测试通过；
- 场景测试：测试通用提问（日期、打招呼）的大模型响应与 Trace 数据。
