# 修复记录：Grafana 抓取与 cAdvisor 容器发现

## 问题现象

- Grafana 容器健康，但 vmagent 对 `grafana:3000/metrics` 的抓取收到 301，并被重定向到对外 HTTPS 子路径；vmagent 因证书校验失败无法抓取。
- cAdvisor 能访问 Docker API，但 CPU、内存、磁盘和 `container_last_seen` 仅出现 `id="/"` 的根 cgroup，没有容器身份标签。日志报告无法读取 overlay2 的 `layerdb/mounts/<container-id>/mount-id`。
- 用户现场 Docker API 返回 11 个容器；这只确认 API 可列出容器，不等于 cAdvisor 已成功关联并采集每个容器的指标。

## 根因

- Grafana 在 `/grafana` 子路径下提供指标，裸 `/metrics` 会重定向到外部 HTTPS URL；静态 vmagent 配置和本地 collector 运行时编译配置都使用了旧路径。
- cAdvisor 容器没有宿主机 Docker Root Dir 的 overlay2 元数据，只挂载 `/sys`，无法将 Docker 容器 ID 与 cgroup 统计对应起来。

## 解决方案

- `platform_grafana` 改为抓取内部地址 `grafana:3000/grafana/metrics`，其他服务的 `/metrics` 路径保持不变。
- 将宿主 Docker Root Dir 以只读方式挂载到 cAdvisor 的 `/var/lib/docker`；通过 `CADVISOR_DOCKER_ROOT_DIR` 支持非默认目录，并禁止 Compose 为缺失目录自动创建空路径。
- 增加编译器与 Compose 契约断言，并记录主机路径检查、配置和重建步骤。
- 同提交保存本次计划、走查和修复记录，并纳入工作区已有的发布结果文档更新及交接记录。

## 实际修改文件

- `backend/services/monitoring_compiler.py`
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `docker-compose.yml`
- `docs/deploy/docker.md`
- `monitoring/vmagent/scrape.yml`
- `docs/plans/plan_20260927_2110_01_grafana指标抓取与cAdvisor容器发现.md`
- `docs/walkthrough/walkthrough_20260927_2110_01_grafana指标抓取与cAdvisor容器发现.md`
- `docs/plans/plan_20260927_1617_01_v1_0_9公有仓库同步.md`
- `docs/walkthrough/walkthrough_20260927_1617_01_v1_0_9公有仓库同步.md`
- `handoff.md`

## 验证命令与结果

- `.venv\Scripts\python.exe -m py_compile backend/services/monitoring_compiler.py backend/tests/monitoring/test_monitoring_v1_compiler.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：通过。
- Compose 与 vmagent YAML 解析、运行时 compiler 静态检查：通过；确认 Grafana 路径为 `/grafana/metrics`，cAdvisor 数据目录挂载只读且要求源目录存在。
- `git diff --check`：本修复记录创建前通过；提交前再次执行。
- 两个受影响 pytest 文件此前启动后卡在全局 PostgreSQL session fixture，未能完成；中止的运行不计为通过。

## 未验证项

- 尚未将本次文件部署到目标主机，没有重建 cAdvisor 或重启 vmagent，也没有验证部署后 Grafana scrape target 和 VictoriaMetrics 中的逐容器时序。
- Docker Compose CLI 与生产主机运行验证未执行。cAdvisor 是否采到磁盘读写还取决于主机内核及存储驱动提供的统计。

## 风险与回滚方式

- 部署前应使用 `docker info --format '{{.DockerRootDir}}'` 核对宿主路径；自定义 Docker 数据目录时设置 `CADVISOR_DOCKER_ROOT_DIR`。错误或不存在的路径会因 `create_host_path: false` 导致 Compose 拒绝创建容器，修正变量后可重建。
- 目标机部署后需检查 Grafana job 为 UP，并确认 `container_last_seen`、CPU 和内存时序带有容器身份标签。此次代码降低了已知空数据原因，但未在目标机验证，不能保证所有 11 个容器及所有磁盘指标必然有样本。
- 回滚时将静态与运行时 Grafana 抓取路径恢复为 `/metrics`，并移除 cAdvisor 的 `/var/lib/docker` bind mount；这些改动不涉及数据库或持久化业务数据。
