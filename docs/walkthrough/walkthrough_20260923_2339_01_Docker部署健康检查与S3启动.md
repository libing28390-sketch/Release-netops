# 完成记录：Docker 部署健康检查与 S3 启动

## 完成摘要
- Docker liveness 检查改为无代理访问 `127.0.0.1`，冷启动宽限提升到 120 秒；避免部署机代理变量干扰本地探针，并给首次启动迁移留出时间。
- 部署脚本会规范化 `.env` 中 `STORAGE_BACKEND` 的空白、大小写、单/双引号及 CRLF。启用 S3 时自动选用 `object-storage` profile；启动遇到暂时依赖 unhealthy 时等待 netops 恢复 healthy，再用 `--no-build --pull never` 补启动服务，不重建或删除数据卷。
- 默认 Compose 模式仍使用 local 存储；SeaweedFS 仅在 S3 profile 启动。示例 endpoint 改为 Compose 内网地址 `http://seaweedfs:8333`，部署文档列出 S3 必填配置及直接 Compose 启动方式。
- 根因修复 SNMP Exporter v0.26 配置不兼容：默认模板与编译器改用 `labels` / `labelname` / `oid` / `type`；启动时对旧持久化 volume 中的 `source_indexes` / `lookup` 执行原子、幂等转换。SNMP exporter 仍等 netops healthy 后启动，以确保 volume 迁移先完成。

## 实际修改文件
- `docker-compose.yml`
- `Dockerfile`
- `scripts/deploy-docker.sh`
- `.env.example`
- `docs/deploy/docker.md`
- `backend/services/monitoring_compiler.py`
- `backend/services/monitoring_oid_catalog.py`
- `backend/services/monitoring_runtime_normalizer.py`
- `monitoring/snmp-exporter/snmp.yml`
- `backend/tests/release/test_deploy_docker_storage_contract.py`（新增）
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `docs/plans/plan_20260923_2339_01_Docker部署健康检查与S3启动.md`
- `docs/walkthrough/walkthrough_20260923_2339_01_Docker部署健康检查与S3启动.md`

## 验证命令与结果
- `.venv\Scripts\pytest.exe backend/tests/release/test_deploy_docker_storage_contract.py backend/tests/release/test_deploy_docker_redis_contract.py -q`：8 passed。
- `C:\Program Files\Git\bin\bash.exe -n scripts/deploy-docker.sh`：通过。
- `.venv\Scripts\pytest.exe backend/tests/monitoring/test_monitoring_v1_compiler.py -q`：21 passed。
- `.venv\Scripts\pytest.exe backend/tests/monitoring/test_monitoring_v1_deployment_contract.py -q`：4 passed。
- `npm run test:frontend -- --run src/pages/IPVlan/prefixExport.test.ts src/utils/topologyRoleLayout.test.ts src/utils/topologySiteOverview.test.ts`：3 个文件、20 tests passed。
- `npm run lint`：通过。
- `npm run build -- --outDir C:\Users\NINGMEI\AppData\Local\Temp\netops-integration-build-20260924-0004`：通过，Vite 转换 4288 个模块并完成生产构建。
- `git diff --check`：通过。

## 未执行验证与原因
- 未连接用户 Linux 主机执行 Compose 更新，也未在远端读取 Docker daemon 状态；新镜像/脚本发布到服务器后，需运行部署脚本应用修复，并核实 `nexora-snmp-exporter` 转为 healthy。
- 未在真实 SeaweedFS 服务上传对象或运行历史存储迁移；凭据与现有存储数据都未触碰。

## 剩余风险与回滚
- S3 sidecar 只在 `STORAGE_BACKEND=s3` 时启动。直接运行 Compose 必须使用 `--profile object-storage`；推荐使用项目部署脚本自动选择 profile。启用 S3 前必须设置 endpoint、bucket 和有效凭据。
- runtime normalizer 在旧配置无法对应到同模块指标时会安全跳过并保留文件，Exporter 仍会报解析错误；部署日志会显示 normalization skipped，需针对该定制 lookup 补上 OID/type 映射。
- Docker 冷启动上限默认 120 秒；超过仍失败时脚本保留 Compose 原始错误和当前 health 状态，并可通过 `NETOPS_STARTUP_RECOVERY_TIMEOUT_SECONDS` 调整等待时间。
- 回滚恢复上述 Compose、Dockerfile、脚本、配置和编译器文件即可；不删除 PostgreSQL、monitoring、S3 或应用卷。
- 前端生产构建输出保留在系统临时目录 `C:\Users\NINGMEI\AppData\Local\Temp\netops-integration-build-20260924-0004`。先前对旧构建输出目录执行的递归清理命令被执行策略拒绝，因此 `C:\Users\NINGMEI\AppData\Local\Temp\netops-prefix-topology-build-20260923-2330` 仍保留；仓库 `dist` 未覆盖。
