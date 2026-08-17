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
