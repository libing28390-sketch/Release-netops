# Provider 连通性安全分类修复

## 问题

Provider 页面连接测试在 8 ms 内返回 `AI_SECURITY_BLOCKED`。PostgreSQL 只读检查确认外部 AI 出口已启用、全局 Kill Switch 未触发、Provider 和绑定模型均启用。

## 根因

DeepSeek Provider 的允许分类上限是 `PUBLIC`。固定探测文本没有敏感发现，通用分类器的默认结果是 `L1_GENERAL/INTERNAL`，因此请求在安全网关内被正确拦截，尚未访问 DeepSeek。

## 修复

1. 固定探测请求显式标记为 `PUBLIC`，只允许这一条无业务数据的探测绕过分类歧义。
2. 网关保留具体安全拒绝码，便于区分分类、策略、Kill Switch 等原因。
3. Provider 编辑页增加允许数据分类选择器；提升到 `INTERNAL` 或 `CONFIDENTIAL` 必须由管理员明确保存。
4. 连通性测试完成后立即更新列表卡片的健康状态，避免成功后仍显示旧的失败徽标。
5. `data_region=unknown` 明确显示为“区域: 未配置”，并在表单提供合规区域选择；未知区域不自动推断或写入。

## 验证

- PostgreSQL read-only probe：策略启用、Kill Switch 关闭、Provider/Model 启用；无生产写入。
- 后端聚焦：18 passed；相关 LLM/Security/API/Provider 回归：21 passed。
- 前端 Provider：3 passed；TypeScript lint PASS；Vite build PASS。
- 未使用 SQLite；未发送真实外部 Provider 请求。
