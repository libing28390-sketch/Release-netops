# Grafana 指标抓取与 cAdvisor 容器发现 Walkthrough

## 当前诊断

- Grafana 容器本身健康；Nginx 入口与 vmagent 内部抓取是两条路径。现场从 `grafana:3000/metrics` 收到 `301`，Location 为 `https://192.168.204.128/grafana/metrics`，随后因为 vmagent 容器不信任目标 HTTPS 证书而失败。代理变量已确认为空；直接请求 `http://grafana:3000/grafana/metrics` 返回 `200 OK`。目标机当前 runtime scrape 仍使用 `/metrics`，尚未加载本次子路径修正。
- cAdvisor `/metrics` 可访问，但资源指标及 `container_last_seen` 只有 `id="/"`，没有容器名；VictoriaMetrics 同样仅有 `id="/"` 的一条观测序列。现有 `name!=""` 看板查询会过滤掉这条宿主根 cgroup，因此容器表与资源图没有数据。
- Socket Proxy 的 `/containers/json` 返回 `200 OK` 和 11 个容器对象，Docker API 列表访问正常。cAdvisor 日志显示它在容器内查找 `/var/lib/docker/image/overlay2/layerdb/mounts/<container-id>/mount-id` 失败；Compose 此前只挂载 `/sys`，没有挂载宿主 Docker Root Dir。
- cAdvisor 还记录了无法读取容器 PID smaps 的 warning；由于本平台禁用了 process 指标，这不解释 CPU、内存和 `container_last_seen` 全部仅有根 cgroup 的现象。

## 本次本地修改

- `monitoring/vmagent/scrape.yml`：`platform_grafana` 的 metrics path 改为 `/grafana/metrics`，保留内网 target `grafana:3000`。
- `backend/services/monitoring_compiler.py`：运行时编译出的本地 collector 配置同步使用 `/grafana/metrics`；其他服务仍为 `/metrics`。
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`、`backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：添加 scrape path 契约断言。
- `docker-compose.yml`：将宿主 Docker Root Dir 以只读方式挂载到 cAdvisor 内 `/var/lib/docker`；默认宿主路径 `/var/lib/docker`，支持 `CADVISOR_DOCKER_ROOT_DIR`，并禁止 Compose 为错误源路径创建空目录。
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：断言 Docker Root Dir mount 只读并要求源路径已存在。
- `docs/deploy/docker.md`：补充 Docker Root Dir 检查、非默认路径配置和 cAdvisor 重建步骤。

## 验证

- `python -m py_compile backend/services/monitoring_compiler.py`：通过。
- 监控 YAML 解析：通过。
- 调用 `render_vmagent_config(collector_id="collector-local")` 的只读检查：生成 `platform_grafana` path `/grafana/metrics` 与 target `grafana:3000`。
- Compose/YAML/compiler 定向静态检查：通过；验证 cAdvisor Docker Root Dir bind mount 为只读、禁止创建缺失源目录，静态与编译 scrape 配置都生成 `/grafana/metrics`。
- `git diff --check`（本轮跟踪文件）：通过。
- 两个 pytest 文件的定向运行受 backend 测试全局 PostgreSQL session fixture 阻塞，当前工作区无法连测试 PostgreSQL；已停止等待进程，不记为通过。
- 目标机已通过用户提供的输出验证 `/grafana/metrics` 返回 HTTP 200、Socket Proxy 列出 11 个容器；没有在目标机直接修改配置或容器。需先部署新的 runtime scrape 配置及 Compose mount，再验证 Grafana UP 和容器指标进入 VictoriaMetrics。

## 目标主机下一步只读检查

```bash
docker exec nexora-vmagent wget -S -O /dev/null http://grafana:3000/grafana/metrics 2>&1 | head -30
docker info --format '{{.DockerRootDir}}'
docker compose up -d --force-recreate cadvisor
docker logs --tail=100 nexora-cadvisor
docker exec nexora-vmagent wget -qO- http://victoriametrics:8428/api/v1/query?query=container_last_seen
```

部署 runtime scrape 更新后，第一条应直接返回 Grafana metrics，而不再跳转到外部 HTTPS。按 `docker info` 输出设置 `.env` 中的 `CADVISOR_DOCKER_ROOT_DIR`（默认路径无需设置），再重建 cAdvisor。VictoriaMetrics 查询应出现带容器身份标签的 `container_last_seen` 序列。未改变 Socket Proxy 权限，也未启用 privileged。
