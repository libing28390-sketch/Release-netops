# Grafana 监控大盘扩展与 Docker 验收计划

## 任务目标

按用户确认的顺序完成：既有 Grafana 修改的 Docker 验收准备；新增监控平台自身健康、WAN 链路 SLA、告警处置与通知效果大盘；对全部大盘做静态和浏览器检查，并记录尚未接入的数据源。

## 现状与问题

- 仓库已有 01–09 共 9 份 Grafana dashboard JSON；生成器位于 `monitoring/grafana/generate_dashboards.py`，默认数据源为 VictoriaMetrics。
- 本地已有接口状态/颜色、Grafana 页面入口及 SNMP 在线数修改，尚未进入用户提供的 Docker 部署环境；浏览器看到的部署仍显示旧入口按钮及旧接口大盘。
- `monitoring/vmagent/scrape.yml` 当前包含网络 SNMP、Linux、Windows 目标；需要确认控制面运行时配置的生成路径，避免只改静态模板而不影响部署。
- 需要检查 WAN 探测、告警事件和通知 outbox 的现有历史数据是否足以支撑新大盘；禁止把缺失数据展示为健康零值。
- 工作区包含多个无关且未提交的后端告警、通知和文档改动，本任务必须保留，不做清理、覆盖或提交。
- Docker CLI 当前未安装/不可从本工作环境调用，因此仓库修改可以完成静态验收，但不能重建或验证目标容器。

## 影响范围

- Grafana dashboard 生成器、VictoriaMetrics/vmagent 采集配置、内部聚合指标路由和新增 dashboard JSON。
- 扩展 ICMP 样本质量字段与幂等数据库迁移；告警与 WAN 数据保持全局聚合，不在 Prometheus 标签中输出租户、设备、目标、告警内容或收件人标识。
- Docker Compose 增加仅在内网采集网工作的 cAdvisor 和 Docker API 白名单代理；代理只开放 cAdvisor 必需的只读 API，cAdvisor 不发布宿主端口且只只读挂载宿主 `/sys`，不挂载宿主根目录。
- 运行时 vmagent 配置生成器仅对 `collector-local` 注入本地 Compose 服务抓取目标；远程采集器不得收到控制面 Docker DNS 目标。
- Compose/迁移变化仅做本地验收准备；远端部署、容器重建和迁移实际应用遵循授权要求。

## 拟修改文件

- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/` 下按需新增的 dashboard JSON
- `monitoring/vmagent/scrape.yml`、`docker-compose.yml` 及 `backend/services/monitoring_compiler.py`
- `backend/api/grafana_metrics.py`、`backend/main.py`、`backend/services/outbound_probe_service.py`
- `backend/database/migrations/m0258_outbound_probe_icmp_quality.py` 及 exporter/迁移/拨测窄测试
- `src/pages/GrafanaDashboardPage.tsx` 新大盘切换入口及对应窄范围测试
- 对应 `docs/walkthrough/` 验收记录

## 实施步骤

1. 审阅项目规则、现有改动差异、Grafana 生成器输出范围及 Docker/vmagent 真实配置路径；盘点可用的健康、WAN 探测、告警和通知历史指标。
2. 核对并保留已完成的本地修改；先验证静态配置和生成物。浏览器只读检查已部署版本；容器重建或部署前确认操作边界。
3. 增加内网 Docker API 只读代理与 cAdvisor Compose 服务，运行时 vmagent 仅在 `collector-local` 抓取；补 remote-write 积压/丢弃/推送失败、VictoriaMetrics 存储空间和容器 CPU/内存/磁盘 I/O 面板。
4. 将 ICMP 由单回显改为有界多回显并保存 RTT、包丢失和包间时延变化；在 exporter 中按固定协议枚举聚合 DNS/TCP/HTTP/ICMP 成功率、超时和延迟。用 WAN 接口样本计算接口侧可用率、采集失败、流量、错误和丢弃。
5. 告警 exporter 增加当前未恢复时长、24h MTTA/MTTR、并发重复 dedupe-key 事件、24h 通知成功/失败和重试数据。
6. 运行生成器前再次核对其会覆盖的完整文件清单；生成并审查全部 JSON 差异，重点检查查询标签、变量、单位、无数据语义、panel ID 和数据源 UID。
7. 运行与本任务相符的 Python/JSON、迁移、ICMP、后端窄测试、Compose/vmagent 配置检查及 `git diff --check`；随后在浏览器检查大盘渲染。当前探针未执行 `wan_probe_bindings` 线路选路，因此真实逐线路 SLA 仍需标为未覆盖，不把全局出口探测冒称单线路 SLA。
8. 输出与本计划同后缀的 walkthrough，列明工作区实现、Docker 运行时版本差异、验证证据和剩余风险。

## 验证计划

- Python 生成器可编译；生成后的 01–09 与新增 dashboard JSON 可解析，panel ID 唯一，数据源 UID 为 `victoriametrics`。
- 只读确认 vmagent 运行时配置的来源、服务健康端点及 metrics endpoint；验证本地采集器含新增平台 jobs，而远程采集器不含控制面目标。
- 对修改的后端行为运行窄范围测试；对 dashboard 配置生成执行回归一致性核对。
- 迁移对已存在 `outbound_probe_results` 幂等加列，并覆盖 fresh schema、迁移重复执行与既有 schema 升级路径。
- Compose YAML 可解析；Docker API 代理无宿主端口映射并只启用白名单 GET API；cAdvisor 只在内网采集网且远程 collector 不包含该目标。
- 根据当前 Docker 版本做浏览器 smoke check；没有执行容器重建时，清楚标明运行时验收未完成，不把本地构建当作已部署。
- 检查本任务文件差异与用户原有变更，避免清理生成目录、运行 `git clean`/`reset`、提交或推送。

## 风险与回滚

- vmagent 实际读取控制面生成的 named-volume 配置；只修改仓库模板可能不会影响现有 Docker。修改前确认运行时输出及 reload 路径。
- Prometheus 标签可能包含 `tenant_id` 等租户标识；没有可靠授权过滤时不新增可跨租户下钻的原始明细面板。
- 主动探测必须经过现有 SSRF/出口访问控制和有界并发，避免将任意目标探测暴露成可被滥用的功能。
- Grafana dashboard 由文件 provisioning 管理；如新 JSON 有问题，回滚对应生成器、配置与新增 JSON 文件，再让 Grafana 重新加载文件。不得直接修改线上 Grafana 作为唯一修复。
- 不直接改动用户 Docker 服务、不清理任何已有构建产物；需要重建或部署时以明确操作范围为准。

## 本轮执行更新

- 浏览器复验目标部署为 `v1.0.9`，只显示大盘 01–08，仍有已在本地源码移除的三个显示模式按钮；旧版 04 可加载流量数据，但访问新 UID `nexora-platform-health` 返回 `Dashboard not found`。工作环境无 Docker CLI，WSL 也无法启动发行版，因此未能重建/重启目标容器或验收新增大盘运行时渲染。
- 新建内部 `/metrics` 聚合出口：仅从应用私有网络抓取；全局统计无租户、设备、目标、地址、告警正文或收件人维度；出向质量使用带时间索引的每轮聚合表，避免按设备/目标暴露明细。
- 平台健康增加 API、VictoriaMetrics、vmagent、SNMP exporter、Grafana 的本地 vmagent scrape jobs，以及由应用 `SELECT 1` 采集的数据库连通 gauge。collector-local 才生成这些目标。
- WAN dashboard 已区分接口侧状态/采集/流量/错误丢弃与全局多协议拨测。ICMP 使用 5 次有界 echo，保存 RTT、包丢失率和相邻回包时延变化估计；拨测仍不等于 binding/source-IP 路由的逐线路 SLA，因此只有线路级探测实际执行后才能报告该 SLA。
- 告警 dashboard 已加当前未恢复持续时长/P95、24h MTTA/MTTR 均值/P95、重复未恢复事件、通知终态成功/失败率与重试数；全局聚合没有租户或明细标签。
- 平台健康增加 API/DB 连通、VictoriaMetrics、vmagent、SNMP exporter、Grafana、cAdvisor 指标；Compose 中 cAdvisor 通过内部 Docker API 只读代理读取资源，目标 Docker 主机还未验证其挂载能否完整采集 CPU/内存/I/O。
- 新大盘已加入本地 Grafana 页面选择器，序号为 10–12。所有 12 份 JSON 与生成器一致；后端测试、TypeScript、production build、Compose/vmagent 静态校验与 PostgreSQL-only 扫描结果见配套 walkthrough。

## 最终执行状态（2026-09-27）

- 本地实现、静态核查及后端窄范围验收完成；完整测试组 44 passed，新增 P95 指标断言单测 1 passed。前端 lint 和独立目录 production build 成功，PostgreSQL-only policy 为 0 violations。
- 浏览器逐项检查部署版 01–08 均能加载，当前 `v1.0.9`，大盘 10–12 未部署；大盘 04 还没有本地新增的接口状态面板，旧三种显示模式按钮仍可见。浏览器留在用户指定的部署页和 04 大盘。
- Docker CLI/WSL 运行时不可用，未操作用户容器；部署版新大盘、PromQL 数据和 cAdvisor 运行时表现仍需 Docker 验收后才能确认。
- pytest 项目 fixture 会在创建隔离 PG 模板前先对本地 `DATABASE_URL` source DB 调用 `database.init_db()`。本次测试过程中已有的 migrations 0257–0259 被应用；0257/0259 属于当前工作区既有告警租户与通知配置变更，可能改动 source DB 告警规则/通知配置数据。此行为记录于 walkthrough；本轮未尝试回滚。

## 用户指定的验收边界补充

- 用户明确要求目前仅验证新代码的本地逻辑；等用户更新部署后再验证运行时。因此不把更新前浏览器看到的 `v1.0.9` 当成新代码的验收结果，也不在用户更新前继续测试部署页或 Docker。
- 本地逻辑/构建证据已完成并记入 walkthrough；部署后的页面渲染、PromQL 数据和 cAdvisor 运行表现待用户更新后再检查。
