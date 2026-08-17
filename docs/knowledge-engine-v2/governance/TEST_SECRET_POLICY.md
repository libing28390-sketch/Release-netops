# V2 测试环境密钥与配置政策

**Task ID：** GOV-006  
**强制范围：** development、test、shadow、preprod，以及所有 CI/本地 V2 测试进程

## 1. 结论

测试环境不得使用生产 API Key、真实生产密码、生产数据库/Redis、真实设备凭据或未脱敏配置。策略采用 fail-closed 校验：没有明确的非生产环境、隔离资源、mock/sandbox AI 和密钥命名空间，测试不得启动。

仓库审计发现根目录 `.env` 当前声明 `ENVIRONMENT=production`，且 `.env.example`/Compose 包含示例默认凭据。它们不属于 V2 测试输入；测试命令必须显式注入 `ENVIRONMENT=test` 和隔离的 `DATABASE_URL`，不得加载或复制根目录 `.env` 的值。

## 2. 配置来源

1. **提交文件：** 只能包含空值、`${TEST_*}` 引用、`secret://nexora-kb-v2/<env>/...` 或 `vault://...` 引用；禁止任何真实 key/password/token。
2. **CI 运行时：** 使用 CI Secret Store 的 test 命名空间；日志不得打印环境变量。使用 `scripts/validate_kb_v2_test_config.py --source runtime` 做启动前检查。
3. **影子/预生产：** 使用独立 Secret Manager namespace 和只读/沙箱账号；生产 API key、生产设备密码和生产数据库角色一律拒绝。
4. **`.env`/`.env.local`：** 是本地运行时文件，不得复制到测试 artifacts、Docker image、Evidence 或 release tree；发现 `ENVIRONMENT=production` 时直接拒绝作为测试输入。V2 验收持久化统一使用隔离 PostgreSQL；SQLite 不作为验收证据。

## 3. 强制安全值

测试配置必须显式设置：

- `ENVIRONMENT` 为 `development`/`test`/`shadow`/`preprod`，不能是 `production`；
- `AI_GATEWAY_MODE=mock|sandbox|offline`，`AI_ENABLED=false`、`EXTERNAL_AI_ENABLED=false`；
- `KNOWLEDGE_V2_ENABLED=false`、`KNOWLEDGE_V2_WRITE_ENABLED=false`、`NETWORK_WRITE_ENABLED=false`、`PRODUCTION_CREDENTIALS_ALLOWED=false`；
- `KNOWLEDGE_V2_ROLLOUT_PERCENT=0`，通过 Gate 后才能修改；
- `DATA_CLASSIFICATION=synthetic|sanitized`、`DEVICE_CREDENTIAL_SOURCE=fixture|synthetic|sandbox|readonly`；
- `KB_V2_SECRET_NAMESPACE=nexora-kb-v2/<environment>`；
- 数据库/Redis 地址只允许独立的非生产主机、数据库名和逻辑库，不得出现 `prod`、`production` 或 `live` 标记。

## 4. 校验器与 CI 接入

机器校验器：

```powershell
.venv\Scripts\python.exe scripts/validate_kb_v2_test_config.py `
  --file docs/knowledge-engine-v2/governance/test-environment.example `
  --environment test
```

校验器不会输出任何配置值；失败时只报告配置键和规则。CI 在 pytest 前执行同一校验，运行进程显式使用 test 环境变量和隔离 PostgreSQL 资源。若本地 shell 已加载根目录 `.env`，必须先清除生产变量或在隔离进程中覆盖，不能通过 `--source runtime` 为生产值背书。

## 5. 违规处置

发现生产 key、真实密码、未脱敏数据或生产资源地址时：立即停止测试、撤销/轮换凭据、隔离 artifacts、创建 SEC Incident 和 Evidence；不得把失败配置提交为“通过”。V2 测试不需要真实厂商/设备凭据，使用 fixture、录制回放或沙箱即可继续非依赖任务。
