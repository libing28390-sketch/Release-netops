# 当前交接：页面卡顿、Docker 资源配额与 300 台容量验证

> 更新时间：2026-10-07 09:42（Asia/Shanghai）。本节优先于下方早期检查点。此前修复/发布的授权记录仍按其原任务保留；本轮页面卡顿续查的远端范围为只读性能采样与浏览器只读查看，不在生产写库、保存资产、重启或部署。

## 2026-10-07 09:41（Asia/Shanghai）隔离压力测试保护性中止

- 按用户要求再次尝试较长的隔离 API 压力测试，但两次都被宿主机负载保护器停止，未得到完整的两小时容量结果。
- 首次 run `2899675dee4a` 于 01:17:11–01:33:48 UTC 运行。15秒预热和最终检查通过，1 RPS 阶段实际运行约14分钟；主机 `load1` 连续三次超过3（3.75、4.28、5.07）后于01:33:41 UTC停止。此窗口恰逢 Ubuntu `apt-daily`/`unattended-upgrade --download-only` 启动；该进程约占82.8% CPU。测试报告没有完整阶段统计，状态为 `aborted`。
- 更新任务退出后重试 run `82d7e162c7b9`，隔离环境启动/预检期间主机 `load1` 连续三次为4.85、5.34、4.29，于01:40:42 UTC停止；没有进入任何计时压力档。该启动期间合成 DB/Grafana/NetOps 容器的 CPU 峰值分别约62%/55%/71%。
- 两个报告均显示清理完成；按完整 run-id 过滤的测试容器、网络、卷均为空。生产11个容器仍运行、healthcheck 状态正常、无重启/OOM；应用内 `/api/health/live` 返回200（约10ms）。没有对生产数据库、资产或真实设备发写请求。
- 结论边界：保护性中止说明共享两核主机在后台更新或额外隔离栈初始化期间没有足够稳定余量支撑本方案；不构成1/2 RPS阶段通过或失败的容量结论。远端报告保留于 `/tmp/nexora-soak-20261007-0056/two-hour/report/` 和 `/tmp/nexora-soak-20261007-0056/retry-after-update/report/`。不在该主机持续高负载时再次创建整套隔离栈。

## 2026-10-07 08:41（Asia/Shanghai）页面卡顿续查

- 当前最直接的生产慢点是 NetOps `/hardware-metrics`：`platform_hardware_inventory` 每60秒 scrape 一次。采样结束时的最新30分钟30次均为200，中位数1710.5ms、p95 4102.1ms、最大5578.7ms，慢耗时几乎全部位于 handler。同期另有17条成功 API 请求超过1秒，`/api/config-templates` 最大约3.96秒。
- 生产有17台设备、15台绑定 SNMP、5296条活动硬件传感器；传感器表共5322行/约24MiB。该 handler 查询并读取近乎整张活动表，解码 JSONB、逐设备渲染 Prometheus 文本，再查询能力信息。此处能解释 Grafana 采集刷新变慢并可能占用应用处理资源；尚未证明它是所有页面卡顿的唯一原因。
- 本轮生产只读 PG/API/资源采样实际完成5×600秒，时间为2026-10-06 23:59:37至2026-10-07 00:49:37 UTC（约50分钟）；第6段短文件不纳入统计，采样进程已停止。`snmp_mib_nodes` seq_scan保持1、seq_tup_read保持67612；`interface_telemetry_raw` seq_scan保持1。PG未见持续多秒SQL或锁等待；一次00:35:56 UTC的事务ID锁等待约191ms。00:20:18 UTC多条成功API耗时约1.3–2.0秒时，PG活动查询采样年龄约3ms。
- 资产列表、新增表单和编辑表单在Chrome已登录会话中均能呈现，列表17条；未保存或提交。资产保存慢/报错仍未验证。采样 helper 对资产和 Grafana API 的未认证请求返回401，不代表已登录业务请求或真实 PromQL 耗时。
- 全场景1/2 RPS短预检失败：Redis warmup有5次 `redis_command_failed`，且 VictoriaMetrics/Grafana/NetOps延迟高。隔离栈清理完成。本轮不启动两小时合成混合压力；50分钟生产只读采样后停止。失败预检不作生产根因证据。
- 记录见 [两小时压力测试计划](docs/plans/plan_20261007_0750_01_两小时容器压力测试.md) 和 [阶段采样报告](docs/walkthrough/walkthrough_20261007_0750_01_两小时容器压力测试.md)。远端原始窗口位于 `/tmp/nexora-soak-20261007-075450/pg-01.jsonl` 及后续分段和 `.resources.jsonl`。
- 历史生产采样结果见 [两小时压力测试计划](docs/plans/plan_20261007_0750_01_两小时容器压力测试.md) 和 [阶段采样报告](docs/walkthrough/walkthrough_20261007_0750_01_两小时容器压力测试.md)。当前结论：没有证据证明设备数量本身或持续 PG 慢查询是主因；最明确的监控慢点是每分钟 `/hardware-metrics` 应用处理4.48秒p95。资产保存仍未验证。长时隔离压测后来两次被主机负载保护器提前中止，不能表述为完成或通过。

## 当前目标与授权

- 目标：修复监控页面、资产表单和采集相关卡顿；验证300台负载候选方案、资源上限与部署后的 API/PG 表现；所有相关代码推送且 Actions 通过，再关闭工作站。
- 授权边界：已授权 SSH、备份、代码部署、索引迁移和测试；没有修改真实网络设备，也没有对资产写入或建立 Grafana 登录态。受保护的资产/看板 API 都返回401，因此不把未认证入口耗时说成真实保存或 PromQL 结果。
- 公共 release workflow run #678（`37516754689`）已成功，发布树提交为 `d2c0629`。远端部署前完整备份位于 `/data/netops-release-backups/release-20261007-032303`；被新版本路径覆盖的旧诊断/容量脚本已保存在 `/data/nexora-preserved-untracked-20261007-032348`。其他未跟踪诊断产物仍留在原位置；未运行 `git clean`。
- Docker 主机 `/data/nexora-automation` 已部署。11个容器均运行，9个有 healthcheck 的容器 healthy，SeaweedFS 与 socket proxy 无 healthcheck。11个服务的内存、CPU、PID 限额均非零；Nginx 配置有效、worker 为1；Grafana旧dashboard清理步骤已跳过。
- m0276 已迁移。实际 MIB 精确查询使用 `idx_snmp_mib_nodes_name_lower`；部署后两轮 `snmp_mib_nodes` 顺扫增量均为0、索引扫描增量144。

## 部署后复测

| 窗口（Asia/Shanghai） | 后端 live p95 / max | Nginx live p95 / max | Grafana / VM health p95 | 慢请求与数据库 |
| --- | --- | --- | --- | --- |
| 03:31:14–03:36:14 | 39.8 / 108.1ms | 215.8 / 1326.4ms | 4.7 / 3.8ms | 1个 HTTP 样本≥1s，无超时；PG active query 最大224.5ms，无 lock wait。 |
| 03:38:02–03:43:02 | 266.4 / 707.2ms | 243.3 / 616.3ms | 7.2 / 3.9ms | 没有 HTTP 样本≥1s或超时；PG active query 最大386.9ms，无 lock wait。 |

- 每轮300秒：后端 live 与代理各60次；Grafana/VM health 各60次；资产表单/列表依赖 API 每条路由直连和代理各20次；11个 Grafana dashboard URL 每个10次。资产和 dashboard API 均返回401；已认证的保存和 PromQL 仍未测。
- 两轮均未见 `snmp_mib_nodes` 顺扫或 tuple-read 增量；精确符号计划使用表达式索引。`interface_telemetry_raw` 顺扫增量0。PG 无 lock wait/blocker；idle-in-transaction 最长约5.15/5.32秒，active query 年龄低于0.4秒。
- 7个主要业务/监控容器 CPU 总和 p95 折算为双核主机约61.8%/57.0%；后端 CPU p95 为103.1%/96.0%，内存 p95 约460/462MiB；无 cgroup throttling/OOM。每轮结尾的全11容器 `docker stats` 快照中，应用约432–442MiB，数据库约259–272MiB，SeaweedFS约199MiB；其余服务亦低于各自上限。全11容器快照与持续7容器时序口径不同。
- 与部署前七轮相比，后端 live p95 从0.58–4.18秒降至0.04–0.27秒；最大代理样本1.33秒仅出现在第一轮，第二轮未重现。卡顿显著缓解，但不能据此保证真实300台设备或已登录业务页表现。
- 原始样本位于远端 `/tmp/remote-pg-latency-20261007-post-r1*`、`post-r2*`，本机 `%TEMP%\\nexora-latency-20261007`。生产仍为17台设备、15台有 SNMP 绑定、5,296 active sensors。

## 部署前七轮采样基线（旧代码）

- 新增三轮连续约 300 秒多 URL 采样，Asia/Shanghai 窗口为 02:30:17–02:35:17、02:35:33–02:40:33、02:41:18–02:46:18；总计与更早的四轮合为七轮。
- 三轮后端 live p95 为 2.33 秒、0.58 秒、2.26 秒；Nginx p95 为 3.82 秒、0.59 秒、2.17 秒。第一、第三轮各出现一次约 6 秒直连/代理同步超时，第二轮无超时；慢请求约每两分钟成簇。Grafana 与 VictoriaMetrics health p95 保持约 5.6–11.1ms。
- 受保护的资产表单、列表和 11 个 dashboard URL 均因无用户会话返回 401；此延迟不能代表已认证查询、保存或 PromQL 面板的真实响应。没有执行生产资产写入或创建 Grafana session。
- 每轮 `snmp_mib_nodes` 增加 48 次 Seq Scan 和 3,245,376 tuple read；表约 67,612 行。PG 1 秒活动样本最长 active SQL 约 329–513ms，没有 lock wait/blocker。PG 没有可用的 `pg_stat_statements`；该采样可能漏掉短 SQL。
- 第三轮应用容器 CPU p95 99.63%、峰值109.95%，内存约693MiB；数据库 CPU p95 42.8%。7个核心容器 CPU 合计 p95 相当于两核约58.8%；cgroup 没有 CPU throttling/OOM。此资源列表未包括 Redis、SeaweedFS、cAdvisor 和 socket proxy。
- 生产当前只有17台设备、15台带 SNMP 绑定、5,296个 active sensor，因此真实远端不等于300台验证。隔离 PostgreSQL + fake SNMP 的密度校准从143.799秒/186,649 SQL降至26.142秒/529 SQL，但不能保证生产真实网络时延。

## 已完成本地修复与验证

- 新增 MIB `LOWER(node_name)` 表达式索引迁移，修复实测 Seq Scan 对应查询；迁移后生产只读 EXPLAIN 已使用索引。
- 传感器样本改为按设备批量写入；新增全空值批次 PostgreSQL 类型 cast；采集器样本落库及采集状态同步记录从 async event loop 移到线程。其他少数同步路径仍保留，不能宣称已消除全部阻塞。
- Compose 为11个容器设置 CPU、内存、PID 上限；Nginx worker 默认1并受 PID 上限约束（1–8）；Uvicorn `WORKERS=1` 保持不变。
- GitHub Actions #677 的异步标记失败已改为 `asyncio.run`；部署服务选择加入 cAdvisor/socket proxy。Actions #678 成功：后端收集2,943项并通过，前端115个文件/445项测试通过，release 总时长12分9秒。
- 本地聚焦验证：health resource execution 7 passed，Docker storage/deploy contract 4 passed；Git Bash 语法与 `git diff --check` 通过。更早的焦点回归和300台隔离 PostgreSQL/fake-SNMP 结果保留在 walkthrough。

## 尚待执行

1. 精确提交本次部署结果、两轮采样和修复记录；保留 `.agents/skills/netops-grafana-dashboards/SKILL.md`、`logs/`、`dist-*`、`.codex-build-validation-*` 和 fake TEST-MIB 等用户/临时文件，不纳入提交。
2. push 文档提交并等待其 Actions 完整成功；之后关闭剩余 SSH 会话，并按用户要求关闭工作站。

---

# 历史交接检查点（2026-10-07 02:18）

> 下方内容记录之前的检查状态；其中旧的“暂不提交、不 push、不部署、不关机”授权限制已经被本次对话中的最新用户指示取代。具体技术证据仍保留作历史参考。

## 1. 当前目标和授权边界

- 用户最新请求：接续交接排查页面/资产操作卡顿及疑似 PG 查询慢，用户怀疑设备数量及 SNMP 频率负载。
- 主任务：依据真实 Linux Docker 证据排查 Nexora 页面卡顿，修正后端阻塞调用和连接复用，为所有容器设置可调整资源配额，将 Nginx 默认 worker 改为 1。
- **后端 Uvicorn `WORKERS=1` 保持不变**。用户明确要求“先不要改 worker 数量”；Nginx worker 是另外一个配置。
- **暂不提交、不 push、不部署**。用户“完成后先不要 push，我还有别的问题”的指令仍有效。
- 不修改真实网络设备，不对远端数据库写入、安装扩展、重置统计或重启服务。用户明确授权 SSH 只读检查与采样；已完成四轮各 300 秒的多 URL/PG/容器采样，以及一轮 60 秒的设备和 SNMP 传感器聚合计数，并只读 EXPLAIN 了实际 MIB 精确匹配查询。SSH 已关闭，未持久保存凭据。授权仍不包含部署、配置修改或业务写入。
- 所有本轮代码和配置仍是本地未提交改动，不能宣称真实 Docker 已完成修复。最新资源分配附件只是评估，未自动采纳。
- 工作区：`D:\netops\netsops-main`，当前分支 `main`。本机是 Windows，**没有 Docker 部署环境**。
- 真实部署：Linux `root@devops`，目录 `/data/nexora-automation`，页面 `https://192.168.204.128/monitor/dashboards`。已提供证据显示主机 2 个逻辑 CPU、Docker 可见约 7.709 GiB 内存。
- 遵循 `.agents/AGENTS.md`；按需使用 backend、monitoring-telemetry、quality-gate、release、seaweedfs skills。`handoff.md`、`.agents/`、`.codex/` 是内部协作材料，不进入公有发布树。

## 2. 当前执行状态：完整回归已运行，修复一项迁移测试断言

- 当前工作树执行 `uv run --offline --project backend pytest backend/tests -q --tb=short`，结果为 **3410 passed, 1 failed, 1 skipped, 26 subtests passed**，用时5736.01秒（95分36秒）。唯一失败是 `backend/tests/database/test_m0275_huawei_yunshan_platform.py::test_m0275_registers_scoped_templates_and_preserves_custom_profile`：期望 `MAX(schema_migrations.version)==274`，实际276。
- 原因是本任务新增 m0276 后，m0275 测试的“最新迁移仍是274”前置假设过时。已将其改为确认274已登记、275已删除，再测试重放275；m0275 与 m0276 的相邻迁移测试组随后 **5 passed / 67.04s**。
- 全量回归没有在这项测试断言修正后再跑一次，因此完整全量结果仍按一次失败报告；其余3410个通过项、一个显式要求 Redis 短期 key 授权的跳过项和26个 subtests均来自同一次全量运行。
- SNMP 样本批量 helper 和轮询接入相关聚焦套件 **36 passed**；同规模300台/93,192传感器的端到端测试 **1 passed**。此前初始全量快照中的旧失败项在本次全量中均通过。
- 本轮测试只使用本地隔离 PostgreSQL 与 fake SNMP；没有对业务库运行测试。全量 pytest 进程已结束。

## 3. 已确认的真实 Docker 证据及结论边界

### 正常采样，没有主动复现卡顿

- 用户原始日志：`C:\Users\NINGMEI\Desktop\nexora-container-review-20261006_220737.log`。
- 用户明确回复：“本次没有测试”。采样窗 22:07:37.822～22:08:38.775，约 60.95 秒。
- 解析结果：`logs/validation/perf-container-review-20261006_220737.json`。
- 后端直连 `/api/health/live` 约 5～48.3ms，经 Nginx 约 9.4～119.6ms；不能据此否定其他时段或业务请求的卡顿。
- MIB/raw 表该窗口 seq scan 增量均为 0。事务 rollback +1699，commit +606，无 deadlock。

### 用户实际复现卡顿的采样

- 用户原始日志：`C:\Users\NINGMEI\Desktop\nexora-container-review-20261006_221103.log`。
- 用户确认：“这次有卡顿，确定是旧代码在跑”。窗口 22:11:04.035～22:12:05.975，约 61.94 秒。
- 解析结果：`logs/validation/perf-container-review-20261006_221103.json`。
- 后端直连 live 四次：约 **50.9ms、1931.1ms、5007ms 超时、553.3ms**；经 Nginx 四次约 50～1246ms，TCP 建连约 0.16～1.20ms。
- **绕过 Nginx 的轻量 live 请求也出现秒级延迟和超时，确认卡顿涉及后端请求执行/事件循环/宿主机调度路径。** 不能仅凭这条证据分配每次卡顿的具体代码责任。
- `snmp_mib_nodes`：seq scan +13，扫描行 +878956 = 13 × 67612，有整表扫描证据。
- `interface_telemetry_raw`：seq scan +6，扫描行 +1096436；复合索引扫描 +540、索引读取 +332150。DB commit +835、rollback +2740，block read +54282、hit +410733，窗口命中率约 88.33%。
- 上述扫描与卡顿同窗发生，但没有 SQL 耗时/执行计划和请求时间关联，**不能判定某一张表或 rollup 是全部卡顿的根因**。PostgreSQL block read 也不等于物理磁盘读取耗时。
- 1m rollup 表索引计数无增量，不能声称本窗口确认 rollup 执行。
- 该窗口 Netops CPU 最高约 81.54%，内存约 703～704MiB / 2GiB；PG CPU 最高约 48.33%。未见新增 CPU throttling、OOM、容器重启或锁阻塞。
- activity 捕获到 `idle in transaction / ClientRead`，不是锁等待，也不是持续执行 SQL 的时长。两个窗口 temp bytes 增量都为 9,109,504，不能据此认定卡顿窗口有独有 spill。

### 线上代码和组件审查

- 两次日志镜像、启动时间及配置一致；`engine/orchestrator.py`、`database/core.py`、`main.py` 的源文件 SHA 与本地 HEAD 一致，和当前工作区修复后的内容不同。仅据此确认这三个关键文件未采用本轮补丁，不扩大为所有文件逐一已核验。
- 实际 `WORKERS=1`、`DB_POOL_SIZE=16`、overflow=4，未配置 `DB_POOL_MIN_SIZE`；`STORAGE_BACKEND=s3`，**SeaweedFS 确实在用**。
- PostgreSQL 18.6：`shared_preload_libraries` 为空，`pg_stat_statements` 安装包可用但未启用；未执行安装、重启或统计重置。
- Nginx/Redis/VM 的低 CPU、低内存不能证明业务性能完全没问题；Grafana/VM 轻量 health 正常也不代表业务查询正常。
- 高 rollback 计数不等于同数量的数据库错误：SELECT-only 事务清理、连接回收探测和 `_db_quick()` 都可能贡献；不能把全部 82 万次归给一个函数。
- 历史累计 raw 扫描行最多，只能定位扫描热点，不能替代 SQL 总耗时或 CPU 证据。
- 2h rollup 窗口及每 12 次成功采集维护一次的代码行为已核实，实际间隔还包含采集耗时和休眠，不是严格每 12 分钟。
- 已有 `/api/ai/metrics`（`ai.audit.view`）数据库只读观测可作为扩展起点；已有 pg_stat_statements 可用时 top20 与 activity fallback，但不是完整平台 SQL 历史监控。
- 后续若启用 pg_stat_statements，需单独完成配置和计划重启；它提供调用/耗时/缓冲区信息，不直接提供 SQL CPU 耗时。
- 未盲目新增 trgm 索引、改变 SELECT 提交行为或缩短 rollup 回溯窗口。

## 4. 本轮后端实际改动（全部未提交）

| 文件 | 行为 |
| --- | --- |
| `backend/core/scheduler_lock.py` | 异步锁获取/释放移入线程，shield 并等待重复取消后的清理，保留所有权围栏、心跳和同步入口。 |
| `backend/main.py` | 请求日志中同步 `validate_session_token` 改用 `asyncio.to_thread`，请求 ContextVar 仍在请求协程设置。 |
| `backend/database/core.py` | 增加 `DB_POOL_MIN_SIZE`；默认按 pool size 保留连接，默认 16；上限仍 16+4=20/worker，保留事务清理、失效连接探测及获取超时。 |
| `backend/services/notification_service.py` | 物化收件人/SMTP 配置并释放 DB 连接后发 Webhook/邮件；保留 SMTP 配置失败时 Webhook 独立发送及原错误处理契约。 |
| `backend/api/health.py` | resources/metrics/history 等同步路由由 FastAPI 线程池执行；HTTP 资源读取不同步触发告警；定时采样仍处理告警；告警外发前提交、释放连接。 |
| `backend/engine/orchestrator.py` | A/B 设备查询物化快照移入线程；B-loop 每 12 次成功采集的遥测维护移入线程；保持过滤、顺序、cycle_tick 和设备并发契约。 |
| `.env.example`、`docker-compose.yml` | 增加 DB_POOL_MIN_SIZE，默认随 DB_POOL_SIZE；另含下面资源配额配置。 |

剩余边界：LLDP 同步告警、ConnectionPool.cleanup 因共享状态仍保留原路径；不能宣称全部阻塞已消除。线程运行不能因取消 await 被强制终止。告警先提交后直接外发没有持久化 outbox，提交后崩溃/发送失败仍存在漏发窗口，未在本轮扩大为架构变更。

### 新增/修改回归测试

- 修改：`backend/tests/database/test_scheduler_lock_leases.py`。
- 新增：`backend/tests/database/test_pg_pool_reuse.py`、`backend/tests/security/test_request_logging_execution.py`。
- 新增：`backend/tests/monitoring/test_health_resource_execution.py`、`test_notification_connection_lifecycle.py`、`test_telemetry_orchestrator_execution.py`。
- 覆盖慢鉴权/资源读取时 live 响应可推进、请求上下文、租约取消清理、连接复用/上限、数据库关闭先于外发、SMTP 失败兼容、多循环成功次数和线程执行。

## 5. Docker 配额和 Nginx 当前工作区方案

所有 11 个服务已设置 `cpus`、`mem_limit`、`pids_limit`。CPU/内存有 `.env.example` 可调默认值；CPU 上限不预留独占核，内存上限不预分配。

| 服务 | CPU 上限 | 内存上限 | PIDs |
| --- | ---: | ---: | ---: |
| netops | 2.0 | 2304m | 512 |
| db | 2.0 | 1g | 256 |
| victoriametrics | 2.0 | 768m | 256 |
| grafana | 1.0 | 384m | 256 |
| seaweedfs | 1.0 | 512m | 256 |
| redis | 1.0 | 1g | 128 |
| nginx | 1.0 | 256m | 128 |
| vmagent | 1.0 | 192m | 128 |
| snmp-exporter | 1.0 | 128m | 128 |
| cadvisor | 0.5 | 128m | 128 |
| docker-socket-proxy | 0.25 | 64m | 64 |

- 合计 **6784MiB = 6.625GiB**，按真实主机约留 1.084GiB 给宿主机及余量。Redis 内部 `maxmemory=512mb` 不变，其余内存留给缓冲、AOF 和进程开销。
- Env 前缀：`NETOPS`、`POSTGRES`、`VICTORIAMETRICS`、`GRAFANA`、`SEAWEEDFS`、`REDIS`、`NGINX`、`VMAGENT`、`SNMP_EXPORTER`、`CADVISOR`、`DOCKER_SOCKET_PROXY`，后缀 `_CPUS` / `_MEM_LIMIT`。
- 用户最新资源附件第一版合计 **7872MiB = 7.6875GiB**，在当前主机仅留约 22MiB；附件声称 7.25GB 的加总不正确，**没有采纳**。
- 附件第二版合计 **6976MiB = 6.8125GiB**，较合理但 Redis 从 1GiB 降至 768MiB 要和内部 maxmemory 一起考虑；后续还可评估 PG/SeaweedFS/SNMP 增加余量。没有自动切换到第二版或创建自动资源档位。
- 增加 PostgreSQL 容器内存上限不会自动调优 shared_buffers/work_mem。扩展本身也不能直接推导额外 512MiB 的必要性。

### Nginx 单 worker 实现

- 用户真实 `nginx -T` / `ps`：主配置 `worker_processes auto`，connections 1024，实际 2 个 worker。
- 仓库 `nginx/nginx.conf` 是挂载到 `/etc/nginx/conf.d/default.conf` 的站点配置，不适合写顶层 worker 指令。
- 新文件：`nginx/docker-entrypoint.d/40-configure-workers.sh`，在官方 30 自动调优 hook 之后执行，重写容器 `/etc/nginx/nginx.conf` 的唯一 worker 指令。
- 配置 `NGINX_WORKER_PROCESSES` 默认 1，允许整数 1～1024；非法值、缺失/重复指令明确失败。修改具有幂等性，不改 worker_connections。
- `nginx/Dockerfile` COPY 并 chmod 新 hook；Compose 和 `.env.example` 加入默认值；没有修改后端 WORKERS。
- 新测试：`backend/tests/release/test_nginx_worker_contract.py`，Git Bash 对临时主配置执行实际 hook 函数，覆盖默认、自定义、LF/CRLF、重复执行和拒绝非法输入。
- 未在 Linux 做 Docker 构建、`nginx -t`、重建容器或线上验证。未来应用 Compose 配额/环境和镜像 hook 需要经授权重建相应容器，单纯 restart 不会更新全部配置。

## 6. 已完成验证与未完成验证

| 验证 | 结果 / 日志 |
| --- | --- |
| 首轮后端定向 | 12 passed / 140.26s；`logs/validation/perf-focused-20261006_2054.log`，早于最后两条 pool 测试。 |
| health/通知/pool/groups/outbox 定向 | 29 passed / 约 200s；`logs/validation/perf-notifications-20261006_2054.log`。 |
| SMTP 兼容补丁后通知/groups/outbox | 22 passed / 350.60s；`logs/validation/perf-notifications-final-20261006_2054.log`，临时库已清理。 |
| 遥测线程执行 | 2 passed / 184.15s；`logs/validation/perf-telemetry-loop-20261006_2054.log`，临时库已清理。 |
| Nginx/存储/Redis/监控部署契约 | 首轮 27 passed、2 个新测试 CRLF 字节比较失败；确认 Git Bash sed 的 LF 规范化后调整新测试按规范化内容比较，既有 15 项部署契约已通过。 |
| Nginx 最终新测试 | 14 passed / 4.88s，退出 0；覆盖实际 hook 行为，未删除/削弱业务断言。 |
| 静态检查 | PostgreSQL-only policy scanner 通过；变更 Python AST、Compose YAML/配额默认值、shell `bash -n`、相关 diff whitespace 检查通过。 |
| 全量后端 | **仍运行，65%，2 F / 1 s，最终报告待取得**；session 60701。 |
| Linux Docker 集成/线上性能复测 | **未执行**，本机不具备该环境且没有部署授权。 |

纯配置/部署测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/release/test_nginx_worker_contract.py backend/tests/release/test_deploy_docker_storage_contract.py backend/tests/release/test_deploy_docker_redis_contract.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py -q --confcutdir=backend/tests/release
```

`--confcutdir` 用于这些纯文件/配置测试，避免无关 PostgreSQL 自动 fixture；不能用于绕过实际数据库业务测试。此次没有重复运行前端全量构建，前端已有改动保留。

## 7. 真实 Docker 只读采集脚本和敏感信息

- 本轮脚本：`scripts/diagnostics/collect_nexora_container_review.sh`，默认 60 秒，10 秒采样；只读 SQL、5 秒 statement timeout、1 秒 lock timeout，日志 umask 077、避免覆盖。
- 内容包括配置白名单、源文件 hash、资源/cgroup、DB 表/索引计数增量、活动与阻塞摘要、可用时 pg_stat_statements、后端直连和代理 live 探测。不输出完整 SQL、密码、完整环境或原始业务日志。
- 用户两份日志来自脚本早期版本。最新脚本补充连接数、temp、work_mem/shared_buffers、状态计数和监控文件 hash；已通过语法验证，最新补充项尚未在真实 Linux 复测。
- 传输/执行示例（后续有需要再给用户，不自动执行远端操作）：

```powershell
scp "D:\netops\netsops-main\scripts\diagnostics\collect_nexora_container_review.sh" root@192.168.204.128:/tmp/
```

```bash
DURATION_SECONDS=60 bash /tmp/collect_nexora_container_review.sh
```

- 早期 5 分钟原始采集：`C:\Users\NINGMEI\Desktop\nexora-perf-20261006_203301.log`；保留已有 `scripts/diagnostics/collect_nexora_perf.sh`。
- 相关后端日志附件包含真实 Feishu Webhook。**不要粘贴原始敏感日志、真实 DSN 或凭据到本文件、测试和回复**。

## 8. 并行审查、既有变更与文档入口

- Luna 6 Max 子 Agent `/root/component_perf_audit` 已独立审查截图的九项判断及两份真实容器日志；只读，未修改文件、未触碰远端。
- `/root/latency_health_audit` 完成 health/engine 局部工作与独立审查。后续创建/唤醒部分 Agent 曾遇到 agent thread limit，Nginx/配额由主 Agent 完成；不要声称由子 Agent 实现。
- 最多并行两个子 Agent，不继续嵌套分派；主 Agent 负责共享配置、集成和文档。当前没有已知写代码中的子 Agent。
- 当前工作树还包含更早无线 Grafana/资产首页修改：`backend/api/assets.py`、Grafana generator/presentation/overview/wireless JSON、对应监控和资产测试、`src/pages/HomePage.tsx`/测试、`.gitattributes`、Grafana skill，以及多个 `.codex-build-validation-*`/`dist-*` 目录。**保留，不 reset/clean/revert，也不自动 stage 全工作区**。
- 早期需求包括无线状态绿色、隐藏采集目标/rule_version、无线流量及 Top、AC 前置及在线/离线统计、在线终端名称、移除资产 ID、首页数量与资产管理一致；具体已改行为和验证以 1934 walkthrough 为准。
- 22:29 工作树出现 `backend/vendor/librenms/mibs/cisco/TEST-MIB-*`，可能来自正在执行的 MIB fixture；先等待测试 cleanup，不能当作生产 MIB 发布或立即清除。
- 根目录 `handoff.md` 旧记录保留在下面；不要把历史已经推送、部署之类的状态套用到这次工作。

当前计划/验证文档：

- `docs/plans/plan_20261006_1934_01_无线面板排序与首页资产数量一致性.md`
- `docs/walkthrough/walkthrough_20261006_1934_01_无线面板排序与首页资产数量一致性.md`
- `docs/plans/plan_20261006_2054_01_API请求阻塞与连接复用.md`
- `docs/walkthrough/walkthrough_20261006_2054_01_API请求阻塞与连接复用.md`
- `docs/walkthrough/walkthrough_20261006_2148_01_页面卡顿与PostgreSQL证据审查.md`
- `docs/plans/plan_20261006_2223_01_Docker资源配额与Nginx进程.md`
- `docs/walkthrough/walkthrough_20261006_2223_01_Docker资源配额与Nginx进程.md`
- `docs/deploy/docker.md`：资源配额、Nginx hook、未来重建/核验说明。

## 9. 接手后的下一步顺序

1. **完成**：结束并记录全量后端 pytest 结果；继续保留10项失败的原始证据，局部定向验证通过不覆盖全量红灯。
2. **完成**：按用户要求执行四轮各5分钟的远端多 URL 采样，补充60秒 SNMP binding/sensor 聚合统计，整理结果见本节和 walkthrough。
3. **完成**：用生产只读连接对 `_resolve_mib_symbol` 对应的精确 SQL 执行 EXPLAIN；计划为 `snmp_mib_nodes` Seq Scan。下一步在隔离 PostgreSQL 验证表达式索引和迁移，然后做 fake SNMP 的300台合成规模核验。
4. 当前能确认周期性应用级停顿与 MIB seq scan 同期出现，但不能确认因果。资产和 Grafana 业务 API 采样未登录、返回401；获得登录态后可再同步复现 dashboard 刷新及资产表单加载，并关联 request ID、PG耗时及 event-loop lag/连接池等待。
5. 如继续做只读远端核验，优先确认设备硬件 discovery/capability 的版本新鲜度、probe/discovery 模块的线上源文件指纹，以及 MIB scan 每轮触发的设备数；不启用扩展或重置 PG 统计。
6. Docker 资源配额方案、Nginx worker 调整、后端阻塞补丁和新 MIB 索引仍是本地工作区候选，尚未部署；保持 Uvicorn worker 1。
7. **继续保持不提交、不 push、不部署、不改真实设备或采集频率**，直到用户更新授权。提交前按项目规则补 `docs/fixes/` 并剔除内部协作文件和测试产物。

## 10. 页面、资产、Grafana 与 SNMP/PG 最新排查结果（2026-10-06）

- 用户报告的触发点：打开/刷新监控看板；资产添加/修改表单打开和保存；Grafana 偶发慢。错误文字未知。本轮没有通过浏览器完成真实登录态操作。
- 采样器按真实前端调用链重复 GET `/api/racks`、`/api/cmdb/sites`、`/api/credentials`、资产 summary/list、Grafana auth gate，以及前端 dashboard 页面列出的11个 Grafana URL；同时探测后端直连和 Nginx health、Grafana/VictoriaMetrics health。请求间隔分别为 health 5秒、API 15秒、dashboard 30秒，超时6秒；没有 Authorization/Cookie，不读响应体，也没有调用有 session 副作用的 `POST /api/grafana/session`。
- 完成两个连续的300秒窗口和一个60秒只读聚合计数窗口。原始脱敏数据：`logs/validation/remote-pg-latency-20261006_230914.jsonl` 及 `.resources.jsonl`、汇总 `...230914.summary.json`；`logs/validation/remote-pg-latency-20261006_231514.jsonl` 及 `.resources.jsonl`、汇总 `...231514.summary.json`；计数窗口 `logs/validation/remote-pg-latency-20261006_232243.jsonl` 及 `.resources.jsonl`。
- 两个300秒窗口都出现应用 live 与多个 API 同时变慢/超时的簇，重复间隔约110秒。窗口1后端直连56次，p50 7.1ms/p95 4175ms/max 6007ms、2次超时；Nginx 56次，p50 20.8ms/p95 5840ms/max 6041ms、2次超时。窗口2后端直连57次，p50 11.3ms/p95 4019ms/max 6006ms、1次超时；Nginx 57次，p50 21.4ms/p95 4001ms/max 6011ms、1次超时。Grafana/VM health 在两个窗口保持快速成功，第二窗口 p95 分别10.4ms/5.5ms。
- 受保护的资产 API 与11个 dashboard URL 没有用户会话，绝大多数请求返回401；部分在同一停顿簇中超时。这只能证明这些 URL 的请求也碰到同一应用级停顿，不能代表认证后的资产查询/保存或 Grafana PromQL 页面耗时。没有发起资产 POST/PUT 保存请求（保持只读授权）；未读取、保存或输出响应体和凭据。
- 两轮 PostgreSQL activity 分别采样298/299次，最长 active SQL 年龄约341/412ms，没有采样到锁等待或阻塞。`pg_stat_statements` 未启用，1秒采样也可能漏掉短 SQL。两轮 `snmp_mib_nodes` 都增加42次 seq scan、读取2,839,704行（表约67,612行），集中在约110秒节律的扫描簇；`interface_telemetry_raw` 两轮 seq scan 均为0，以索引读取为主。现有证据没有给出这些 MIB 查询的单次耗时，不能据扫描行数断言它独自导致卡顿。
- NetOps 容器 CPU p95 两轮约92%/101%，峰值约103%/106%，约为一个 CPU；容器 quota 是2 CPU。cgroup 未见 throttling/OOM。PostgreSQL、Grafana、VictoriaMetrics、SNMP exporter 没有持续满载迹象。应用容器存在周期性 CPU/阻塞负担，但当前不能定位到单条 SQL。
- 60秒只读 fleet 汇总：17台设备，15台有 SNMP community/credential 绑定；A/B native loop 候选各17台。硬件传感器表有5,296条 active sensor、涉及15台设备。V1 assignment 按间隔为30秒/15台、120秒/1台、900秒/15台；native 与 V1 资产是否重叠未知，`explicit_snmp_profiles=0` 也不代表没有 SNMP。这些计数表明采集负载值得关注，但不等于5,296个独立 SNMP 包。
- 代码路径证据（工作区）：B-loop await `process_device_slow`；若设备/硬件发现被判 stale，会触发自动 `discover_device_oid_config`，经 LibreNMS hardware probe 解析 MIB 符号；`_resolve_mib_symbol` 在 async 探测路径里同步执行 `LOWER(node_name)` SQL，计划含 `Seq Scan snmp_mib_nodes`。这是比常规 active sensor 轮询更直接的扫描路径。active sensor 轮询另会同步加载传感器清单并 await SNMP walk。周期性全表扫描与 API 停顿节律吻合，使自动硬件发现/MIB 查找成为首要疑点，但远端本轮源文件指纹未包括 discovery/probe 模块，且没有查询耗时/请求 ID关联，仍未证实根因。
- 资产表单的 `/api/credentials` 原先按每条 credential 单独读取关联 devices。`backend/services/credential_service.py` 已改为单次 `ANY(array)` 批量读取，新增 `backend/tests/configuration/test_credential_list_batching.py`；这只减少表单选项加载的 N+1。`backend/api/assets.py` 另修复独立 SNMP credential 的 community 不再误建 SSH credential binding，对应资产绑定单测单独重跑通过。所有这些改动均未部署。
- 当前完整后端回归为3410 passed、1 failed、1 skipped、26 subtests passed；唯一失败是 m0275 测试对“最高 migration version=274”的旧假设。该断言已修复，m0275+m0276相邻迁移组5 passed；全量没有因测试-only修复再跑一次。诊断 helper 为14 passed；硬件样本批量相关聚焦组36 passed；PostgreSQL-only scanner 为0 violations。
- 下一步需要用户登录态下同步复现 dashboard 刷新及资产表单打开/保存，关联浏览器时间、请求 ID、已认证 API 耗时，并补充 event-loop lag/连接池等待观测，才能分开页面、授权、SQL和采集的因果关系。未启用扩展、未重置 PG 统计、未重启容器、未部署、未改采集频率或设备。

## 11. 加长采样与 MIB 精确查询计划（2026-10-07）

- 用户要求把远端采样延长到约5分钟、多次重复调用页面/API URL。基于该授权新增完成两轮300秒窗口（23:47:26–23:52:26、23:53:30–23:58:30），与既有两轮构成四轮；追加采样覆盖资产表单的 `/api/racks/validate-u` 哨兵 GET。远端原始文件保留在 `/tmp/remote-pg-latency-20261006-2347-r1*`、`/tmp/remote-pg-latency-20261006-2353-r2*`，早期窗口见 `...230914*` 和 `...231514*`。
- 新窗口后端直连 live p95 为2,196ms/2,751ms，Nginx p95 为1,794ms/3,489ms；Grafana/VM health p95 为8.4/11.5ms和5.9/6.7ms。两轮 `snmp_mib_nodes` 均新增42次 seq scan、读取2,839,704行。最新两轮 PG activity 活跃查询最大年龄约266/396ms，无 lock wait/block；应用容器 CPU p95约97.6%/85.3%，没有 CPU throttling 或 OOM。
- 当前生产规模仍是17台设备、15台 SNMP 绑定设备、5,296条 active hardware sensor，远低于300台目标；不得将线上真实采样描述成300台验证。
- 用户给出的浏览器当前无登录态；资产及Grafana受保护路由仍返回401。真实保存 POST/PUT、登录后 PromQL/业务查询和浏览器请求关联未测试，不能用未认证 gate 延迟代替。
- 对照 `snmp_hardware_probe_service._resolve_mib_symbol` 精确过滤/join/order/limit 的只读 `EXPLAIN (FORMAT JSON)`：顶层 Limit→Sort→Hash Join；`snmp_mib_nodes` 为 Seq Scan，估算成本约5323、匹配336行；没有执行 ANALYZE。计划使用表达式索引 `LOWER(node_name)` 进行隔离验证。诊断 helper 已加入该精确计划探针及回归测试（14 passed）。
- 新增计划与 walkthrough：`docs/plans/plan_20261007_0004_01_SNMP符号查询与300台容量验证.md`、`docs/walkthrough/walkthrough_20261007_0004_01_SNMP符号查询与300台容量验证.md`。`LOWER(node_name)` 表达式索引迁移已通过3万条合成 MIB nodes 的隔离 PG planner 测试；默认 planner 选择该索引，fresh schema 和重复迁移测试通过。迁移尚未部署到生产。
- 300台合成轮询基线为143.799秒、186,649条 SQL、样本 SQL 118.712秒；批量候选同场景为26.142秒、529条 SQL、批量样本 SQL 12.464秒，93,192个样本全部写入成功。测试覆盖隔离 PostgreSQL 与 fake SNMP，不能外推为生产时延承诺。
- 批量 helper/轮询接入回归36 passed；300台复测1 passed；前端 lint、独立目录 production build、首页测试及配置/部署契约测试通过；PostgreSQL-only scanner 为0 violations。完整后端回归3410 passed、1 failed、1 skipped、26 subtests；m0275测试断言修正后相邻迁移组5 passed，完整套件未重跑。
- 只读业务 URL 因没有登录态仍为401；资产保存 POST/PUT 和登录后 Grafana/业务查询时延尚未复现。SSH 已关闭。
- 依据当前授权边界继续保持本地未提交状态；不 push、不部署、不关机。

---

# 历史交接记录（原文保留，以下不代表当前执行状态或授权）

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

## 2026-10-07 登录态页面卡顿复现与两小时 soak

- 已登录 Chrome 交替打开 `/dashboard` 与 `/assets/dashboard` 三轮，6次导航均渲染成功，约1.35–1.71秒；资产列表及新增/编辑表单选项读取返回200。没有提交资产保存、执行连通性测试或访问真实设备。
- `/monitor/telemetry` 的概览请求在生产现场重复失败：最近5分钟 Nginx 记录38次 `GET /api/monitoring/overview` 500；NetOps traceback 指向 `backend/api/monitoring.py:649`，数据库收到字面的 `""" + tenant_clause + """` 并报语法错误。该接口错误可解释监控概览缺数据和周期性失败，不是慢 SQL；源码同文件另有行347、674、708、747的类似三引号拼接点，均需修复并补验证。
- Grafana 另一个已确认慢路径是每分钟调用 `/hardware-metrics`，读取/处理约5296条活动传感器记录，p95约4.10秒、最大5.58秒；既往50分钟PG采样未见持续慢SQL或锁等待。当前证据不支持17台设备的SNMP数量是主因；资产保存慢/报错仍未在生产写入验证。
- 7200秒登录态只读 soak 已于2026-10-07 01:53:52 UTC启动，浏览器留在 `/assets/dashboard`，不再反复访问已知会500的监控中心。远端采样目录 `/tmp/nexora-live-soak-20261007-0953/`，进程PID `266359`；每60秒记录Nginx请求/状态汇总、后端失败路由、load、MemAvailable、`/data`空间、生产容器健康/重启/OOM，超过停止线自动结束。首样本为load1 1.77、MemAvailable约5.0GiB、11容器运行健康、窗口内0个5xx。必须等 `summary.json` 显示实际时长不少于7200秒后再交付完整两小时报告；不要把先前50分钟采样或中止的合成测试累计进去。
- 登录后正常页面轮询会自然访问 `/api/health/resources`（该端点记录主机资源样本）；看板导航还会创建临时 Grafana session。除此之外没有业务数据写入。采样期间只允许低频切换看板/资产页，若 `load1>4.5` 连续3分钟、MemAvailable低于3GiB、容器 unhealthy/重启/OOM或Nginx每分钟5xx超过10连续3次则停止。
- 最新延伸样本：登录资产页重复表单三轮，新增开窗0.771–0.858秒、编辑开窗0.811–0.875秒，取消未保存；列表重载0.536–1.476秒。Grafana iframe首屏6.6秒仍显示加载、约16.6秒时已可读；热重载可读到指标耗时3.554秒。与热重载对应的65秒Nginx窗口266请求，261×200、3×499（导航取消）、2×101（WebSocket），`/grafana/api/ds/query` 33次、VictoriaMetrics query 12次、backend failure 0；load1 3.32、MemAvailable 4.98GiB、11容器正常。
- 采样器最新记录（01:58:52 UTC）为累计300.3秒、5个60秒样本，summary尚未生成；仍需等待到至少03:53:52 UTC并复核远端summary、JSONL、容器状态后才能完成目标。
- 更新后的主要普通页面延迟候选：`src/App.tsx` 初始化/路由变化和120秒轮询都会请求 `/api/config-templates?page_size=200`。首次结果设置 `selectedTemplateId` 会改变 `fetchSharedLookups` callback 身份并触发依赖 effect 重跑；硬刷新日志可见约1秒间隔的成对请求。生产有132条模板，`backend/api/config_templates.py` 的 `_serialize_template()` 对每条执行版本查询、收藏查询、schema normalization/quality计算，约264条逐项SELECT/请求。两次慢请求日志总耗时p50约1.50秒、最大1.94秒，handler约1.47–1.89秒。慢请求日志只记录≥500ms或错误，不是全量p95。资产页刷新一次2.185秒，但表单开窗仍仅0.77–0.88秒；Grafana另有 `/hardware-metrics` p95约4.10秒与监控概览SQL 500。
- 主soak截至02:09:52 UTC约16分钟、16个样本，最新load1 1.95、MemAvailable约5.07GiB、11个容器正常，窗口53个Nginx请求、0个5xx；资产页2.185秒刷新后仍返回完整页面。长时目标未完成。

### 两小时现场只读 soak 最终结果（2026-10-07）

- 已完成，不要继续等待：远端 `/tmp/nexora-live-soak-20261007-0953/summary.json` 显示 `actual_duration_sec=7200.2`、121样本、`stop_reason=duration_complete`；慢请求侧车7207.4秒后结束。完整原始文件留在同目录。
- 资源分位数：load1 min/p50/p95/max=0.35/1.45/3.32/4.41；MemAvailable=4.79/4.93/5.06/5.10 GiB；swap空闲约2.00 GiB；`/data`空闲17.57–17.61 GiB。load1有短峰但没有连续3个样本超过4.5。11个容器结束时全部running、9个有healthcheck的服务healthy、0重启/0 OOM。
- Nginx 65秒窗口每60秒采样的汇总状态为200:2547、499:15、101:3、401:6、5xx:0；5秒重叠，计数为窗口观察而不是唯一请求数。499为导航取消，101为Grafana WebSocket升级。401集中在登录态到期后：设备路由2次，其余notifications、health/resources、scheduled-jobs/future、playbooks各1次；浏览器约03:46 UTC返回登录页。
- slow-log侧车只包括≥500ms或失败的已认证请求，不等于全量路由p95。79条慢日志里 `/api/config-templates` 有29条200：total p50/p95/max=1.239/1.935/2.157秒，handler=1.195/1.894/2.136秒，auth p50约32ms；132个模板逐条查版本与收藏、再逐条schema处理，是普通页面最强延迟证据。Grafana `/hardware-metrics` 每分钟处理5296条活动传感器，既往实测p95约4.10秒/max5.58秒；`/monitor/telemetry` 概览则因 `backend/api/monitoring.py:649` SQL拼接错误在最近5分钟产生38次500，错误本身不是慢查询。
- 既往约50分钟PG采样没有持续多秒SQL或锁等待（最长活动SQL约1.07秒，单次锁等待约191ms）。两小时host load1 p95 3.32/max4.41，短时CPU竞争可能放大卡顿；但没有逐分钟SNMP关联数据，不能证明设备数量/扫描是主因。当前17台设备、15台SNMP绑定也不支持“设备数过多”的结论。
- 资产新增/编辑表单只读打开分别0.771–0.858s / 0.811–0.875s；保存未提交，用户提到的保存慢/报错仍未验证。本轮未写业务数据、未做真实设备操作、未修改或部署代码。修复优先级：模板接口批量化并避免重复请求、修正监控SQL插值及同类分支、优化硬件指标导出；之后在明确允许的测试环境验证保存路径。

## 2026-10-07 页面卡顿、监控与资产完整修复计划

- 用户最新要求是制定完整修复计划。本轮计划已归档 `docs/plans/plan_20261007_1348_01_页面卡顿与监控资产完整修复.md`，对应走查 `docs/walkthrough/walkthrough_20261007_1348_01_页面卡顿与监控资产完整修复.md`；本轮未修改业务代码、运行业务测试或部署。
- 顺序：阶段0专用PG与全量基线；P0修overview/search及同类SQL拼接并验证租户/缓存/错误态；P1模板列表四条批量数据查询+App选择状态引起的重复lookup；P1资产PUT成功/失败/回滚/跨租户/厂商切换；P2hardware分段计时与最小优化、Grafana冷热分解；SNMP/CPU关联验证；授权后分包部署与至少7200秒有效登录态复测。
- 两名Luna只读审查确认：hardware没有sensor级N+1或现成缓存，短TTL对60秒scrape可能每轮miss；普通资产保存无直接SSH/SNMP，特定投产更新会启动密码轮换；collector在commit后异步防抖。资产保存原始慢点未复现，不能写成已修复。
- 前端确认lookup callback依赖selectedTemplateId并重跑初始化effect；开发StrictMode另会双mount。资产列表/选项和监控hook有错误被吞的路径，计划补401/403/失败状态。Grafana iframe onLoad不等于关键指标可读。
- 测试前置：backend/tests/conftest.py先对DATABASE_URL源库init_db，再建isolated template。只能指向专用本地/CI PostgreSQL，不能指向生产或日常应用库；显式mock轮换、collector及外部连接。本轮保留所有已有未提交变更。
- 主Agent负责共享文件、计划/handoff和最终集成；每轮最多两个Luna 6 Max执行者，不重叠写文件、不重复公共回归。性能目标、阶段门禁、工作包、部署授权与回滚见新计划。下一步先做受控基线与最明确根因修复，不先降低SNMP频率或扩容。

## 2026-10-07 页面卡顿修复执行与本地验收

- 已修复 `backend/api/monitoring.py` 的 overview/search SQL 拼接与租户缓存隔离；模板列表批量读取版本/当前用户收藏；App lookup 按认证会话隔离，取消登出前请求并忽略迟到响应；监控和资产 UI 展示请求失败、权限、空态及重试；hardware exporter 窄字段读取并输出分段耗时。
- 隔离 PG 合同确认现有 `backend/api/assets.py` / rack 服务正确维护 staging 资产/设备关联、冲突与 rack rollback、跨租户拒绝和 Cisco/Huawei/H3C 平台规范；未改生产写入服务。硬件导出/库存回归21项通过，资产 PUT 合同1项通过。
- 后端组合回归47 passed，前端6文件18测试 passed，TypeScript、独立Vite生产构建、PostgreSQL-only（0 violations）和 Python 编译均通过。使用本机临时 PostgreSQL，不用 Docker、不连生产库。
- 5296合成 sensors / 17设备 / 30次本机硬件导出 p95约1.246秒、最大1.248秒、输出约8.36 MB且30次一致；该基准不能外推到生产。阶段日志记录 SQL/解码/分组/渲染/能力查询/响应大小。
- 修复计划与执行 walkthrough 已分别更新在 `docs/plans/plan_20261007_1348_01_页面卡顿与监控资产完整修复.md`、`docs/walkthrough/walkthrough_20261007_1348_01_页面卡顿与监控资产完整修复.md`；提交要求的 fix 记录为 `docs/fixes/fix_20261007_1434_01_页面卡顿与资产完整修复.md`。
- 当前尚未推送或核验 Actions（待本轮最终步骤）。没有在远端部署，没有做 Grafana 10冷/10热浏览器验收或至少7200秒部署后长测，也没有更改 SNMP 周期/并发。生产保存错误仍属未复现；在部署和长测完成前不能称为全部线上问题解决。

## 2026-10-09 多厂商硬件与无线采集最终核验

- 已将 Python 采集修复部署至 `192.168.204.128`，当前镜像 `nexora-netops:final-fixes-v4-20261009`；生产容器内 `shutil.which("php")` 返回 `None`。规则来源固定为 LibreNMS commit `6c26b4fe4a40f7b392c19c36a44257212736e38c`，执行器为 Python；H3C Comware AP/无线因上游无 Wireless discovery，由显式标注的 Python H3C MIB adapter 实现。
- 线上 `network_snmp` 9/9 UP，硬件 inventory scrape 1/1 UP；v7 当前 602 条活动传感器分解见 walkthrough，其中 2 条此前未单列的 Cisco HSRP 状态已补上。CPU 9/9、内存 7/9；温度/光功率/电压/电流/功耗/风扇状态/电源状态及 H3C 无线数据按设备实测返回。9 台设备 `sysUpTime` 均有有效值；当前没有风扇 RPM 样本。
- AC_11 AP_12/AP_13 均为注册 `run`，无线指标链路有样本；四个无线电状态为 admin-disabled / oper-down。AP 客户端数与 controller 客户端数均观测为 0，不能将 AP 注册状态当成 radio 在线发射状态。
- 更精确的状态判读：AP operation status 原始值 5 对应 MIB 定义的 `run`；radio Admin/Oper 对象使用 TruthValue，设备返回 false(2)。Python 映射与原始 SNMP 一致；现有 `dis wlan ap all` 输出只覆盖 AP join 状态，判断 radio 配置/运行状态还需设备 radio 专项输出。当前只收客户端计数，未收 `HH3C-DOT11-STATION-MIB` 逐客户端明细。
- 原生无线规则并非只缺 H3C：固定快照有 14 个可轮询 profile，覆盖 Huawei、Cisco、Aruba、Extreme、Ruckus、MikroTik、Ubiquiti；另有 Stellar 非可轮询、5 个仅 RF profile、1 个 YAML-only profile，115 个 profile 无上游 wireless rule。各 profile 采集粒度不同，不能据此说其他厂商所有型号都支持完整 AP/终端表。
- 回归：硬件/无线 55 passed，Grafana metrics/provider/PromQL 36 passed，`git diff --check` 通过。浏览器逐面板渲染没有取得认证成功证据；VM 指标和 provisioned dashboard 文件已核对。固定 LibreNMS 文件手工复核入口为 `backend/vendor/librenms/source-manifest.json`。
- 计划与执行记录：`docs/plans/plan_20261009_1102_01_多厂商无线采集恢复.md`、`docs/walkthrough/walkthrough_20261009_1102_01_多厂商无线采集恢复.md`。旧 SNMP walkthrough 已加历史结论提示。

## 2026-10-09 无线 LibreNMS 规则覆盖与 v8 发布续记

- 用户追问所有无线 LibreNMS 规则是否适配；固定快照有 20 个 dispatcher rule key，Python 适配和来源校验为 20/20。H3C/Comware 是单独标注的项目 Python MIB adapter。当前 23 个 vendor 桶里 9 个有上游无线 OS rule；另外 13 个桶在该固定 commit 没有无线 OS rule，不能以 MIB 文件名推断有规则。Ruckus 的 ZD、Hotzone、SZ、Unleashed 都在 20 个 key 中。
- Stellar 有 LibreNMS `pollWirelessClients()` 自定义 walk；Python 已适配 `apClientWlanService` 和每 SSID/总数聚合。修正了 README 里“空 OID 意味着不轮询”的旧描述。
- 本轮定向回归无线/adapter/probe/poller 82 passed，来源策略/bundle manifest 23 passed；临时镜像里 21 项含来源元数据的规则（20 upstream + H3C）均验证通过。线上 v8 healthy、restart count 0，采集版本 `nexora-librenms-rules-hardware-v8`；9/9 设备、602 活动传感器、72 capability、render_errors=0。AC_11 的 AP 6/6、controller 2/2、radio 44/44 success；F1090-9/-10 无该无线数据，Cisco 设备无线 radio 为 unsupported。
- Docker Hub 不可达导致远端 Dockerfile build 拉基础镜像失败。已从留存的 v4 生产镜像制作离线增量 v8，原启动配置/Compose 环境注入保留。回滚镜像：`nexora-netops:rollback-wireless-v8-20261009`；源码备份：`/data/nexora-automation/artifacts/codex-wireless-v8-20261009/predeploy-source.tar.gz`。数据库和其他采集/Grafana 容器未重启或修改。
- 生产现场只有 Cisco 与 H3C，可完成真实设备验收；其他 vendor profiles（包括 Ruckus）有代码级测试与固定来源校验，但仍需对应型号设备作端到端 SNMP 验收。当前工作入口与详细记录仍是上述配对 plan/walkthrough。

## 2026-10-10 SNMP 诊断系统信息与拓扑 LLDP 完整读取

- `/monitor/snmp-walk` 恢复固定 MIB-2 系统信息与 LLDP 邻居视图；新增只接收 `device_id` 的授权诊断接口，不重新开放任意 OID。
- LLDP collector 支持 `max_rows=None`；诊断与拓扑采集都显式无行数截断。拓扑过去每个 MIB 列最多 10,000 行。`/monitor/topology` 的 links/graph 页面过去固定请求 5,000 行，服务端缺省同样为 5,000、最大 20,000；当前缺省请求返回完整授权图，其他调用显式传 `limit` 仍保留兼容上限 20,000。
- 超时核查：每 LLDP 列 walk 30 秒，9 列并发；UDP transport 1 秒、最多重试 2 次；全局 SNMP 并发默认 30，拓扑每批设备并发默认 6。单设备拓扑任务默认 300 秒，可配置 30–3600 秒；没有整轮 wall-clock deadline。walk semaphore 排队时间不计入单列 30 秒，但会被单设备外层 deadline 覆盖。超时仍返回 partial/failed 或触发既有 SSH fallback，不冒充完整快照。
- 变更涉及 `backend/api/devices.py`、`backend/services/snmp_service.py`、`backend/services/topology_service.py`、`backend/api/topology.py`、`backend/services/topology_graph_service.py`、`src/components/SnmpMib/components/LiveWalkInspector.tsx`、`src/pages/SnmpWalkPage.tsx`、`src/hooks/useTopology.ts`；计划/执行记录为 `docs/plans/plan_20261010_0807_01_SNMP诊断恢复系统与LLDP.md`、`docs/walkthrough/walkthrough_20261010_0807_01_SNMP诊断恢复系统与LLDP.md`。
- 验证：`npm run lint`、`npm run build`、5 个后端模块 `py_compile`、PostgreSQL-only policy scan（0 violations）、`git diff --check` 均通过；未运行测试、未部署。build wrapper 忽略 `--outDir` 并写入 `dist/`，其受跟踪的 `dist/index.html` 已恢复至任务开始时的干净状态。
- 现场浏览器未验证：目标 HTTPS 页面返回 `ERR_CERT_AUTHORITY_INVALID`，未绕过证书提示；部署后仍需确认真实 LLDP 邻居是否完整。无行数上限会增加超大拓扑的响应与渲染开销。

## 2026-10-10 SNMP 诊断结果易读化与运行时间修正

- 用户截图显示同一设备运行时间摘要为 `0d 0h 0m`，详情却是 `1:51:45.880000`。根因是后端把所有以数字开头的字符串都当作 TimeTicks，误把小时字段的 `1` 当成 tick 数；现在识别 TimeTicks 与 `days, H:MM:SS.fraction` 两种格式，并向诊断响应增加可选 `uptime_seconds`。摘要和高级详情统一显示，例如“1小时51分45秒”，原始 SNMP 值保留在展开项。
- `/monitor/snmp-walk` 增加三步只读操作提示；系统/LLDP 状态先以中文说明、邻居数及精简字段呈现，完整系统字段、邻居平台/长描述和诊断原文按需展开。LLDP 邻居直接遍历服务端完整结果，无切片、分页或新增行数上限。
- 变更文件：`backend/services/snmp_service.py`、`backend/api/devices.py`、`src/components/SnmpMib/components/LiveWalkInspector.tsx`、`src/pages/SnmpWalkPage.tsx`；记录位于 `docs/plans/plan_20261010_0831_01_SNMP诊断结果易读化.md` 与 `docs/walkthrough/walkthrough_20261010_0831_01_SNMP诊断结果易读化.md`。
- 验证：`python -m py_compile backend/api/devices.py backend/services/snmp_service.py`、`npm run lint`、`npm run build`、`git diff --check` 通过。构建生成的跟踪文件 `dist/index.html` 已恢复。
- 浏览器确认 `http://192.168.56.1:5400/monitor/snmp-walk` 更新后的首屏、默认系统/LLDP 页和无设备空态。页面未选择设备，所以没有发起真实 SNMP 查询；设备结果布局通过源码、类型检查和构建确认，待用户选定设备后可再现场核对。

## 2026-10-10 IPAM 网段与地址池合并

- 目标：地址池作为网段子级分配范围管理；用户确认隐藏 DHCP 租约导航入口、保留现有数据和 API，不将无权威来源的人工租约纳入 IP 库存与利用率。
- 分工：后端执行者负责 `backend/api/ipam.py` 与 `backend/services/ipam_service.py` 的地址池过滤/范围校验；前端执行者负责地址池嵌入网段界面和导航入口；主 Agent 统一负责范围收敛、回退 DHCP 联动字段、文档和最终审查。
- 已完成：网段行提供地址池弹窗；地址池查询按 `prefix_id` 过滤，创建表单固定当前网段；校验地址族、CIDR 边界、起止顺序与重叠。隐藏独立地址池和 DHCP 菜单，旧页面兼容分支、租约数据及 `/api/ipam/leases` CRUD API 保留。移除了临时尝试的租约网段/地址池关联、迁移和库存联动。
- 静态验证：后端 `py_compile` 与 `git diff --check` 通过；源码检索确认 DHCP 页面不再发送 `prefix_id`/`pool_id`，租约 API 路由保留。未运行 pytest、lint、构建或浏览器验证。
- 计划/走查：`docs/plans/plan_20261010_1509_01_IPAM网段与地址池合并.md`、`docs/walkthrough/walkthrough_20261010_1509_01_IPAM网段与地址池合并.md`。
- 未完成事项：无。没有执行提交、推送、部署或数据库迁移。

## 2026-10-10 IPAM 页面布局自适应

- 目标：修复用户截图中的 IP 定位 ARP 表和 IP 地址列表在不同视口下的拉伸、横向挤压及徽标逐字换行。
- 分工：前端 Agent A 仅修改 `src/pages/IPLocatorPage.tsx`；前端 Agent B 仅修改 `src/pages/IPVlan/IPAddressTab.tsx`；主 Agent 维护 `src/pages/IPAMManagementTab.tsx` 公共宽度约束，统一审查并更新计划/走查。
- 已完成：ARP 工具栏/分页固定在结果卡外，结果区独立滚动并设置可读列宽；IP 地址筛选器按响应式网格换行，表格固定 14 列及约 1613px 最小宽度，资产编号/序列号合并展示，徽标保持单行、长内容可悬停查看。接口和数据行为未改。
- 验证：两个执行者及主 Agent 的 `git diff --check` 均通过；未运行测试、lint、构建或浏览器。窄屏运行时布局未验证。
- 计划/走查：`docs/plans/plan_20261010_1551_01_IPAM页面布局自适应.md`、`docs/walkthrough/walkthrough_20261010_1551_01_IPAM页面布局自适应.md`。
- 未提交、推送或部署。

## 2026-10-10 IPAM 网段创建与分配简化

- 目标：处理接口候选超过数千项时难以浏览、新增网段表单字段太多且输入 CIDR 时闪屏，以及 IP 分配/地址池流程复杂的问题。
- 执行范围：后端工作者负责 `backend/api/ipam.py`、`backend/services/ipam_service.py`；前端工作者负责 `src/pages/IPVlan/PrefixManagementTab.tsx`；主 Agent 负责 `src/pages/IPVlan/IPAddressTab.tsx`、`src/pages/IPVlan/IPPoolTab.tsx`、计划/走查/handoff 和集成审查。保留工作区此前已有的其他修改。
- 已完成：接口候选响应分页（默认25，服务端上限100）、状态筛选及全局摘要；显式 `candidate_ids` 与 `all_pending:true` 二选一，拒绝空选择；默认列待创建项，可确认全量待创建或逐页挑选。已存在项可以显式选择以补登记接口 IP。生成仍按精确 CIDR + 租户/站点/VRF 处理，不汇总相邻网段。
- 已完成：新增网段表单收敛为 CIDR、网络用途、名称、网关 IP、网关设备等常用字段；名称/网关含义明确，父网段推荐与 IP 规划改为按需展开，高级字段折叠，表单高度固定并使用淡入。移除会随输入自动插入的大块规划器，修复内容跳动。网关接口字段需要数据库 ID，因此不再接受接口名自由文本，新建留空、编辑保留已有 ID。
- 已完成：IP 分配的设备、接口、MAC、角色、状态、到期时间、描述折叠；地址池使用当前网段上下文并继承租户，说明其仅记录范围与利用率而非 DHCP 下发/手工分配限制；保存后的列表刷新不清空已展示数据。首次加载只有成功后才视为已加载，失败重试仍显示初始加载状态。
- 静态验证：检索全仓接口候选 API 调用仅发现上述前端调用方；请求参数/响应字段与后端契约核对一致；`git diff --check -- backend/api/ipam.py backend/services/ipam_service.py src/pages/IPVlan/PrefixManagementTab.tsx src/pages/IPVlan/IPAddressTab.tsx src/pages/IPVlan/IPPoolTab.tsx` 通过。未运行测试、lint、构建或浏览器验证。
- 已知限制：候选分页仍需在后端扫描全量接口以计算摘要；全部待创建生成仍是同步单事务，大规模批次可能触发 API/代理超时。需根据实际设备规模评估后台任务与进度接口，当前未引入调度器。
- 计划/走查：`docs/plans/plan_20261010_1642_01_IPAM网段创建与分配简化.md`、`docs/walkthrough/walkthrough_20261010_1642_01_IPAM网段创建与分配简化.md`。未提交、推送、部署或改动数据库。

## 2026-10-10 IPAM 运行页面精简、ARP 周期采集与 NSOT 协议评估

- ARP 表筛选框/按钮改用公共控件；IP 对账重复说明已精简；利用率页 KPI、Top 5 和站点卡片已整理，无历史趋势时不再留大块空白。
- APScheduler 新增 ARP 周期扫描，默认 10 分钟（最小 5 分钟）；复用现有 sweep 状态记录，不新增任务表。采集入口使用 `scheduler_locks` 租约互斥，手动触发冲突会返回清晰提示。
- NSOT 代码核对结论（后续改造前）：系统为混合协议；ARP/LLDP 已有 SNMP 路径，接口有 IF-MIB 快照，MAC/FDB、路由和动态路由邻居仍以 CLI 为主。该结论是当时的状态，后由下方 SNMP 优先改造更新。
- SNMP 可覆盖多类事实，但依赖设备 MIB 和字段完整度；MIB 标准参考 RFC 2863、4292、4363、4273、4750。后续宜按数据域影子比对迁移，保留 CLI 回退，尤其逐厂商核验 BGP/VRF。
- 修改文件还包括 `backend/main.py`、`backend/services/ip_locator_service.py`、`backend/api/ip_locator.py`、`src/components/ui/IconInputField.tsx`、`src/pages/IPLocatorPage.tsx`、`src/pages/IPVlan/IPReconciliationTab.tsx`、`src/pages/IPVlan/IPUtilizationTab.tsx`。配套文档：`docs/plans/plan_20261010_1706_01_IPAM运行页面精简.md`、`docs/walkthrough/walkthrough_20261010_1706_01_IPAM运行页面精简.md`。
- 验证仅做静态审查和 `git diff --check`；未运行测试、构建、浏览器验证，未部署或推送。

## 2026-10-10 NSOT SNMP 优先采集与 LibreNMS 事实核对

- 标准 SNMP 采集 helper 已加入完整 Q-BRIDGE FDB、IP-FORWARD IPv4/IPv6 路由、BGP4、OSPFv2/v3、ISIS 表采集；多列 walk 需覆盖同一完整索引集合，缺字段/解码/映射失败才回退，不截断行数。
- 活跃端点 MAC/FDB 路径先用 Q-BRIDGE-MIB，映射失败回退 CLI；ARP 继续走 IP-MIB。`poll_endpoints_job` 仍是缓存投影步骤，旧设备采集代码在其提前返回后不可达，不将它描述为本轮新增的活动采集器。
- 路由采集默认表先读 IP-FORWARD-MIB；已知非默认 VRF 沿用按范围 CLI 补采，新 VRF 或 SNMP 默认表失败时仍可走原 CLI 路径。动态路由邻居按协议先 SNMP；只为失败协议执行 CLI。统一 NSOT 不再硬编码禁用 EIGRP/RIP：RIPv2 先读 RIPv2-MIB，可选 peer 表不可用或空时回退；Cisco 平台先读 CISCO-EIGRP-MIB，其他平台直接走 CLI。BGP 的 local AS 与建立时间字段写入现有邻居记录。完整 BGP RIB 仍走 CLI/TextFSM，因当前 SNMP 实现不能证明 IPv6、VRF 和厂商 weight 的覆盖完整。
- 追加采集结果完整性修正：ARP SNMP 与 MAC/FDB 记录要求全部可归一化；CLI/TextFSM 未匹配、空结果或部分坏行不再报告成功。FDB 仅替换完整成功设备的快照，失败设备保留旧记录；任一目标交换机 FDB 不完整时暂停终端位置重算。路由、BGP RIB 和 CLI 动态邻居仅在非空且所有结果行都有效时更新快照；不可证明的空表不会清除旧数据。SNMP 动态邻居 helper 明确报告完整空表时仍接受空快照。
- 接口采集已分别使用 IF-MIB、IP-MIB、Q-BRIDGE-MIB 读取状态/描述/MAC/MTU/速率、地址、VLAN/端口成员；按域判断完整度，只有缺失域才调用 CLI fallback。统一 NSOT 流程关闭 `sync_topology_and_interfaces_job` 的旧接口 CLI 阶段，避免随后 `collect_interface_status_for_online_devices` 再采一次。接口字段服务的 MAC/MTU 没有专属 CLI category，不完整时保留原值；IP 地址 fallback 可能连带读取状态，但仍保留 IF-MIB 状态。
- LibreNMS 资料核实：FDB 有当前表、创建/更新时间和周期清理，不是完整 MAC 移动事件轨迹；路由有历史保留但只按 discovery 周期更新，默认 1000 超限时通用 MIB 分支记录并跳过，非截取前 1000 条，OS 专用 `RouteDiscovery` 可能绕过通用分支；上游已有通用 ISIS-MIB 邻居发现/轮询。BGP Up/Down/Flap 日志依赖 polling 检测状态变化；`/api/v0/bgp` peer 记录与 `/api/v0/routing/bgp/cbgp` AFI/SAFI 前缀计数是不同数据集，前缀数不是基础 peer 通用字段。`discovery-protocols` 的 OSPF/OSPFv3 自动发现不等于邻居状态表采集。
- 验证：对 `snmp_service.py`、`interface_collection_service.py`、`ip_locator_service.py`、`scheduler_service.py`、`collection_plan_service.py`、`nsot_collection_preview_service.py`、`topology_service.py` 做 Python AST 静态解析，并对本任务改动执行 `git diff --check`；未运行测试、构建、设备采集或部署。
- 配套计划/走查：`docs/plans/plan_20261010_1734_01_SNMP优先NSOT采集与CLI回退.md`、`docs/walkthrough/walkthrough_20261010_1734_01_SNMP优先NSOT采集与CLI回退.md`。
- 追加拓扑 LAG 首采：无论 LLDP 使用 SNMP 或 SSH，聚合关系都独立先用 IEEE8023-LAG-MIB `dot3adAggPortAttachedAggID`，通过 IF-MIB 映射 member/aggregator 接口。取消 4096 行上限，支持 SNMPv3 profile，整 walk 超时 30 秒；不完整或不支持时才启动该域的 `eth_trunk` CLI/TextFSM。完整 IF-MIB 能证实无聚合时接受空快照；两个来源无有效结果或 CLI 未匹配时保留旧关系。未做真实设备验证。

## 2026-10-10 CMDB 设备骨架、VLAN 可读性与运行日志排查

- `/cmdb/devices` 仅返回网络设备骨架；`/cmdb/vlans` 默认不展开行，摘要表保留 9 个主要字段，操作列详情图标打开完整信息，顶部摘要收敛为 3 项。保留筛选、分页、导出、编辑/删除及详情数据。
- VLAN 当前页设备数对 device ID/hostname 去重。详情操作使用共享 action icon/table cell 组件。
- Windows SSH 告警来源已定位：`device_telemetry_sampler` 每分钟调用 `record_device_telemetry_snapshot()`，Linux 脚本 `insp_linux_full` 的选择条件错误地将任意 `device_category` 含 `server` 的在线设备加入采集；`_execute_shell_script()` 仅用 `management_port`/`port`，空值默认 22，不路由 WinRM。当前只完成定位，未改该任务。
- IP 定位失效日志来自 `ip_locator_cache_invalidation`（每 2 秒轮询 PG outbox）无法连 Redis 的重试。用户确认本机未配置 Redis；代码默认 `REDIS_URL=redis://localhost:6379/0` 和 Redis backend，因此仍会尝试本机 6379。多个近邻 warning 是多个 outbox event，不代表多次设备路径追踪。建议部署配置显式将 locator cache backend 设为 disabled 或配置 Redis；本轮未更改默认值。
- 验证：`git diff --check`、CMDB Python 编译、`npm run lint` 和隔离目录 Vite 生产构建均通过。浏览器当前未登录，未做页面视觉复核。未运行测试、未部署、未提交或推送。
- 配套计划/走查：`docs/plans/plan_20261010_2030_01_CMDB设备骨架与VLAN可读性.md`、`docs/walkthrough/walkthrough_20261010_2030_01_CMDB设备骨架与VLAN可读性.md`。

## 2026-10-12 告警隔离压测续记

- 目标：在用户授权的 Docker 验证 VM 上安全执行 500/1000/5000 合成告警队列压测；此前告警页 GET 2.34 秒中约 2.32 秒为默认 executor 认证等待，独立有界认证池后约 27 毫秒；整体 CPU 归因仍需要联合压力证据。
- 主 Agent 完成 `scripts/docker_capacity` 的 alert-storm 专用 seed、告警 API 读取、隔离 Redis/Celery/Relay、资源限额及宿主 CPU 门槛。告警直接写入隔离测试 DB，不调用规则计算或外部通知；workspace task succeeded 只代表禁用通知后的安全收敛。
- `/root/review_stress_harness` 做了只读审查并指出 runner 编排缺失、事件前缀不匹配、activity schema 不符、CPU 参数未传递及 Broker 密码被多余传给 runner；主 Agent 均已处理，执行者未改文件、未连接 VM。
- 本地验证：17 个 metrics 测试、45 个 runner/main 测试通过；compileall、PostgreSQL-only（0 violations）、alert dry-run 和 `git diff --check` 通过。详细记录：`docs/plans/plan_20261012_1611_01_告警隔离压测.md`、`docs/walkthrough/walkthrough_20261012_1611_01_告警隔离压测.md`。
- 已登录用户授权的 VM 并完成只读基线检查。30 秒预检宿主 CPU 峰值 81.02%，NetOps 83.27%、PostgreSQL 48.97%；两次后续预检都在任何克隆容器创建前安全退出，run 标签资源清理完整。没有向生产 DB 写入合成数据或发送通知。
- 当前有 788 条告警、744 条未恢复、744 个活动 incident。788 行告警 count 执行 0.379ms，20 行列表执行 0.042ms；此查询当前不是 CPU 峰值来源。Outbox 1625 行中 Email/Feishu 各 802 行失败、workspace 21 行成功、pending/processing 为 0；失败正文尚未查看。
- 高基线竞争路径：每分钟 `/hardware-metrics` 处理约 3902 个传感器行并返回约 7.5MB（1.28–2.44s）；ARP Sweep 对 10 台设备收集 62 项用时 2.1–2.4s，峰值样本与扫描重合；IP Locator invalidation/run worker 有 max-instances 跳过。PostgreSQL 累计统计中 SNMP 硬件传感器读写高于 incident 查询。告警通知 Worker 基本空闲；共享 2CPU PostgreSQL 仍构成告警资源隔离缺口。
- 由于 6 秒预检只收到 2 个样本，alert-storm CLI 最短基线改为 10 秒；`test_main` 25 项和 Python 编译通过。必须先降低已有 CPU 基线到连续 30 秒峰值 <30%，再运行 500 条 30 秒 pilot，然后才跑 1000/5000 档。计划与完整实测证据见 `docs/plans/plan_20261012_1611_01_告警隔离压测.md` 和 `docs/walkthrough/walkthrough_20261012_1611_01_告警隔离压测.md`。

## 2026-10-12 告警压测基线整改

- 用户更正验证 VM 地址为 `192.168.204.128`；主机仍为 2 vCPU/7.7 GiB。已从 `/hardware-metrics` 阶段日志确认 3902 行/约 7.59 MB 的读取和渲染耗时为 1.27–3.89 秒。传感器分布中 378 个 voltage、378 个 current、12 个通用 sensor_value 行不会被导出；10 台设备 ARP sweep 用 5 并发收集 62 项耗时 2.1–2.4 秒，并与一次 CPU 峰值时间重合。告警总数/分页 SQL 当前分别为 0.379/0.042 ms，通知 Worker 基本空闲，不能把高 CPU 归因到告警通知 Celery。
- 本地整改：硬件指标 SQL 复用渲染器排除集合过滤 768 个无输出行；新鲜 sensor 行不再逐条复制；完整 ARP sweep 使用独立默认并发 cap=2（环境变量上限8），实时定位并发保持不变。Locator invalidation outbox 查询无待处理记录，因此只记录其 max-instances 警告，不猜测性限频。
- 验证：指标导出、PostgreSQL fixture 输出等价、ARP 合同测试合计 72 项通过；目标文件 `py_compile` 通过；PostgreSQL-only scanner 0 violations；`git diff --check` 通过。alert-storm 500 条 pilot 仍被宿主 CPU >30% 门槛阻止，尚未建立 CPU 基线整改后数据。
- 当前浏览器只读检查通过：告警台 744 条待处理、75 页；资产设备 221，网络设备 219（204 离线），服务器2在线；资产与配置相关页面已加载，仪表盘重新登录后显示 221 台、17 台在线及资源摘要。未触发任何采集/诊断、备份或配置下发。
- 用户已明确授权部署并测试。硬件过滤/ARP 并发已通过只覆盖后端的叠加镜像部署；设备健康 N+1 接口读取也改为批量并部署，PostgreSQL 等价/查询数测试通过（模块 3 passed）。当前运行 `nexora-netops:alert-health-batch-202610120952` 的镜像内容，仅 netops 重建；回滚标签保留。整改后三次基线峰值64.49/33.60/71.39%，均未创建压测资源，500 pilot未运行；不能声称整体CPU改善或卡顿已解决。
- 慢调度计时本地9测试通过，仍未部署。全量回归原句柄和OS进程已消失、无最终结果，已重新运行并持久化 `logs/alert-backend-full-regression-20261012.log`。继续采集主进程调用栈及硬件导出热点；共享PG资源边界、ARP全周期及资产配置高负载响应仍需验证。
- 续查py-spy捕获主事件循环硬件发现反复扫描MIB清单。Luna仅修改source_policy及其测试，对精准upstream使用现有签名索引、不缓存trust布尔；21项来源测试通过、40次2,360条清单查询等价，本地2.56s→0.042s。`nexora-netops:mib-index-20261012`仅覆盖这一文件并重建netops，镜像健康且运行文件哈希一致，回滚标签保留。慢调度计时未部署，全量pytest仍运行。修正Bearer Token后的160次低频API请求全200，告警/资产/设备/模板p95约94/432/505/127ms；未作为告警风暴验收。
- 最新30秒预检仍因宿主52.13%峰值中止，未创建测试资源。随后60秒/30样本全进程容器采样host均值25.29%/p9565.79%/max72.05%；NetOps mean/max14.10/77.82%，PG5.03/32.11，SeaweedFS7.22/12.56，Grafana2.95/21.74，SNMP exporter3.93/11.75；告警两个Celery worker均值0.06/0.08，峰值0.49%。当前预检尖峰由多个服务任务交叠；告警Worker不是本次高基线主耗。证据/脚本见 walkthrough 与 `logs/nexora-all-process-cpu-20261012.json`。全量pytest session仍活跃，约23%，无失败输出，不能标通过。
- 新 Locator 续查：最近10分钟 `max_instances` skip分别为 invalidations28次、runs12次；4张队列表按状态聚合为空，20秒PG活动查询每半秒采样结果为空。30秒py-spy对默认executor的 `claim_locator_invalidation` PG SELECT仅捕获1次。不能断言其在数据库慢/锁等待；应让 scheduler lock phase timings 测量当前实现后判断。主机 `/proc/pressure/cpu` some avg10约7.6%、full 0，硬件指标端点0.85-2.08s/分钟且约7.59MB。全量pytest目前31%；日志 `.log` 持续记录，无失败输出，仍在同一个 live process。
- 第二个 postdeploy 60秒/30样本全host采样 host均值/p95/max 23.94/51.91/61.73%，NetOps mean/max15.16/90.13%，PG4.91/19.66%，告警normal/critical均值0.05/0.08、峰值0.49%。较上一窗口host均值/p95低，但NetOps max更高；未证明稳定降载，也不可启动alert pilot。结果在 `logs/nexora-all-process-cpu-window2-20261012.json`。全量pytest仍有活进程，进度33%。
- 移除 `/hardware-metrics` 为字节计数多做的一次7.59MB UTF-8编码，Response对象复用同一body长度并计入总耗时。8项导出测试通过、PG-only/compile/diff通过。叠加镜像 `nexora-netops:single-encode-20261012` 已部署，run0、healthy；API200/7,585,572 bytes。部署后3次处理耗时0.905/0.926/1.150s，改动前相邻3次0.851/2.077/1.513s；小样本不证明宿主CPU改善。全量pytest进度53%，1 skip，无fail，仍运行。
- 编码优化部署后3个实际样本耗时0.905/0.926/1.150s，主体字节数7,585,237–7,585,737，Content-Type未变；部署前相邻3个为0.851/2.077/1.513s，抖动仍有，不能声称稳定改善CPU。最新当前闲时 docker stats：netops0.28%、PG0.49%、告警两个worker0.06/0.04%，只是瞬时样本。全量pytest当前48%，仍同一活跃进程，无失败输出。
- 单次编码优化后预检run0eba62e5d21e464d91aa03d816151955仍因host47.55%而安全拦截，cleanup complete且run标签资源为空；隔离报告在本机 `logs/nexora-alert-run-postencode-20261012-report.json`，未运行500pilot。post编码窗口3/4 host mean17.14/16.98、p95 37.18/35.56、peak47.87/51.26，NetOps mean7.05/7.17、peak36.37/40.67；旧window2为host mean23.94/p95 51.91/NetOps peak90.13。时段负载不同，不能据此因果归功于编码优化。最新backend全量pytest仍活跃，67%、1skip、无fail。

## 2026-10-12 告警隔离最新状态

- 后端全量 pytest 已结束：3655 passed、1 skipped、26 subtests passed、30 failed（6372.38秒）。输出见 `logs/alert-backend-full-regression-20261012.log`。失败分布在资产/变更单/凭据/拓扑等测试；其中 rack health scope 的过期 mock 已改为批量读取接口并聚焦验证。全量结果早于最近的告警状态 upsert 改动，不能标为通过。
- 告警状态 upsert 本地改为最多100行一条多值 SQL；500行测试验证分5个事务写状态，并与事件、活动、outbox保持原子性。告警状态批次及 outbox 原子性聚焦测试6 passed。该补丁尚未部署，2.86/5.54秒两轮计时差异说明本机噪声较大，未证明CPU改善。
- 最新30秒安全预检宿主CPU峰值71.50%（15个样本），高于pilot启动门槛30%；NetOps峰值51.45%、PostgreSQL30.68%，Alert normal/critical Worker只有0.20%/0.34%。预检在创建克隆容器前退出并清理；500条pilot未开始。主服务事件/规则/状态/outbox写入仍可能争用共享CPU和PostgreSQL，通知Worker配额不能隔离这些前置工作。
- 任务最新结论与证据记录于 `docs/plans/plan_20261012_1611_01_告警隔离压测.md` 和 `docs/walkthrough/walkthrough_20261012_1611_01_告警隔离压测.md`。本轮只读 `docker exec` 指纹核验被自动审批以“approval required by policy, but AskForApproval is set to Never”拒绝；没有部署最新 upsert 补丁或在VM执行pilot。
