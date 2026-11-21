# PostgreSQL 看板采集恢复记录

## 修复结果

修复了服务器启动时镜像默认配置覆盖已发布 PostgreSQL 抓取规则的问题，并将 PostgreSQL 性能看板加入 Nexora 的监控大盘列表。生产服务器现已恢复抓取；Nexora 页面的状态卡与 Top SQL 表格均显示数据。

## 根因

服务器共享运行目录已应用 collector-local v93，归档中包含 `platform_postgres_exporter` 抓取任务。主机重启后，`scripts/sync-frontend-dist.sh` 仍会用镜像默认 `vmagent/scrape.yml` 覆盖版本化运行文件，导致 vmagent 不再抓取 PostgreSQL exporter。Exporter 本身仍可返回数据库指标，Grafana 看板配置也仍存在。

同时，Grafana 中已有 UID 为 `nexora-postgres-performance` 的看板，但 Nexora 前端注册表没有对应入口。

## 代码变更

- `scripts/sync-frontend-dist.sh` 只在尚无 `current_version.json` 时用 defaults 初始化运行目录。已有发布版本时保留其 scrape 配置，仅补齐缺失的 Linux/Windows target 文件。
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py` 增加启动契约回归覆盖，验证初次初始化及版本化 scrape 配置保护。
- `src/pages/GrafanaDashboardPage.tsx` 增加“13 PostgreSQL 数据库性能”入口，指向既有 Grafana UID，并注明 Top SQL 仅按 Query ID 展示、不含 SQL 文本。

## 生产部署

- 目标服务器：`192.168.204.128`。
- 构建来源：服务器 `/data/nexora-automation` 的发布提交 `1344b6467d98634015a5dd92ff85c18c88c8a444` 的干净归档，只在临时目录修改上述脚本和看板注册表，未携带本地工作区其他未提交变更。
- 临时构建目录：`/tmp/nexora-pg-dashboard-build-20261010`。按锁文件安装 1,178 个依赖，Vite 处理 4,323 个模块并成功构建。
- 当前镜像标签：`nexora-netops:codex-postgres-dashboard-20261010-r2`，已标记为 `nexora-netops:latest`。发布前镜像保存在 `nexora-netops:rollback-20261010-pg-dashboard`。
- 部署中发现 Docker 文件复制会覆盖启动脚本的执行权限；最终镜像已显式验证脚本可执行，再替换应用容器。
- 运行配置恢复自 `versions/00000093/vmagent/scrape.yml`。恢复前后的文件备份位于 `/data/nexora-automation/artifacts/codex-postgres-dashboard-20261010/`。

## 验证结果

- 本地 `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：8 项通过。
- `bash -n scripts/sync-frontend-dist.sh`：通过。
- `npm run lint`：通过；隔离目录生产构建：成功。
- 服务器运行目录 `sha256sum -c checksums.sha256`：9 项全部通过；恢复后的 scrape 文件 SHA-256 为 `08d9661c91e7abf95cb722f7b9949c4d2e370e10827f3052e9802abd84c7edcf`。
- vmagent active targets 为 40 个，`platform_postgres_exporter` 状态 `up` 且无 lastError。应用容器及 vmagent 均 healthy，重启计数为 0。
- VictoriaMetrics 查询结果：`up{job="platform_postgres_exporter"}=1`；`pg_scrape_collector_success{collector="stat_statements"}=1`；`pg_stat_statements_calls_total` 有 100 条时间序列。
- 浏览器打开 `https://192.168.204.128/monitor/dashboards`，第 13 张入口成功切换到 UID `nexora-postgres-performance`。页面显示 Exporter 与 `pg_stat_statements` 状态为“正常”，并可见调用速率、执行耗时、Rows、Shared Buffer 命中率以及 Top SQL 两张表的实时行。

## 回退

如需恢复发布前应用镜像，在服务器 `/data/nexora-automation` 执行：

```bash
docker image tag nexora-netops:rollback-20261010-pg-dashboard nexora-netops:latest
docker compose -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate netops
```

若回退镜像启动覆盖运行配置，再从 `/data/nexora-automation/artifacts/codex-postgres-dashboard-20261010/scrape-v93.yml` 恢复到 monitoring artifacts 的 `runtime/vmagent/scrape.yml`，并仅重启 vmagent。
