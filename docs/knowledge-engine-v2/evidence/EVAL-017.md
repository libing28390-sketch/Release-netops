# EVAL-017 Evidence

- Task ID: EVAL-017
- 目标：完成 Copilot、Provider、Model、Knowledge、Security 浏览器关键路径测试。
- 状态：PASS_AUTOMATED_USER_VERIFY_PENDING
- 执行日期：2026-08-17

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-017-BROWSER-KEYPATH-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval017_browser_check.py`
- `tests/knowledge_engine_v2/test_eval017_browser.py`
- `src/pages/ai/Copilot/keypaths.test.tsx`
- `src/pages/ai/Models/ModelManagementTab.test.tsx`
- `src/pages/ai/Providers/ProviderManagementTab.test.tsx`
- `src/pages/ai/Security/SecurityPolicyTab.test.tsx`
- `docs/knowledge-engine-v2/eval/eval-browser-keypaths-v1.manifest.json`

## 实现内容

- Copilot：问题发送、模型切换、诊断范围、会话头部操作和 SSE 事件版本覆盖。
- Provider：脱敏 API Key、网关连通性结果、添加流程、空状态和可恢复错误覆盖。
- Model：Provider/Model 关联、用户默认模型、场景路由切换、添加流程和空列表覆盖。
- Knowledge：导入任务进度/重试、分页、RAG PostgreSQL 回归展示、Trace 脱敏、错误和响应式布局覆盖。
- Security：默认拒绝、出口开关确认、策略演练（无外部调用）、事件空状态和错误覆盖。
- 路由：Provider/Security 路由映射与 403 安全 API 错误契约覆盖。

## 执行命令与结果

1. `$env:PYTHONPATH='backend'; .venv\Scripts\python.exe scripts/knowledge_engine_v2_eval017_browser_check.py`
   - PASS；前端 14 个测试文件 / 52 passed。
   - V1 PostgreSQL baseline：10/10；retrieval_accuracy=1.0；citation_accuracy=1.0；wrong_vendor_rate=0；version_conflict_rate=0；rollback=transaction_rollback。
   - `database=postgresql`；前端组件测试 `database=none`；`sqlite=not_used`。
2. `$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval017_browser.py -q -p no:cacheprovider`
   - PASS：2 passed in 16.35s。
3. `npm.cmd run lint`
   - PASS：TypeScript `tsc --noEmit`。
4. `npm.cmd run build`
   - PASS：Vite 3680 modules transformed；仅产生可回滚的构建产物哈希变化，未纳入本任务提交。
5. `git diff --check`
   - PASS。

## 已认证浏览器可见检查

- `/ai/providers`：页面标题、Provider 数量、AES-256、脱敏 Key 和安全网关提示可见；未执行真实 Provider 连通性写操作。
- `/ai/models`：模型表格、Provider 关联、场景路由和“添加 Model”入口可见。
- `/ai/copilot`：Copilot 空会话、模型选择器、诊断范围、发送按钮和只读提示可见。
- `/ai/knowledge`：文档/版本、Source Registry、RAG Evaluation、Retrieval Trace 四个视图入口可见。
- `/ai/security`：安全网关标题、策略状态、出口控制和演练入口可见。
- 窄屏 390px 请求（浏览器实际 CSS viewport 433px）：Copilot 与 Knowledge 均可见，`bodyScrollWidth == innerWidth == 433`，无横向溢出。
- 浏览器当前已认证会话可用；仍需用户在页面上完成一次可见确认，才能将正式 Checkbox 从 `[ ]` 改为 `[x]`。

## 本轮浏览器复查（2026-08-17）

- 使用当前已认证浏览器会话逐一访问 `/ai/providers`、`/ai/models`、`/ai/copilot`、`/ai/knowledge`、`/ai/security`。
- 五个页面在等待懒加载完成后均正常渲染；页面标题、关键控件和主要数据区域可见，页面正文没有“服务内部异常”、Unhandled/Traceback 或其他错误提示。
- `/ai/providers`、`/ai/models`、`/ai/copilot`、`/ai/security` 复查时浏览器 error/warn 日志为 0；Knowledge 页面复查日志同样为 0。
- Model、Copilot、Knowledge 首次约 1.6–2 秒快照可能仍显示 Loading；继续等待约 8 秒后均完成渲染，属于前端懒加载延迟，不判定为服务故障。
- Copilot 窄屏复查：请求 viewport 390×844，浏览器实际 CSS viewport 为 433px；`bodyScrollWidth=433`、`documentElement.scrollWidth=433`、`innerWidth=433`，无横向溢出。
- 本轮只读查看，没有执行 Provider 连通性测试、真实外部 AI 请求、设备写操作或生产数据库写入。

## Provider 连通性问题修复（2026-08-17）

- 根因：PostgreSQL 中 DeepSeek Provider 的 `allowed_data_classification` 为 `PUBLIC`；固定探测文本没有敏感发现，通用分类器按安全默认归为 `L1_GENERAL/INTERNAL`，网关在外发前按 Provider 分类上限拒绝，导致 8 ms 的 `AI_SECURITY_BLOCKED`。
- 修复：Provider 探测接口显式声明固定探测请求为 `PUBLIC`；网关保护链路接受可选 `data_classification`；保护阶段的稳定 `reason_code` 不再被统一丢失；Provider 编辑表单新增 PUBLIC/INTERNAL/CONFIDENTIAL 选择并提交到 API；连通性测试完成后立即同步卡片健康状态，避免旧的 `AI_SECURITY_BLOCKED` 徽标残留。
- 回归：后端安全/Provider 聚焦 18 passed；LLM/Security/API/Provider 回归 21 passed；Provider 前端 3 passed；`npm run lint` PASS；`npm run build` PASS；`py_compile`/`git diff --check` PASS。
- PostgreSQL 只读探针确认：安全策略启用、全局 Kill Switch 关闭、Provider/模型启用；本次探针 `production_write=false`，未发送外部 Provider 请求。
- 当前 Provider 仍保持 `PUBLIC` 配置，未擅自扩大其数据外发范围；如需 Copilot 发送 INTERNAL 内容，应在 Provider 编辑中明确选择 `INTERNAL` 并保存。
- 页面中的 `unknown` 标签对应 `data_region`，不是健康状态或错误码；当前 PostgreSQL Provider 行确实为 `data_region='unknown'`。前端已改为显示“区域: 未配置”，并提供 global/cn/us/eu 选择，避免裸 `unknown` 误导；不根据 URL 擅自推断区域。

## 数据库影响

- 无生产 DDL、无生产数据写入。
- V1 权威回归使用 PostgreSQL；脚本从 `.env` 读取 PostgreSQL URL，仅运行临时事务基线。
- SQLite 未参与本任务任何验收；硬编码 SQLite fixture 不作为证据。

## 安全影响

- 测试确认 Provider 页面只展示脱敏 API Key，不渲染原始密钥。
- 403 权限拒绝仅展示稳定错误码、消息和 Request ID；未回显敏感请求体。
- Security dry-run 明确 `external_call_made=false`，不调用外部 Provider。
- Copilot UI 默认只读提示保持可见；未执行设备写命令。

## 审计与监控

- Provider/Security 现有 API Request ID、网关事件和安全事件审计路径保持不变。
- 关键路径报告保存在 `eval-browser-keypaths-v1.manifest.json`，包含源文件 SHA-256 和 PostgreSQL 基线指标。

## 回滚方式

- 回滚 EVAL-017 代码、测试、合约和证据提交即可；无数据库迁移。
- 构建产物 `dist/index.html` 已恢复原引用，未纳入本任务变更。

## 已知限制

- 真实浏览器路径依赖认证会话；本轮已通过已认证 Chrome 会话读取并验证页面，但按清单硬门槛仍等待用户确认。
- 未执行真实 Provider 连通性测试，避免向外部供应商发送请求；自动化测试使用 mock。

## 最终结论

自动化与 PostgreSQL/V1 质量门禁 PASS，浏览器可见检查 PASS；最终状态为 `PASS_AUTOMATED_USER_VERIFY_PENDING`，待用户完成可见确认后转为 `PASS`/`DONE`。
