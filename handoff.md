# Nexora Monitoring V1 P0 交接记录

- 日期：2026-09-16
- 范围：`Nexora_Monitoring_V1_详细架构与落地实施方案.md` 的 P0-T01～P0-T20
- 状态：`REPOSITORY IMPLEMENTATION COMPLETE / RUNTIME POC PENDING`
- 分支：`main`

## 已交付

### Backend / Control Plane

- `backend/database/migrations/m0232_monitoring_v1_control_plane.py`：Collector、SNMP Module、Module Variant、Monitoring Plan、Assignment、MetricDefinition、Config Version、Target Snapshot、Shadow Compare，以及 SNMPv3 加密字段。
- `backend/services/monitoring_compiler.py`：CMDB/Collection Plan → Assignment → Target Snapshot → vmagent/snmp_exporter Artifact；包含 interval、timeout、冲突、duplicate-walk、Auth Alias、Manifest/checksum/YAML 校验。
- `backend/services/metric_provider.py`：Native、Shadow、VictoriaMetrics Provider、Canonical Metrics、Counter Wrap 和 Shadow Compare。
- `backend/services/collector_artifact_service.py`：Current/Previous、Last Known Good、原子发布和回滚。
- `backend/services/monitoring_health_service.py`：Collection Health 和错误分类。
- `backend/api/monitoring_v1.py`：Module/Variant、Plan、Collector、Assignment、Artifact、Metrics、Collection Health、Shadow Compare API，含 RBAC、租户隔离和审计。
- 现有 Collection Plan 已支持 `devices.collection_policy_json.monitoring` 扩展。

### Frontend

- `/monitor/collection-plans`：Plan 创建、JSON 配置、编译测试。
- `/monitor/modules`：Module/Variant 创建、测试、发布、校验。
- `/monitor/collectors`：Collector 创建、测试、编译、校验、发布、回滚。
- `/monitor/collection-health`：Assignment 健康率、状态和错误明细。
- 新增入口图标：采集计划 `Layers3`、模块目录 `Boxes`、采集器管理 `CloudCog`、采集健康 `Gauge`。
- Network Monitoring 支持 Native / Shadow / VictoriaMetrics 切换。

### Docker Compose

已加入固定版本服务：

```text
victoriametrics/victoria-metrics:v1.103.0
victoriametrics/vmagent:v1.103.0
prom/snmp-exporter:v0.26.0
```

已配置 VM 持久化、vmagent disk queue、Remote Write、健康检查、Generic IF-MIB/System Module 和 `/etc/nexora-collector` Target Snapshot 路径。

## 验证证据

```text
pytest -q backend/tests -k "monitor or snmp or alert or probe" 162 passed
pytest -q backend/tests/vendor_audit/test_collection_plan_service.py backend/tests/vendor_audit/test_collection_plan_bulk_api.py 46 passed
pytest -q backend/tests/database/test_m0232_monitoring_v1.py 1 passed
pytest -q backend/tests/monitoring 64 passed
npx vitest run --config vitest.config.ts src/utils/routeContext.test.ts 8 passed
npm run lint PASS
npm run build PASS
python scripts/validate_postgresql_only.py PASS / 0 violations
python scripts/monitoring_poc_preflight.py PASS（静态配置）
```

## 现场验收阻塞

当前工作主机没有 Docker CLI，且没有 H3C/Huawei/Cisco 实验设备，因此尚未执行真实 Docker runtime、设备矩阵、vmagent 断链补传和 300 台压测。强制预检结果为：

```text
python scripts/monitoring_poc_preflight.py --require-runtime
Docker CLI not found (exit 2)
```

## 下一步

1. 在 Docker 验收机执行 `python scripts/monitoring_poc_preflight.py --require-runtime`。
2. 执行 `docker compose up -d`，确认 db、redis、netops、VictoriaMetrics、vmagent、snmp_exporter、nginx 健康。
3. 导入 POC CMDB 设备和 SNMPv2c/v3 Credential Binding，执行 Collector compile → validate → publish。
4. 按方案执行 GATE-01～GATE-18，全部通过后再将 `MONITORING_METRIC_BACKEND` 从 `native` 切换为 `shadow`，最后切到 `victoriametrics`。

## 安全与回滚

- Target Snapshot 只保存 opaque `auth_<hash>`，不保存 community/password。
- Artifact 校验或编译失败不得覆盖 Last Known Good。
- 保留 Native Provider 和旧配置版本，现场失败时回滚到上一版本。
- `.env`、真实凭据和 `.tmp/` 不应提交。

## 2026-09-25 Grafana 会话与接口流量断点排查

- 发布提交 `0a8a96d3e5a14abf289503cc3510b0a54db7b653` 已推送至 `origin/main`；远端 `v1.0.9` 已按用户授权强制更新，annotated tag peeled commit 与该提交一致。标签推送触发 `.github/workflows/release.yml`，工作流结果尚未检查。
- Grafana 重复 `/grafana` 的浏览器根因：普通窗口禁用缓存仍复现，无痕正常，删除浏览器的原生 `grafana_session` 后恢复。Nexora 专用 `nexora_grafana_session` 应保留。仓库改动已调整 Grafana 子路径代理并在 Nginx 上游剥离浏览器 Cookie，同时让内部鉴权子请求单独校验 Nexora 会话；这批 Cookie 隔离改动尚未在服务器部署验证。
- 接口流量图缺样：vmagent 曾报告 R3/R4 `generic_ifmib_interface_std` 采集因 SNMP exporter 请求超时返回 HTTP 500；后续人工探测两台设备都曾返回 HTTP 200，说明故障间歇发生。
- 近 30 分钟 VictoriaMetrics range 查询中，`topk(10, ...)` 与去掉 `topk` 的 PromQL 输出缺样时间完全一致，并同时影响所有接口及入/出方向：R3 两段 90 秒间隔；R4 多段 90–150 秒间隔。原始计数器中也存在同步采集间隔。结论：断点来自 SNMP 目标采集不连续，不是 `topk` 截断；设备响应耗时、SNMP exporter 超时与模块轮询负载仍待进一步定位，尚未修复。
- 后续：本地 Cookie 隔离改动需在服务器部署验证；SNMP 断点需另行检查各轮 scrape 错误时间、exporter 日志及设备响应。此次发布工作流仍在远端异步运行，不能从本地 ref 核验推断 CI/制品发布成功。
