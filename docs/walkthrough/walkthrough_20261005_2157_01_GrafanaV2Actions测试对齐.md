# Grafana V2 Actions 测试对齐

## 完成摘要

用户提供的 Actions 运行有 2,799 项通过、1 项跳过、1 项失败。唯一失败测试不仅用了 V2 之前的色板断言，也检查了未应用 V2 presentation 的基础 builder。测试现已改为读取最终 `build_dashboard_catalog()` 结果，并按当前 V2 语义检查颜色、利用率显示和表格状态文本着色。

S3 侧已有 cAdvisor 容器资源观测：CPU、内存、磁盘读写速率与容器最后观测时间。当前没有 SeaweedFS `/data` 剩余空间或 S3 bucket 实际对象容量的展示/预警，因此不能把容器 CPU/磁盘 I/O 面板视为 S3 空间预警。

配置备份策略默认保留 90 天、每设备最多 30 个版本。保留清理在策略备份执行后触发，不由独立清理任务运行。存储位置由全局 storage provider/`config_backup` usage binding 决定，不是每条策略单独选择；迁移后的默认路由优先使用数据库默认 profile，没有时使用 `STORAGE_BACKEND` 环境配置。给出的虚机 `docker ps` 中 SeaweedFS 正在运行，说明 S3 profile 已启动，但不能仅凭此确认应用实际选用的 storage binding。

## 实际修改文件

- `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
- `docs/plans/plan_20261005_2157_01_GrafanaV2Actions测试对齐.md`
- `docs/walkthrough/walkthrough_20261005_2157_01_GrafanaV2Actions测试对齐.md`

## S3 容器监控核对

- Compose 启动 cAdvisor，`platform_cadvisor` job 每 30 秒抓取 `cadvisor:8080/metrics`；给出的 `docker ps` 显示 `nexora-cadvisor` 与 `nexora-seaweedfs` 都在运行。SeaweedFS 运行且 cAdvisor 能枚举到它时，平台健康 Dashboard 的通用容器指标会按容器名称展示它。
- Dashboard 有容器 CPU、内存、磁盘读写速率、观测数和观测清单；没有 SeaweedFS 专属采集目标或实际 `/data` 总量、已用量、可用量面板。
- `/api/storage/status` 对 S3 使用 `ListObjectsV2(MaxKeys=1)` 检查连接/列表权限，生命周期数字来自应用数据库记录，不是远端对象字节总和，也不代表磁盘空间。
- 应用资源健康检查调用 `shutil.disk_usage(PROJECT_ROOT)`；默认 disk warn/critical 阈值为 80%/90%，但 `PROJECT_ROOT` 是 netops 容器中的应用路径，不能保证等于 SeaweedFS 的 `/data` volume 所在文件系统。因此这不是可靠的 S3 容量预警。
- SeaweedFS 镜像为可变 `latest`；没有虚机运行版本、挂载源路径及实际 `df`/`du` 输出。本次没有假定特定 SeaweedFS 指标端点，也未远程改动部署。

## 验证命令与结果

- `pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py::test_wireless_and_interface_dashboards_share_reference_semantic_colors --noconftest -q -p no:cacheprovider`：1 passed。
- `pytest backend/tests/monitoring/test_grafana_v2_presentation.py --noconftest -q -p no:cacheprovider`：40 passed。
- 未重跑 2,799 项全量 Actions；以上是本地针对失败合同及相关 V2 presentation 的聚焦验证。
- S3 部分为 Compose、vmagent scrape 配置、Dashboard PromQL、storage API、provider binding migration 和 health API 静态检查；未连接虚机、不运行 Docker/S3 操作。

## 未验证项与剩余风险

仍需在部署虚机读取 SeaweedFS 容器挂载源及 `/data` 的 `df -h`/`du -sh`，确认 cAdvisor 指标中实际有该容器。需新增真实 volume/宿主文件系统容量采集与告警规则后，才能承诺 S3 容量预警；还未验证 SeaweedFS 镜像 digest、`weed version`、空间告警投递或部署端数据。
