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

## 2026-09-25 Grafana Dashboard 方案 A

- 状态：本地实现与静态核对已完成。方案细节见 `docs/plans/plan_20260925_2323_01_Grafana方案A视觉优化.md` 和 `docs/walkthrough/walkthrough_20260925_2323_01_Grafana方案A视觉优化.md`。
- 生成器更新并生成 9 份 JSON，包括新增接口详情页 `nexora-interface-detail.json`。接口状态码 `1/2` 显示绿色 `Up` / 红色 `down`，`0`、`3–7`、空值和 NaN 显示灰色 `UNKNOWN`。
- CMDB interface role/阈值契约、Monitor V1 metric relabel、IF-MIB 高容量包计数器和 `ifLastChange` 采集已接入；详情页按接口 profile 阈值计算动态状态。
- CMDB 接口列表/更新使用 asset tenant/site scope；没有持久化 skeleton 主键的 IP 库合成行不可编辑。详情页 `ifAlias` join 使用不含接口过滤标签的设备 selector。
- 验证：Python 编译、生成器运行、9 份 JSON 结构与面板网格检查、SNMP YAML/metric relabel 静态检查、`git diff --check` 均通过。当时未运行测试套件；本次合并复核补跑迁移和快照隔离的隔离 PostgreSQL 用例（2 passed）。未应用数据库迁移、未部署 Grafana 或连接真实设备。
- 遗留验收：Grafana 12.1.0 页面实际渲染、部署后 PromQL 结果、CMDB 迁移及 vmagent runtime 行为尚未验证。04 多接口 Gauge 使用平台默认阈值；单接口详情状态使用 CMDB 配置阈值。Last Change 年龄需要同设备 `sysUpTime`，默认基线包括 system 模块。

## 2026-09-26 S3 存储排查与配置说明

- 已审查对象存储配置/连接测试、默认存储解析、config 快照及 PAM 录像的上传、读取、重试和删除路径。
- 修复 S3 `NoSuchBucket` 被误归类为对象缺失的问题；对象下载/元数据查询现在将缺 Bucket 作为存储错误，并在 S3 操作错误中保留安全的错误码和 HTTP 状态摘要。
- 配置快照对象读取失败现在写入安全诊断日志；查看/下载 API 对确实缺失的对象返回 404，对存储不可用返回 503，不再静默返回空内容。
- 前端用途说明标明默认 Bucket 的 `config/` 与 `pam/` 前缀、知识库尚未接入、Bucket 需预先创建；固定 S3 类型改为静态文本，Endpoint 增加 S3 API 地址提示。
- 验证：存储模块独立测试 15 passed；修改的 Python 文件编译通过；`npm run lint` 和 `git diff --check` 通过。常规 pytest 全局初始化受工作区待迁移版本 253 阻挡；未对真实 SeaweedFS 做上传/读取验证。
- 只读复核 `docker-compose.yml` 确认 netops 的 `NO_PROXY`/`no_proxy` 已包含 SeaweedFS 服务别名；endpoint 路径仍开放以兼容路径前缀反代，前端提示不应把 Bucket 和业务目录作为 URL 路径。
- 上述 S3 修改当时未提交或推送；已纳入 2026-09-26 当前 `main` 工作区的统一复核、提交和推送。

## 2026-09-26 当前工作区统一复核

- m0253 原先会覆盖非空内置 IF-MIB 配置；现改为对空配置完整 seed、对非空配置只追加缺失的 `ifLastChange`，保留已有 OID/metrics 并重算 JSON hash。新增隔离 PostgreSQL 回归覆盖运维编辑保留、hash 更新和幂等。
- `ifLastChange` 是只读 SNMP GET 采集目录项；没有执行 SNMP SET 或修改真实设备配置。
- 配置快照内容/下载加入 asset tenant/site scope，越权访问返回与不存在 ID 相同的 404；新隔离 PostgreSQL 用例验证跨租户拒绝。
- Grafana PPS 图现显示入向、出向、单播、组播、广播 5 类曲线。PPS 使用已有 Counter64 `ifHC*Pkts` 指标；设备不暴露该指标族时显示无数据。
- 验证：隔离 PostgreSQL 用例 2 passed；存储服务聚焦用例 15 passed；Python 编译、Grafana 生成与 JSON 静态检查、SNMP YAML 解析、`npm run lint`、PostgreSQL-only 扫描、`git diff --check` 均通过。隔离 PG 服务在本次运行前有 13 个既存 `nexora_pytest_*` 测试库；本次运行新增残留为 0，既存库未触碰。
- 未应用数据库迁移，未做 Grafana 在线渲染/PromQL、真实设备采集或真实 S3 上传下载。PPS 缺少 Counter64 计数器时无数据。
- 当前 `main` 改动已完成最终暂存审查，并按用户授权统一提交、推送至 `origin/main`。
