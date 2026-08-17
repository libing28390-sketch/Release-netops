# EVAL-011 Evidence

## Task ID

EVAL-011

## 目标

覆盖 Provider CRUD、模型切换、Fallback、权限和密钥安全测试，并以 PostgreSQL 作为唯一持久化验收数据库。

## 修改文件

- `docs/knowledge-engine-v2/architecture/EVAL-011-PROVIDER-MODEL-SECURITY-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval011_provider_model_security_check.py`
- `tests/knowledge_engine_v2/test_eval011_provider_model_security.py`
- `docs/knowledge-engine-v2/eval/eval-provider-model-security-v1.manifest.json`
- `docs/walkthrough/20260817_eval011_provider_model_security.md`

现有实现和复用的权威测试：

- `scripts/knowledge_engine_v2_llm_pg_probe.py`
- `backend/tests/ai/test_llm_001_037_multi_provider.py`
- `backend/tests/ai/test_sec_001_020_security_gateway.py`
- `backend/tests/ai/test_security_gateway.py`
- `backend/tests/ai/test_api_v2_contracts.py`
- `scripts/knowledge_engine_v2_v1_baseline_pg.py`

## 实现内容

- 冻结 EVAL-011 覆盖矩阵：Provider CRUD、模型偏好/场景切换、兼容性 Fallback、tenant/role/user ACL、AES-256-GCM 密钥轮换/失效/脱敏、稳定错误码。
- 新增 coverage validator，逐项核对 `LLM-001-037-POSTGRES-TEST-PLAN.yaml`、PostgreSQL 回滚探针、后端契约测试和安全/API 合同测试；拒绝 SQLite 验收证据。
- 新增 EVAL-011 测试：强制 `DATABASE_URL` 为 PostgreSQL，并以子进程执行真实 PG 探针，确认迁移/fixture 事务最终 rollback。

## 执行命令

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval011_provider_model_security_check.py
.venv\Scripts\python.exe scripts\knowledge_engine_v2_llm_pg_probe.py
.venv\Scripts\pytest.exe backend/tests/ai/test_llm_001_037_multi_provider.py backend/tests/ai/test_sec_001_020_security_gateway.py backend/tests/ai/test_security_gateway.py backend/tests/ai/test_api_v2_contracts.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests\knowledge_engine_v2\test_eval011_provider_model_security.py -q -p no:cacheprovider
.venv\Scripts\python.exe scripts\knowledge_engine_v2_v1_baseline_pg.py
npm.cmd run lint
npm.cmd run build
.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval011_provider_model_security_check.py tests\knowledge_engine_v2\test_eval011_provider_model_security.py
git diff --check
```

## 测试结果

PASS。

- Coverage validator：`status=PASS`；六类覆盖全部为 true；`database=postgresql`；`sqlite=not_used`；`rollback=probe_transaction`。
- PostgreSQL LLM probe：PASS；`multi_provider=true`、`route_fallback=true`、`acl_tenant_scoped=true`、`key_rotation=true`、`key_audit=true`、`duplicate_model_rejected=true`、`rollback=true`。
- Provider/Model/Security/API 后端契约回归：`33 passed`。
- EVAL-011 PostgreSQL wrapper：`2 passed`。
- V1 PostgreSQL baseline：`10/10`，retrieval_accuracy `1.0`，wrong_vendor_rate `0.0`，version_conflict_rate `0.0`，citation_accuracy `1.0`，transaction rollback。
- Frontend TypeScript lint：PASS。
- Vite production build：PASS；仅保留既有大 chunk warning。
- Python compile / `git diff --check`：PASS。

## 数据库影响

- 探针使用本机 PostgreSQL `netops` 开发库，迁移、临时 Provider/Model/ACL/Key rows 均处于显式事务，结束时 rollback；无生产数据库写入。
- 未使用 SQLite；无新增 migration。

## 安全影响

- Provider API contract 禁止响应 `api_key`；密钥只验证 master-key、加密存储、mask 和轮换审计，不打印明文。
- Security Gateway 测试覆盖凭据/DLP、Prompt Injection、未知 Provider、分类与区域拒绝。
- 报告不包含 Provider secret、原始 prompt、SQL 或响应正文。

## 回滚方式

- 应用回滚：停用新 Provider/Model/Route，恢复已验证 V1 默认路由。
- 数据回滚：探针事务已回滚；没有需执行的生产 migration rollback。

## 已知限制

- Provider/Model 真实外部连通性未执行，避免访问真实厂商；健康测试继续使用安全网关探针/fixture。
- 前端交互浏览器关键路径属于 EVAL-017，当前仅完成 lint/build。

## 最终结论

PASS
