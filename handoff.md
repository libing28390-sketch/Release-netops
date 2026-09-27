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

## 2026-09-26 Grafana 九个看板重复核查与接口流量修复

- 逐一检查全部 9 个实时看板，并对无数据项和关键查询重复执行只读 Explore 验证。详细记录在 docs/plans/plan_20260926_1105_01_Grafana接口流量与状态排查.md 与对应 walkthrough。
- 设备下拉旧名称的原因已确认：当前 live 变量仍通过历史 ifOperStatus|up 时序的 label_values 拉取 hostname。重开 04 展开后仍有 23 个选项，包括 F1090-10、R10/R11/R12/R13/R14。新生成的变量用当前 up 目标分组查询，重复验证得到 13 个当前 SNMP 目标且不含这些旧名。Grafana 未 reload 本地生成物，本次没有更改运行实例。
- 04 实时流量卡和趋势仍显示数据暂不可用；面板 422 细节确认 SW6/Gi0/3/TO-R4 的 group_left 右侧同一 ifName 序列因 interface_role/利用率阈值标签有无形成重复。生成源已聚合 join 元数据；修正查询在 Explore 返回流量样本。
- 01 状态条件改成管理启用且运行状态明确 DOWN，并解释统计的是当前状态；接口角色显示“接口用途”，unclassified 显示“用途待确认”。03 无线面板缺指标时不再回退为 0。
- 采集端当前无网络设备 CPU、内存、温度和无线指标样本。05 失败数为 0 与在线状态一致；06 选择有效的 R1/Et0/0 后各流量面板有数据；02、08 与 09 的其余主要数据按计划显示。
- D07 与 D09 表格首次观察只见表头；重复打开后 D07 显示 3 个挂载点，D09 显示 R1/Et0/0 带宽 10 Mb/s，未复现持续缺数。首次未呈现的瞬时原因不能从只读页面确认。
- 改动：monitoring/grafana/generate_dashboards.py、9 份 monitoring/grafana/dashboards/nexora-*.json、backend/tests/monitoring/test_domestic_and_wireless_monitoring.py，以及本次 plan/walkthrough。
- 验证：聚焦 pytest 6 passed；Python 编译与 dashboard generator 通过；git diff --check 通过。没有保存、reload、部署或发布 live Grafana。
- 下步：待 Grafana 实例采用本次生成 JSON 后，再在 live 04 重验变量选项与流量面板，并确认新中文标签及 01 状态说明生效。

## 2026-09-26 设备与接口看板参考样式及光模块支持核查

- 02 设备详情把 CPU/内存当前值改为所选设备各实体中的最高值 Gauge；最高温度卡取消跨设备通用温度阈值。04 接口看板新增过去 5 分钟平均入向/出向速率 Top10 Bar gauge，原利用率表与质量/状态面板保留并重排。
- 光模块：LibreNMS 的当前 Comware 发现配置未定义 H3C Rx/Tx 功率传感器，`mibs/h3c/HH3C-TRANSCEIVER-INFO-MIB` 路径未找到。H3C 厂商文档存在对应 MIB/OID，但用户要求以 LibreNMS 支持为准，因此没有添加 SNMP exporter 指标、CLI 采集或 Grafana 面板。
- 验证：生成器和 Python 编译通过；9 份 dashboard JSON 结构/ID/网格/datasource 校验通过；02 Gauge 与 04 Top10 查询契约验证通过；`git diff --check` 通过（保留既有 handoff 行尾警告）。
- Live Grafana 只读仍显示旧 01 总览：硬件平均图无数据，稳定 Down 计数仍是 216；本地生成文件尚未 reload/deploy。本次未写入 Grafana，也未操作设备。
- 当前修改文件包括 `monitoring/grafana/generate_dashboards.py`、设备和接口 dashboard JSON，以及 plan/walkthrough：`docs/plans/plan_20260926_1315_01_设备与接口看板参考样式.md`、`docs/walkthrough/walkthrough_20260926_1315_01_设备与接口看板参考样式.md`。

## 2026-09-27 Grafana 九个看板深度复核

- 范围：只读核对 9 份 provisioned Grafana JSON、生成器、SNMP OID/采集器契约、Grafana 访问链及相关监控数据表；本轮未改 dashboard 或业务代码。
- 静态健康：9/9 JSON 均与生成器内存输出相等，panel ID/变量名无重复；SNMP catalog 与 Linux/Windows exporter 指标引用未发现拼写缺项。当前 admin/oper 状态表的 1=绿色 Up、2=红色 down 背景填充符合预期。
- 高风险待处理：SNMP/服务器目标携带 `tenant_id`，但 9 个 dashboard 查询均无 tenant selector；Grafana session/auth proxy 对 Viewer 开放且共用 VictoriaMetrics datasource。多租户下存在跨租户指标可见性风险。单纯加入可编辑 dashboard 变量不能形成安全隔离；需要 datasource/proxy 级租户约束，或先限制到全局受信角色。
- 其他复核发现：Linux/Windows 多处按 hostname 聚合并丢弃 site_name；健康/主机资源摘要用 `or vector(0)` 混淆无数据与真实零；ifOperStatus 的 testing/dormant/notPresent/lowerLayerDown 被映射为 UNKNOWN；Outbound 固定阈值与 CMDB profile 阈值可能冲突；Windows“关键服务”查询目前覆盖全部服务。`filtered_interface_join` 的多重名称/描述冲突及无线在线 AP 大于总量导致负离线数仍缺真实数据验证。表格 unit override 的 rename 后匹配也需 Grafana 12.1 页面确认。
- 验证：`.venv` 下 dashboard/无线测试 6 passed，编译/部署契约测试 6 passed；Agent 运行网络 dashboard + compiler 聚焦测试 28 passed；9/9 generator sync、SNMP metric selector 静态匹配及 `git diff --check` 通过。
- 未验证：本机没有可用 Docker/promtool，localhost VictoriaMetrics/Grafana 不可访问；未执行实时 PromQL、Grafana 页面渲染、真实设备采集。
- 后续建议：优先定义并实施 Grafana 租户隔离；新看板优先考虑设备风扇/电源/部件健康（现有 OID 有数据但厂商覆盖有限），以及 WAN 链路 SLA/容量（现有 PostgreSQL 样本、coverage、P95 基线和事件可用，但当前 Grafana 只有 VictoriaMetrics datasource）。
- 05“SNMP 在线目标”此前发现过把 `up=0` 失败目标计为在线的缺陷；当前生成器和生成 JSON 已使用 `up == 1` 后再计数，失败目标卡片使用 `up == 0`，静态查询语义已修正，仍需随部署版本在 Grafana 页面验证。

## 2026-09-27 新增 10–12 监控大盘与运行时验收

- 新增 `GET /metrics` 内部聚合导出，供 collector-local 抓取 API/数据库连接、出口拨测、告警生命周期、通知投递和 outbox 指标；不导出租户、设备、目标、地址、告警正文或收件人标签。WAN 查询复用有时间索引的每轮汇总样本，导出语义限于系统级出口拨测质量。
- vmagent 运行时编译器仅对 `collector-local` 添加 API、VictoriaMetrics、vmagent、SNMP exporter 和 Grafana scrape jobs；静态样例与编译产物一致，远端 collector 不包含这些服务 DNS。
- 新增 10 监控平台健康、11 互联网拨测质量、12 告警运营与通知有效性三个 Grafana dashboard，并在 Nexora dashboard 选择器新增入口。探测耗时不代表 ICMP RTT；本轮没有实现线路绑定 SLA、真实丢包或抖动。
- Agent 分工：metrics router 与 dashboard builders 分别独立实现；coordinator 完成 `main.py`/运行时 compiler 接入、验证、生成与审查。
- 验证：后端编译、vmagent 静态/运行时配置对比、12 份 dashboard JSON 与生成器同步/唯一 panel ID/VictoriaMetrics UID 检查、26 个聚焦 pytest 和 `npm run lint` 均通过；`git diff --check` 仅保留既有 CRLF 转换提醒。
- 运行时：已用浏览器复验并保留 `https://192.168.204.128/monitor/dashboards`。当前部署显示 `v1.0.9`、只有 01–08，仍有本地已删除的三个显示模式按钮；旧 04 流量图有实时值，但没有“接口管理与运行状态”面板。直达 `nexora-platform-health` 返回 `Dashboard not found`。Windows 环境没有 Docker CLI，WSL 无可用发行版，未执行容器重建/重启；新增看板等待目标部署更新后再做在线 smoke test。
- 后续边界：当前三个新看板只读聚合指标，无用户/租户下钻；真实链路 SLA 仍需按 WAN binding/source route 的探测采样。此前发现的既有 Grafana 多租户 datasource 隔离问题未纳入本次修改。

## 2026-09-27 本地逻辑验收边界补充

- 用户明确要求：新改代码目前只验证本地逻辑；等用户更新部署后再验证运行时。本轮不再对 Docker/部署页做新代码验收。
- 本地证据：聚焦 PostgreSQL 后端测试 44 passed，新增 P95 指标断言单测 1 passed；TypeScript lint 与独立目录 production build 成功；12/12 dashboard JSON 与生成器一致；Compose/vmagent 静态核对、PostgreSQL-only 扫描（0 violations）及 `git diff --check` 通过。
- 浏览器此前看到的部署是更新前 `v1.0.9`，仅作为基线；它没有新大盘或新接口状态面板，不能作为新代码运行时通过/失败的证据。待用户更新后再对部署版做 smoke check。
- pytest session fixture 在本地 source PostgreSQL 上应用了待执行的 migrations 0257–0259；其中 0257/0259 是工作区既有的告警租户/通知变更，可能已调整 source DB 告警规则或通知配置数据。本轮没有回滚。

## 2026-09-27 监控平台全量容器指标排查

- 大盘六行是六个 `platform_*` scrape 端点，不是 Docker 容器总数。已将 cAdvisor CPU/内存/磁盘指标查询改为按全部非空容器名聚合，并新增 `container_last_seen` 容器观测数/清单；观测不等价于容器健康状态。
- 用户现场输出确认 vmagent 访问 `grafana:3000/metrics` 被转发到 `192.168.31.253:10808` 后返回 502；Compose 现清空 vmagent/cAdvisor 代理变量并设置内网 `NO_PROXY`。cAdvisor 重启的高概率原因是 `--disable_metrics` 带有 v0.60.6 不支持的 `accelerator` 值，已移除，仍需部署后验证。
- VictoriaMetrics 固定 v1.103.0；`vm_total_disk_space_bytes` 从 v1.124.0 才引入，存储面板改为已用数据量 `sum(vm_data_size_bytes)`，不再显示虚假的空间占用率。
- 聚焦部署契约测试 7 passed；12 份 dashboard JSON 解析和目标生成同步检查通过；`git diff --check` 通过。监控目录全套测试运行约 38% 后中止，不计为通过。
- 未更新或重启目标机容器，也未在线写入 Grafana。部署后应验证 Grafana/cAdvisor scrape 状态、cAdvisor 容器资源时序和动态清单数量；详情见 `docs/plans/plan_20260927_2013_01_监控平台容器指标全量采集.md` 与对应 walkthrough。
