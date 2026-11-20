# Grafana 监控大盘扩展与 Docker 验收记录

## 完成摘要

- 按计划顺序完成本地落地：复核旧 Dashboard Docker 验收状态，增加平台健康指标链路，增加出口拨测质量 dashboard，增加告警处置与通知效果 dashboard。
- 新增 Grafana 大盘 10「监控平台健康」、11「互联网拨测质量」、12「告警运营与通知有效性」，并在 Nexora 大盘切换器添加入口。
- 保留工作区原有告警、通知、接口状态和样式等未提交更改；未清理构建目录，未提交、推送或部署。

## 实际修改文件

- `backend/api/grafana_metrics.py`：新增内部 Prometheus 文本指标导出。导出数据库连通、出口拨测、告警生命周期、通知投递和 outbox 的聚合指标；不导出租户、设备、目标、地址、告警正文、收件人标签。
- `backend/main.py`：注册内部 `/metrics` 路由。容器内 API 端口仅 `expose`，Nginx 的 `/` 路径提供 SPA，不把此端点反向代理到公网。
- `backend/services/monitoring_compiler.py`、`monitoring/vmagent/scrape.yml`：新增 5 个平台应用/监控服务 job 和 1 个 cAdvisor job。运行时编译仅对 `collector-local` 注入 Docker 服务名；远程 collector 不包含这些地址。出口质量查询复用带时间索引的探测结果和汇总样本。
- `backend/services/outbound_probe_service.py`、`backend/database/migrations/m0258_outbound_probe_icmp_quality.py`：ICMP 发送有界的 5 次 echo，持久化解析出的 RTT、丢包率和相邻回包时延变化估计；新增 PostgreSQL 幂等加列迁移。
- `docker-compose.yml`：添加仅连接内部采集网络的 Docker API GET 代理和 cAdvisor；没有发布宿主端口，cAdvisor 只挂载只读 `/sys`，不挂载宿主根目录。其资源指标仍需目标 Docker 运行时验证。
- `backend/tests/monitoring/test_grafana_metrics_export.py`、`backend/tests/monitoring/test_outbound_probe_icmp_quality.py`、`backend/tests/database/test_m0258_outbound_probe_icmp_quality.py`、`backend/tests/monitoring/test_monitoring_v1_compiler.py`：覆盖真实 PostgreSQL 聚合查询、无标识标签/数据源缺失语义、ICMP 解析和有界探测、迁移幂等性及平台 scrape 目标只属于本地 collector。
- `monitoring/grafana/generate_dashboards.py` 与 `monitoring/grafana/dashboards/`：新增 10–12 三份 JSON。所有 12 份当前 JSON 与生成器输出一致。
- `src/pages/GrafanaDashboardPage.tsx`：新增三个 dashboard 选择入口，保留此前移除纯净大盘/电视模式/完整管理按钮的修改。
- 本计划、此 walkthrough 与 `handoff.md` 增补了本次实施和验证记录。

## 关键实现说明

- 平台健康大盘跟踪 API、VictoriaMetrics、vmagent、SNMP exporter、Grafana 和 cAdvisor 的本地采集目标；API 的 `SELECT 1` 单独表示数据库连通性。面板还覆盖 vmagent remote-write 积压/推送失败、VictoriaMetrics 磁盘空间，以及容器 CPU、内存工作集和文件 I/O。未接入 PostgreSQL/SeaweedFS exporter；cAdvisor 面板未在目标 Docker 运行时验证。
- WAN 大盘分别显示接口侧健康/采集/流量/错误丢弃，与系统全局 DNS/TCP/HTTP/ICMP 探测质量。ICMP 多 echo 记录真实回包 RTT、丢包和相邻回包时延变化估计；探测样本聚合不暴露设备/目标标签。现有探测器没有执行 `wan_probe_bindings` 的线路选路，故该大盘不是逐线路 SLA；只配置 source IP 也显示“未验证”，不冒称线路绑定已生效。
- 告警大盘显示当前未恢复时长、时长 P95、24 小时 MTTA/MTTR 均值和 P95、同一 dedupe key 的重复未恢复事件、通知成功/失败率及重试。通知成功率按 `succeeded / (succeeded + failed)` 计算，排除 queued/sending/retrying/skipped；全局聚合不提供租户或告警明细下钻。
- 新指标首次部署后才会进入 VictoriaMetrics；旧历史 PostgreSQL 样本不会自动回填成 VictoriaMetrics 历史曲线。

## 验证命令与结果

- 在 `backend/` 目录执行 `../.venv/Scripts/python.exe -m pytest tests/monitoring/test_monitoring_v1_compiler.py tests/monitoring/test_grafana_metrics_export.py tests/monitoring/test_outbound_probe_icmp_quality.py tests/monitoring/test_wan_p0_p2_contract.py tests/database/test_m0258_outbound_probe_icmp_quality.py -q`：44 passed（255.64 秒）。其后为显式新增的 MTTA/MTTR P95 exporter 断言单独复跑 `test_metrics_export_contains_only_aggregate_allowlisted_labels`：1 passed（52.24 秒）。
- `npm run lint`：`tsc --noEmit` 退出码 0。独立输出目录执行 Vite production build：4,296 modules transformed，构建成功；没有覆盖仓库内已有 dist 目录。
- `.venv/Scripts/python.exe monitoring/grafana/generate_dashboards.py`：成功生成 12 份 Dashboard JSON。
- Dashboard 静态校验：12/12 文件与 builder 输出逐项一致；panel ID 无重复，横向网格不越界；Prometheus datasource UID 为 `victoriametrics`；10–12 的自定义指标引用均能在 exporter 契约中找到。
- vmagent/Compose 静态校验通过：local compiler 生成新增平台 job，remote collector 不含控制面 Docker 服务目标；Docker API 代理无宿主端口且禁用 POST，cAdvisor 只在内部网络和只读 `/sys` 挂载。
- PostgreSQL-only 扫描：0 violations。涉及 Python 的改动和测试 `py_compile` 通过。`git diff --check` 退出码 0，仅有已有文件 LF→CRLF 提醒。

## 未执行验证与剩余风险

- 浏览器只读检查已重开并保留 `https://192.168.204.128/monitor/dashboards`：部署页为 `v1.0.9`，选择器仅有 01–08，仍显示本地已删除的“纯净大盘 / 电视模式 / 完整管理”按钮。逐项打开部署版 01–08 后均加载到对应 Grafana dashboard；04 有实时流量值，但没有当前源码中的“接口管理与运行状态”面板。页面当前保留在 04。新增 10–12 不存在于该实例，之前直达新 UID 返回 `Dashboard not found`。
- 本工作环境没有 Docker CLI、Docker Desktop CLI 路径或可用 WSL 发行版（`wsl.exe --status` 返回 `Wsl/Service/CreateInstance/0xd0000022`），没有重建/重启用户部署。部署版新增 dashboard、新指标 scrape 后的 PromQL 和 cAdvisor 资源采集仍未运行时验收；本地静态/单元/PG 测试不能替代 Docker 验收。
- 重要测试环境行为：项目 pytest 的 session fixture 会先对 `DATABASE_URL` 指向的本地 PostgreSQL source DB 执行 `database.init_db()`，再创建隔离测试库。运行期间 source DB 的日志显示原先 pending migrations 0257–0259 已依次应用；0257/0259 是工作区已有的告警租户/通知迁移，除 0258 的加列外也可能改变 source DB 告警配置数据。本轮没有回滚这些 schema/data migration，未触碰远端 Docker 实例。
- 新的告警和出口指标是系统全局汇总，Grafana Viewer 可能看到全局计数，但不能按租户、设备或目标下钻。既有 Grafana datasource 多租户隔离问题是上一轮审查发现的，本次未改变其权限模型。
- 真正按物理 WAN 链路统计 SLA，需要后续实现并验证 binding/source-IP 感知的路由探测。容器 CPU/内存/磁盘 I/O 也需要在目标 Docker 主机验证 cAdvisor 的受限挂载是否提供完整数据。
- 如新面板运行后指标无数据，需检查 Docker 控制面生成的 named-volume `vmagent/scrape.yml` 是否已更新、API `/metrics` 是否可从 vmagent 网络访问，以及新样本是否已完成至少一次 scrape；仓库静态文件不会直接改变已运行容器。

## 用户指定的验收边界

- 用户要求新改代码本轮只做本地逻辑验证，待用户更新 Docker 部署后再验证运行时。本轮没有把更新前部署页作为新代码验收，也不继续访问部署环境验证这些改动。
- 之前浏览器看到的 `v1.0.9` 只作为更新前基线：它没有 10–12 新大盘，也没有本地新增的接口状态面板；这些旧版页面现象不能说明新代码运行结果。
- 后续待用户更新后再检查大盘选择入口、Grafana 页面渲染、PromQL 新指标以及 cAdvisor 实际资源采集。
