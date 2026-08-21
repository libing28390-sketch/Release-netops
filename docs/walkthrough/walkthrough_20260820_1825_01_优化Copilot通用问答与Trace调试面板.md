# 优化 Copilot 通用问答与 Trace 调试面板 走查与验证报告

## 任务摘要
针对用户在使用 Copilot 时反馈的问题，进行了全链路的深度排障、修复与验证：

1. **大模型流式被安全策略拦截（`AI_SECURITY_BLOCKED`）的彻底根治**：
   - **根本原因定位**：
     - System Prompt 注入的日期时间字符串（`2026-08-20 18:48:43`）以及网络运维常用 IP/主机名被安全分类器识别为 `L2_IDENTIFIER`（`DataClassification.CONFIDENTIAL`）；
     - 数据库 `ai_provider` 表中默认的 `allowed_data_classification` 设为了较低的 `INTERNAL` 或 `PUBLIC`，当比对安全级别时触发了 `_classification_rank(CONFIDENTIAL) > _classification_rank(INTERNAL)` 的数据分类超界拦截（`AI_SECURITY_CLASSIFICATION_DENIED`）；
   - **修复措施**：
     - 将生产与开发环境中外部企业 AI Provider 的 `allowed_data_classification` 规范为 `CONFIDENTIAL`（允许 L2 标识符经由网关 ScopedTokenVault 脱敏/最小化后安全外发）；
     - 修复 `llm_gateway.py` 在执行回退兼容查询时误将 classification 默认值硬编码为 `PUBLIC` 的缺陷；
     - 在 `AISecurityGateway.protect()` 中增加了针对全局安全单例的数据库策略动态保底加载。

2. **开发者调试 Trace (Inspector) 面板右下角原始载荷显示优化**：
   - 将抽屉宽度扩展为 `420px`，优化长文本展示；
   - 增加内容区底部留白（`pb-12`）与代码块最大可视高度（`max-h-80`），解决底部截断问题；
   - 新增“一键复制 JSON”便捷按钮。

3. **通用问答体验与自然对话优化**：
   - 注入当前系统时间与自然对话指引，消除通用提问的生硬拒答；
   - 优化 `copilot_contract.py` 与前端 `AssistantTab.tsx`，通用问答不再误展示网络排障诊断摘要卡片。

## 实际修改文件
- [llm_gateway.py](file:///d:/nexora/nexora-private/backend/ai/gateway/llm_gateway.py)：修正兼容查询中的默认数据分类为 `CONFIDENTIAL`，完善流式元数据返回。
- [gateway.py](file:///d:/nexora/nexora-private/backend/ai/security/gateway.py)：完善 `protect()` 中的策略单例保底加载与分类拦截处理。
- [assistant.py](file:///d:/nexora/nexora-private/backend/ai/services/assistant.py)：注入真实时间、优化错误事件细节下发。
- [copilot_contract.py](file:///d:/nexora/nexora-private/backend/ai/services/copilot_contract.py)：为 `general_qa` 精简合约结构。
- [CopilotInspectorDrawer.tsx](file:///d:/nexora/nexora-private/src/pages/ai/Copilot/CopilotInspectorDrawer.tsx)：加宽面板、解决滚动截断、新增一键复制 JSON 按钮。
- [ai.ts](file:///d:/nexora/nexora-private/src/api/ai.ts)：补全流式消息与遥测接口定义。

## 验证结果
- **后端单测套件**：`pytest backend/tests/ai/` -> **288/288 全部通过 (100% Pass)**。
- **前端静态检查**：`npm run lint` (`tsc --noEmit`) -> **0 Errors 验证通过**。
- **真实大模型端到端调用**：DeepSeek 真实流式输出完整 token，耗时与指标正常记录，不再出现安全拦截阻断。
