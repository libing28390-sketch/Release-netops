# EVAL-020 Evidence

- Task ID：EVAL-020
- 目标：执行依赖、Secret、权限、日志和错误响应安全检查。
- 状态：PASS
- 执行日期：2026-08-17

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-020-SECURITY-GATE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval020_security_check.py`
- `tests/knowledge_engine_v2/test_eval020_security.py`
- `docs/knowledge-engine-v2/eval/eval-security-gate-v1.json`
- `docs/knowledge-engine-v2/governance/TEST_SECRET_POLICY.md`
- `backend/ai/gateway/router.py`
- `backend/ai/security/rate_limit.py`
- `backend/ai/api/assistant.py`
- `backend/ai/api/security.py`

## 实现内容

- 依赖门禁执行 Python `pip check`、`package-lock.json` JSON 完整性和 npm lock-only 解析；不输出依赖环境中的 Secret/DSN。
- Secret 门禁复用 V2 test-config validator，验证安全配置通过并验证字面量 Secret 被 fail-closed 拒绝；扫描 AI runtime 与前端源文件 415 个文件，0 个生产 Secret 字面量，报告不保存匹配值。
- 权限门禁用 Python AST 盘点 `backend/ai/api` 的 96 个路由，96/96 使用 `require_ai_permission`，覆盖率 100%。
- 日志门禁扫描 AI runtime 97 个文件，并执行现有日志/Trace 脱敏回归；发现并修复模型路由与 Redis 限流日志中的原始异常文本，统一只记录稳定异常类型。
- 错误响应门禁检查 AI exception 的稳定 `code/message/request_id/details` 结构，禁止 `HTTPException` 回显异常文本；目录和安全事件接口改为稳定错误码与通用消息。
- 治理文档明确 V2 验收持久化统一使用隔离 PostgreSQL，SQLite 不作为验收证据。

## 执行命令与结果

1. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe scripts\\knowledge_engine_v2_eval020_security_check.py`
   - PASS；总耗时 3.106 秒。
   - pip check 退出码 0；npm lock-only 退出码 0；Secret validator 安全配置通过且字面量拒绝通过。
   - AI 路由权限 96/96；日志静态发现 0；错误响应静态发现 0；报告不含 Secret。
   - PostgreSQL V1 baseline 退出码 0；production_database_write=false；rollback=transaction_rollback；sqlite=forbidden。
2. `$env:PYTHONPATH='backend'; .venv\\Scripts\\pytest.exe tests\\knowledge_engine_v2\\test_eval020_security.py -q -p no:cacheprovider`
   - PASS：4 passed。
3. `$env:PYTHONPATH='backend'; .venv\\Scripts\\pytest.exe backend/tests/ai/test_sec_001_020_security_gateway.py backend/tests/ai/test_security_gateway.py backend/tests/ai/test_provider_auth_failure_surface.py backend/tests/ai/test_provider_connection_security_fix.py backend/tests/ai/test_obs001_retrieval_observation.py backend/tests/ai/test_obs004_request_id_correlation.py backend/tests/ai/test_obs008_database_observability.py backend/tests/ai/test_api003_typed_requests.py backend/tests/ai/test_api004_response_contract.py backend/tests/ai/test_api006_sse_contract.py backend/tests/ai/test_api007_sse_idempotency.py backend/tests/ai/test_llm_001_037_multi_provider.py -q -p no:cacheprovider -p no:conftest`
   - PASS：64 passed in 5.23 秒；未使用 SQLite conftest。
4. `$env:PYTHONPATH='backend'; .venv\\Scripts\\python.exe -m py_compile scripts/knowledge_engine_v2_eval020_security_check.py tests/knowledge_engine_v2/test_eval020_security.py backend/ai/gateway/router.py backend/ai/security/rate_limit.py backend/ai/api/assistant.py backend/ai/api/security.py`
   - PASS。
5. `npm.cmd run lint`
   - PASS：TypeScript `tsc --noEmit`。
6. `npm.cmd run build`
   - PASS：Vite 3680 modules transformed；仅有既有大 chunk warning；构建产物已恢复，未提交 `dist` 变化。
7. `git diff --check`
   - PASS。

## 数据库影响

- 无生产 DDL、无生产业务数据写入。
- V1 权威回归使用现有 PostgreSQL 18.4，基线夹具在单事务内写入并 rollback；SQLite 未参与验收。

## 安全影响

- Provider/AI runtime 的原始 API Key、密码、Token、异常文本和 Provider body 不进入报告、日志或错误响应。
- 所有 AI API 路由继续经过显式 AI permission dependency；权限盘点为 100%。
- Provider 认证/网关失败保持稳定错误码；错误响应不暴露内部异常文本。
- 未发送外部 Provider 请求、未执行网络设备写命令。

## 审计与监控

- 机器报告：`docs/knowledge-engine-v2/eval/eval-security-gate-v1.json`。
- 关键源文件和合约可通过 Git commit 追溯；报告只记录计数、状态、退出码、耗时和回滚语义。

## 回滚方式

- 回滚 EVAL-020 提交即可恢复四处稳定错误响应/日志改动、契约、脚本、测试、报告和治理文档。
- 无生产 schema/data 回滚动作；V1 基线仅执行事务 rollback。

## 已知限制

- 静态日志扫描以 AI runtime 为边界；非 AI 旧版网络/身份 API 不被本任务伪装为已完成的全仓库安全重构。
- npm 依赖只做 lock-only 完整性与本地解析，不执行外部供应链审计或升级操作。

## 最终结论

**PASS** — 依赖、Secret、AI 路由权限、AI 日志脱敏、稳定错误响应、PostgreSQL V1 回归、Lint、Build、编译和 diff 检查全部通过；EVAL-020 可进入后续 MIG-001。
