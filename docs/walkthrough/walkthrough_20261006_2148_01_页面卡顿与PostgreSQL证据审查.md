# 页面卡顿与 PostgreSQL 证据审查

## 结论与材料范围

已完整读取用户引用的「配置Nexora Nginx」最后一轮用户 SQL 输出及回复，核对本轮附件、补充的三次 docker stats 和 docker ps，审查工作区代码。下面原始阻塞路径使用开始审查时的基线行号，之后的工作区补充修复另列；没有操作远端 Linux 主机。

已经找到确定存在的同步阻塞路径，以及两个应优先调查的数据库扫描热点。现有证据还不能证明某条 SQL 是所有页面卡顿的唯一或最大来源，也不能量化 SQL 优化后会降低多少 CPU。当前保留一个 Uvicorn worker，不提交、不 push、不部署。

## 本轮新增的关键代码证据

`backend/main.py:450` 在 FastAPI lifespan 内用 `asyncio.create_task(_bg_init())` 初始化后台任务；`_bg_init` 的 `:135` 调用 `start_loops`；`backend/engine/orchestrator.py:177-179` 用 `asyncio.create_task` 创建 A/B loop。它们在请求处理所用的 asyncio 事件循环上运行。

审查时的基线中，以下调用没有线程或 executor 边界：

- A-loop `orchestrator.py:121-124`、B-loop `:151` 同步执行 `_db_quick`。
- B-loop `:163` 同步执行 `_run_telemetry_maintenance`，包括 raw 表聚合 upsert 和多条保留期 DELETE。
- B-loop `:167` 同步清理 SSH 连接池，`:169` 同步执行 LLDP 告警查询与状态写入。

`background_monitor_service.py:331-343` 的 `_db_quick` 是同步连接获取、SQL 执行和连接归还。维护任务 `:588-636` 的聚合窗口确为最近两小时。等待这些同步调用时，事件循环不能调度其他请求，即使轻量 `/health/live` 本身不读数据库，也可能延后执行。这与此前轻量 live 请求出现秒级延迟的现象相符，但尚无维护起止时间与慢请求时间的逐条对齐，不能把每次慢请求都归因于维护。

维护周期应表述为每 12 次成功采集循环。每轮还包含设备采集、SQL、LLDP 处理与 60 秒 sleep，因此不是固定每 12 分钟运行；慢设备或异常会改变间隔。最近两小时反复聚合的重叠计算确实存在。

这次审查发现的采集循环路径在此前请求中间件、调度租约、健康接口及通知连接生命周期修复之外，后来追加了下面的局部修复。不能被描述成已消除了全部后端阻塞，更不能将尚未部署的工作区变更视作线上状态。

## 审查后的工作区补充修复

`backend/engine/orchestrator.py:121`、`:152` 已使用 `await asyncio.to_thread(_db_quick, ...)` 获取物化设备快照；`:168` 将遥测维护放入线程。设备采集协程、并发上限、轮次和每 12 次成功循环后的维护顺序保留。新门控测试 `test_telemetry_orchestrator_execution.py` 2 passed，184.15 秒，证明慢快照/维护期间事件循环可推进；测试日志见 `logs/validation/perf-telemetry-loop-20261006_2054.log`。

`:172` SSH 连接清理和 `:174` LLDP 告警仍直接运行，后者包含数据库与共享告警状态访问；未核对共享状态线程安全前，没有将其一并移动。线程隔离不会减少数据库聚合扫描量，取消协程也不会强制停止同步线程。本轮不引入增量 rollup 或索引迁移。

用户明确本机 Windows 没有 Docker 部署环境。所有线上资源结论均基于用户提供的实际 Linux 容器数据，工作区测试只是行为验证。提供 `scripts/diagnostics/collect_nexora_container_review.sh` 在真实主机采集配置、活动事务摘要、数据库统计前后快照、cgroup 和直连/代理 live 时延；默认 60 秒，无安装扩展、reset、重启或数据库写入。脚本仅通过本机 Git Bash 语法检查，真实容器执行待用户反馈。

## 对最后一轮判断的逐项核对

| 判断 | 审查结果 | 尚缺的证据或修正 |
|---|---|---|
| Nginx 资源不足 | 当前采样不支持 | CPU 0～0.01%，内存约 6.1 MiB / 256 MiB；不能据此排除代理认证等待或所有配置问题，但扩大配额缺少依据 |
| 82 万 rollback 主要来自 `_db_quick` 的 SELECT | 来源归因不足 | 只读事务归还连接可 rollback；每次 checkout 的 `SELECT 1` 后也主动 rollback，许多业务路径都会累计计数 |
| rollback 表示事务生命周期错误 | 表述过强 | `database/core.py:310-337` 已在 close 时 rollback 并归还池；事务已经结束。长期持有事务才是需查的问题，换成 commit 不等于获得性能收益 |
| raw 表有大量扫描 | 已由累计统计支持 | 8574 次 seq_scan、约 9.71 亿 seq_tup_read；这是扫描行次数，不是查询执行时间或物理磁盘读取量 |
| 两小时重算有优化空间 | 代码确认 | 应先测聚合、保留期清理及最新接口快照查询各自耗时，不能假定 raw 扫描全部来自 rollup |
| MIB 大量全表扫描来自模糊搜索 | 全表扫描证据强，调用归因未确认 | 均值约 67612 行/scan，普通 name/oid 索引扫描为零；除 `%keyword%` 搜索外，后台符号解析也使用 `LOWER(node_name)` 精确比较 |
| 直接加三个 trigram 索引 | 需要按热 SQL 选择 | 精确符号匹配可考虑 `LOWER(node_name)` 表达式索引；模糊匹配再考虑 trigram。跨表 OR、短关键字和排序仍需看执行计划 |
| pg_stat_statements 可帮助定位 | 正确 | 能统计 calls、执行时间、buffer 等，但 total_exec_time 不能直接等同 CPU 时间或计算出 PostgreSQL CPU 占比 |
| 容器运行 3 小时说明统计覆盖 3 小时 | 不成立 | PostgreSQL 正常重启可能保存累计统计；stats_reset 为 NULL 时不能据此得出精确统计窗口 |

MIB 代码补充：`snmp_hardware_probe_service.py:237-241` 在后台符号解析中使用 `LOWER(n.node_name) = LOWER(?)`，`librenms_rule_service.py:1254-1259` 也有类似比较。页面 MIB 搜索的真实过滤器在 `snmp_mib_service.py:1062-1072`。单看表级统计不能区分这些调用。

raw 表除维护之外还有设备接口快照查询：`api/devices.py:733-747` 批量查询每接口 MAX(ts) 后再连接原始表；`database/core.py:456-468` 有单设备版本。后台 `load_persisted_interface_statuses` 只在接口计数器缺少内存基线时调用，不能把它说成每次轮询都会重扫。

第二位 Luna 验证执行者补充发现 `api/capacity.py:81-103` 也聚合 raw 表最近一小时数据。因此，即便观测到 raw 扫描增量，也不能仅归到 rollup。

## 实际 Linux 容器的 22:07:37～22:08:38 采样

用户提供 `nexora-container-review-20261006_220737.log`，并明确这次没有主动测试页面卡顿。以下结论是该常态窗口的实际数据，不是 Windows 测试结果；窗口 60.952797 秒，结构化解析保存在 `logs/validation/perf-container-review-20261006_220737.json`。

| 项目 | 真实容器证据 | 结论边界 |
|---|---|---|
| 运行版本 | orchestrator/core/main 的源码 SHA256 都等于当前 HEAD，均不等于本轮修改后的工作区 | 这三个关键文件尚未采用性能补丁；不能把本机测试通过当作部署后效果 |
| worker/连接配置 | WORKERS=1、DB_POOL_SIZE=16、overflow=4、DB_POOL_MIN_SIZE 未设置 | 源码还是修复前版本，空闲池原行为未改变 |
| 后端资源限额 | 2 CPU / 2 GiB，nr_throttled 和 throttled_usec 前后不增加，OOM 与 memory max 事件均 0 | 该窗口没有后端 cgroup 限流/OOM证据；不能据此排除宿主机争用或其他窗口压力 |
| 请求耗时 | 5 次 direct live 5.0～48.3 ms，代理 live 9.413～119.592 ms，全部200；VM health 1.8～10.3 ms，Grafana health 2.2～5.0 ms | 本次没有抓到秒级 live 卡顿；这些健康路径不替代真实页面/API/PromQL延迟。直连与代理顺序执行，不能简单相减当代理开销 |
| 数据库扫描增量 | MIB 和 raw 的 seq_scan/seq_tup_read 都增加0；raw idx_scan增加460，idx_tup_fetch增加6339；1m索引统计不增加 | 之前累计热点仍成立，但这61秒没有显示它们持续全表扫描，未观测到对应 rollup 活动；不能据此否认其他时段的维护/搜索热点 |
| 事务增量 | commit +606、rollback +1699，deadlocks +0 | rollback仍只能作为正常清理或异常的混合计数，不能当1699次报错；含诊断自身少量只读事务 |
| 活动事务 | 四次采样无 active/idle-in-transaction 记录；最后一次有5.38秒 Client/ClientRead idle-in-transaction，blocking_pids为空 | 有应用持有事务等待客户端的现象，未抓到锁阻塞；尚无SQL或HTTP关联，不能指定通知为唯一调用方 |
| 临时文件 | temp_bytes +9,109,504 bytes（8.6875MiB） | 提示本窗口有查询使用数据库临时文件，不能直接归到raw/MIB或断言为最大耗时来源 |
| SQL诊断条件 | PostgreSQL18.6；shared_preload_libraries为空、compute_query_id=auto、pg_stat_statements包1.12可用但未安装；track_io_timing=off | 现在已确认模块未预加载。若后续启用，需先配置并安排数据库重启，再在目标库安装；本轮没有执行这些动作 |
| 对象存储 | STORAGE_BACKEND=s3 | SeaweedFS实际在存储链路上，不能仅以mini/低内存就排除；其S3时延和磁盘仍未采集 |

这份日志缩小了资源限额方向的疑点，没有抓到页面卡顿现场。下一轮延长采样并主动复现相关页面，记录卡顿时间与页面路径，再关联事务、维护、HTTP Handler和SQL耗时。15分钟比一分钟更有机会覆盖维护周期，但因采集耗时与异常影响，仍不能保证一定覆盖维护。

## 实际卡顿窗口的 22:11:04～22:12:06 采样

用户随后提供 `nexora-container-review-20261006_221103.log`，明确这次实际出现卡顿。窗口为61.940063秒，结构化解析保存在 `logs/validation/perf-container-review-20261006_221103.json`，由第二位Luna验证执行者独立核对。

| 指标 | 未主动测试窗口220737 | 实际卡顿窗口221103 |
|---|---:|---:|
| backend direct live | 5次均200，5.0～48.3ms | 50.9ms、1931.1ms、5007ms超时、553.3ms |
| Nginx live total | 9.413～119.592ms | 50.043～1246.393ms |
| VM/Grafana health最大耗时 | 10.3ms / 5.0ms | 10.1ms / 17.8ms |
| MIB seq_scan / seq_tup_read增量 | 0 / 0 | 13 / 878,956 |
| raw seq_scan / seq_tup_read增量 | 0 / 0 | 6 / 1,096,436 |
| raw复合索引扫描增量 | 460 | 540 |
| PG buffer读取 / 命中增量 | 4,606 / 158,803 | 54,282 / 410,733 |
| commit / rollback增量 | 606 / 1,699 | 835 / 2,740 |
| 临时文件bytes增量 | 9,109,504 | 9,109,504 |
| 后端新增quota throttling / OOM | 0 / 0 | 0 / 0 |

秒级直连live与用户报告同处卡顿窗口，已经绕过Nginx，因此Nginx自身不足以解释卡顿；更支持后端事件循环/请求执行或主机调度延迟。代码中已确认的同步阻塞是明确修复目标，但缺少具体页面、逐条请求/维护时间与SQL执行统计，不能断言某一次扫描就是5秒超时的原因。

这个窗口确有MIB/raw序列扫描增加，MIB增量恰等于13×67,612估算行数，是整表读取的强证据。1m表索引统计不增加，无法将raw的6次扫描认定为rollup。`blks_read`增加包含经操作系统缓存的块读取，不是物理磁盘读取时间；未启用track_io_timing不能计算I/O等待。两段临时文件增量相同，也不能用它单独解释卡顿。

22:11:37.7只抓到一个ClientRead idle-in-transaction，事务龄1.80秒、无blocking PID，不是正在执行1.8秒SQL或锁等待。四次稀疏快照没有捕获active SQL，语句级归因仍缺证据。两个日志的镜像ID、启动时间、配置、源码哈希相同，均未运行工作区性能补丁。

用户后续授权为每个容器配置资源上限，并将Nginx worker设为1；这是运行时保护和配置整理，不能代替同步阻塞修复。见 `walkthrough_20261006_2223_01_Docker资源配额与Nginx进程.md`；未部署。

## 九项判断的独立复核补充

第二位 Luna 验证执行者独立读取统计与代码，确认：Nginx/Redis/VM“无性能问题”均应改为“采样中资源占用低”；SeaweedFS是否延后排查取决于业务调用，不能依据PIDS估计组件数；MIB整表读取证据强；raw只在已提供的表统计中累计读取最多，未证明耗时最多；两小时窗口重算成立，12分钟是近似而非固定调度；rollback来源比例未知；SQL诊断值得使用，但现有模块可复用而非从零实现。

项目已有 `backend/ai/api/usage.py:136-142` 的权限保护接口 `GET /api/ai/metrics`，在 `backend/ai/services/database_observability.py:100-166` 可选读取当前数据库的 Top20 pg_stat_statements，扩展不可用时退回当前 active pg_stat_activity。查询只返回queryid/calls/time/buffers，不返回SQL正文。关系/cache统计只观察五张AI allowlist表，平台首页健康接口尚未呈现全平台SQL诊断；既不能说项目完全没有这个能力，也不能说当前已有完整的平台慢SQL历史监控。

## 补充资源数据的解释

三次快照中 NetOps CPU 为 47.08%、93.48%、52.50%，内存约 659～706 MiB / 2 GiB；PostgreSQL CPU 为 44.59%、6.14%、15.33%，内存约 166～168 MiB。Nginx、Grafana 和 VictoriaMetrics 在这些采样点没有明显 CPU/内存限额压力。容器 healthy 说明健康检查通过，不等于页面响应快速。

后台 CPU 高而 PostgreSQL 同时只有 6.14% 的快照说明需要同时检查 Python 采集解析、序列化及事件循环上的计算；只处理数据库索引不足以解释所有现象。三个瞬时采样不能替代完整时间序列，不能证明宿主机 CPU 持续饱和或完全空闲。

`PIDS` 包含 Linux 线程，NetOps 的 13～26 不能被解读为 Uvicorn worker 数。显示约 7.709 GiB 的容器没有从这一列体现出更小的内存硬上限；这不是每个容器已占用或已预留 7.709 GiB。

## 优先排查与优化顺序

1. 优先隔离采集循环的同步 I/O：数据库读写和遥测维护应通过受控线程执行，保持采集顺序与单实例约束。涉及共享告警状态或 SSH 池的逻辑要先核对线程安全，不能把整段异步采集粗略搬进线程。
2. 增加采集、维护、LLDP 与事件循环 lag 的耗时记录，与 HTTP Handler 慢请求时间对齐，明确哪些阻塞与页面停顿同时发生。
3. 获取固定采样窗口的 SQL 统计增量，分别按总耗时、最大耗时及调用次数查看；对确认的热 SQL 看执行计划，区分 rollup、DELETE、最新快照和 MIB 符号解析。
4. 采用增量 rollup 前明确迟到样本和重启补算规则。水位只能在聚合成功后推进，按完整分钟边界重算，不能简单缩短窗口后丢失迟到数据或停机期间样本。
5. 根据真实 MIB 热 SQL 选择缓存、精确表达式索引或模糊搜索索引，再比较耗时与扫描增量。

先前附件只证明 `netops` 数据库尚未安装 pg_stat_statements 扩展；新增真实容器日志进一步确认 shared_preload_libraries为空。启用需要配置预加载和数据库重启窗口，不能只运行 CREATE EXTENSION，也不应无依据强制重建数据卷。采样可比较两个快照的差值，不需要先清空累计统计。

## 官方依据

- [PostgreSQL 累计统计](https://www.postgresql.org/docs/current/monitoring-stats.html)：扫描计数、估计行数、统计在正常重启时的保留及缓存 I/O 的解释。
- [pg_stat_statements](https://www.postgresql.org/docs/17/pgstatstatements.html)：加载条件、目标数据库扩展安装、SQL 执行耗时和调用统计。
- [Psycopg 事务](https://www.psycopg.org/docs/usage.html#transactions-control)：SELECT 可开启事务，需及时结束。
- [pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html)：支持模糊模式索引，短模式或无可提取 trigram 的模式存在限制。
- [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/)：PIDS 包含线程，内存列与 I/O 列的含义。
- [asyncio.to_thread](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)：同步阻塞 I/O 的线程执行及 Python GIL 的边界。

审查由主 Agent 集成，Luna 后端执行者独立核对 lifespan/A/B 事件循环链路、实际周期及事务归还行为；随后同一执行者按独立文件边界完成采集循环补充修复。用户要求截图逐项确认后，第二位 Luna 验证执行者完成九项独立复核并审阅只读采集脚本；原始详细矩阵保留在本次对话的子Agent结果。实际容器数据由用户执行命令后提供，未由 Agent 操作远端配置或部署。
