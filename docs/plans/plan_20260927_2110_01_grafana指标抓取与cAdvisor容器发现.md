# Grafana 指标抓取与 cAdvisor 容器发现

## 任务目标

- 修复 Grafana 指标目标访问 `/metrics` 时重定向到公网 HTTPS 子路径、导致 vmagent 抓取失败的问题。
- 修复 cAdvisor 通过 Docker API 发现容器后，因容器内缺少宿主 Docker overlay2 元数据目录而无法建立容器资源序列的问题。
- 保留并说明现有 Docker 容器资源看板覆盖全部非空容器名的查询语义。

## 现状与证据

- vmagent 可解析并访问 `grafana:3000`；`/metrics` 返回 301 到公网 HTTPS 路径并证书失败，而 `/grafana/metrics` 返回 HTTP 200。目标机 runtime scrape 文件仍使用旧 `/metrics`。
- cAdvisor `/metrics` 可访问，但返回的 CPU、内存、磁盘及 `container_last_seen` 样本均只有 `id="/"`，VictoriaMetrics 中也只有根 cgroup 的 `container_last_seen` 序列。
- vmagent 当前已清空代理变量并配置 Docker 内部服务 `NO_PROXY`；本次直接请求证实 Grafana 子路径 endpoint 可采集。
- Socket Proxy 对 `/containers/json` 返回 HTTP 200 和 11 个容器对象。cAdvisor 日志显示它尝试读取 `/var/lib/docker/image/overlay2/layerdb/mounts/<container-id>/mount-id`，但该路径在 cAdvisor 容器内不存在；当前 Compose 只挂载 `/sys`。

## 影响范围

- vmagent 静态基线抓取配置及本地采集器运行时编译配置中的 Grafana metrics path。
- cAdvisor Compose 中 Docker Root Dir 的只读挂载及其部署说明。
- 相关监控编译与 Compose 部署契约测试。

## 实施步骤

1. 为 `platform_grafana` 的内部 scrape 配置指定 `/grafana/metrics`，保持 Nginx 及 Grafana 面向用户的子路径设置不变。
2. 同步更新静态 `monitoring/vmagent/scrape.yml` 与 `backend/services/monitoring_compiler.py`，防止部署后生成配置覆盖静态修正。
3. 为 cAdvisor 以只读 bind mount 暴露宿主 Docker Root Dir 到容器内 `/var/lib/docker`；支持通过 `CADVISOR_DOCKER_ROOT_DIR` 适配非默认路径，并禁止 Compose 自动创建错误的空源目录。
4. 增加测试，验证平台 Grafana job 使用子路径，其他本地抓取目标保持 `/metrics`，cAdvisor 仅以只读方式挂载 Docker Root Dir，远端 collector 仍不包含平台内网目标。
5. 更新 Docker 部署文档，说明如何读取 `docker info` 的 Root Dir、配置可选路径并重建 cAdvisor。

## 验证计划

- 运行受影响的 monitoring compiler 与 deployment contract 定向测试。
- YAML/Python 解析和 `git diff --check`。
- 目标主机端验证 vmagent `/targets` 中 `platform_grafana` 无重定向/TLS 错误；验证 cAdvisor 原始指标出现 Docker 容器名称标签，并在 VictoriaMetrics 查询到对应序列。
- 当前代理无法访问目标 Linux 主机；不宣称目标运行时已验证。

## 风险与回滚

- `/grafana/metrics` 路径由现场 301 Location 验证；部署后仍需以 vmagent target 状态确认。
- Docker Root Dir 默认 `/var/lib/docker`，但有些主机自定义该位置；部署人员需核对 `docker info --format '{{.DockerRootDir}}'` 并按需配置变量。挂载为只读，不开放 Docker Socket 给 cAdvisor，也不启用 privileged/capabilities。
- 回滚可恢复两个 scrape 配置的 Grafana metrics path 为 `/metrics`，并移除 cAdvisor Docker Root Dir bind mount；不涉及业务数据或数据库迁移。
