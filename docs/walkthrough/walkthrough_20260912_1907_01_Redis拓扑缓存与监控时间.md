# Redis 拓扑缓存与监控时间格式 — 走查记录

## 完成摘要

- 只读追踪了 `/monitor/topology`、LLDP 写库、拓扑页面读取及 IP Locator 邻居缓存路径。
- 为 `redis-logs` 增加 Docker stdout/stderr 时间戳；新增一个从 stdin 格式化 Redis `MONITOR` epoch 的工具。未改 Redis sidecar 配置、ACL 权限、拓扑缓存行为或设备采集流程。
- 按代码默认配置，拓扑链路证据 freshness 为 48 小时；定位器使用拓扑边的默认 freshness 却为 10 分钟。调度默认也不是 48 小时：迁移创建的统一 NSOT 任务为每日 02:00，部署运维可以自行修改。图页/locator 和周期采集目前没有共享一份完整 LLDP Redis 快照。

## 实际修改文件

- `scripts/format_redis_monitor.py`
- `scripts/deploy-docker.sh`
- `backend/tests/release/test_deploy_docker_redis_contract.py`
- `backend/tests/release/test_redis_monitor_formatter.py`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260912_1907_01_Redis拓扑缓存与监控时间.md`
- `docs/walkthrough/walkthrough_20260912_1907_01_Redis拓扑缓存与监控时间.md`

## 拓扑/LLDP 代码审计结论

1. 周期采集已将规范化 LLDP observations 写入 PostgreSQL `topology_observations`；`topology_links` 与拓扑 evidence graph 是派生读模型。成功完整扫描会将缺失观察标为 stale；失败采集不会清空旧事实。PostgreSQL 应继续作为事实权威。
2. `/api/topology/links` 与站点摘要用 `core.read_cache` 的进程内 10 秒 TTL，不是 Redis。拓扑收集流程没有对 locator Redis key 预热；IP Locator 自己的 Redis snapshot 使用 locator scope 和 observation dependency metadata。
3. IP Locator 的 `_topology_neighbors` 默认拒绝超过 600 秒的链路，尽管 topology 默认 evidence TTL 是 172800 秒。找不到新鲜拓扑边后，locator 再查询它自己的 Redis/PG neighbor snapshot；若无可用快照才回源到 `legacy._collect_lldp_from_device`。因此出现 H3C `display lldp neighbor-information list` 与其他阶段命中 Redis 可以同时成立。
4. 当前代码默认 NSOT 每日任务负责统一的拓扑/接口采集；`TOPOLOGY_AUTOMATIC_INTERVAL_SECONDS` 默认 86400 秒，实际在 `main.py` 注册为 prefix-discovery job，generation-status 输出的 topology 自动 job 元数据可能与实际 operator-visible NSOT 任务不一致。最终以部署数据库中的已批准 scheduled job 为准。

## Redis 数据建议

| 优先级 | 数据 | 建议与边界 |
| --- | --- | --- |
| 1 | 每台设备完整 LLDP 邻居快照 | 正规化字段、设备/站点作用域、采集时间、run/generation、平台/命令/parser/schema 版本、`complete` 状态；完整成功的零邻居也写明确 negative snapshot，失败/截断/不支持不得写空值。TTL 应与部署实际 cadence 对齐；48 小时周期至少 freshness 48 小时并留刷新抖动，物理保留期可以更长但不得把过期事实当新鲜。 |
| 2 | 接口与 LAG inventory | 描述、规范接口名、聚合成员关系相对稳定，可以用 24–48 小时类 TTL；admin/oper 状态更易变化，应单独用短 TTL（约 5–15 分钟），不能将两类 freshness 合并。 |
| 3 | 图页/站点拓扑响应投影 | 可按 tenant/site/view/filter/topology generation 缓存，优先 generation 驱动失效或 30–60 秒短 TTL；用户个性布局要按 user 隔离或不进入共享缓存。 |
| 4 | 低频 CMDB/IPAM 映射 | Prefix、VLAN、站点摘要等可按租户/站点作用域短期缓存；频率低，优先评估 DB 成本后再加，避免缓存 invalidation 复杂度大于收益。 |

路由/ARP/MAC/子网/完整结果目前已经有 Redis read-through 策略。不要将凭据、原始 CLI 输出、任务租约/运行状态等 Redis 化为权威；它们应保留在现有安全或 PostgreSQL 事实/协调路径中。

本轮没有直接把 topology collector 的 LLDP observation 填入 locator Redis。当前 locator 缓存依赖 locator 专属 observation generation、全局 topology generation 和 parser/action/schema 指纹；topology collector 的成功/空结果也必须有完整快照语义。直接延长 Redis TTL 不足以解决跨服务复用。建议的后续实现是：成功的完整扫描在 PostgreSQL 提交后发布每设备快照；为 `topology_observations` 的新鲜度/变更建立可靠 generation fence；locator 优先读取该共享快照并按实际设备授权范围过滤。这样可以消除重复 CLI，同时不会把 stale 或失败数据误判为空拓扑。

## Redis 时间格式结论与实现

- `1789210633.197223` 是 Unix epoch 秒 + 微秒；按 `+08:00` 解析为 `2026-09-12 18:57:13.197223`。官方 [Redis MONITOR 文档](https://redis.io/docs/latest/commands/monitor/) 使用相同的 epoch 格式示例，并说明 `MONITOR` 展示收到的命令、会隐藏 AUTH secret。
- `127.0.0.1`、约 10 秒重复的 `AUTH` + `PING` 与 compose `healthcheck.interval: 10s` 和 Redis loopback source 一致；推测这些是容器健康检查，不是应用 Redis 读写量的代表。
- Compose 的 logging driver/timezone 只影响容器 stdout/stderr 元数据，不能改写 `MONITOR` 协议行内 epoch。`redis-logs` 现附加 Docker `--timestamps`；`format_redis_monitor.py` 从 stdin 转换 MONITOR 行，默认 `+08:00`，保留命令文本和微秒。文档注明 `MONITOR` 高开销并且当前 `nexora` ACL 刻意没有该权限，不应为它放宽运行时 ACL。

## 验证命令与结果

- `pytest --noconftest backend/tests/release/test_redis_monitor_formatter.py backend/tests/release/test_deploy_docker_redis_contract.py -q`：6 passed。
- `C:\Program Files\Git\bin\bash.exe -n scripts/deploy-docker.sh`：通过。
- `python scripts/format_redis_monitor.py --timezone=+08:00`：用户样例 epoch 转成 `2026-09-12 18:57:13.197223+08:00`，`AUTH (redacted)` 文本未被改写。
- 相关跟踪文件 `git diff --check`：通过，无空白错误。

## 未执行验证及原因

- 未在用户的 Ubuntu Redis 主机运行 formatter 或执行 `MONITOR`；未修改/重启独立 Redis、未改部署 `.yml`，避免触碰真实部署。
- 未执行拓扑/LLDP cache bridge，因为其需要先统一 `topology_observations` generation、完整空快照、作用域和现有 locator dependency fence；本轮只产出实现建议。

## 剩余风险与后续建议

- 现场实际拓扑 schedule 可能已被运维设为 48 小时；迁移默认仅是每日 02:00。先从拓扑页 generation-status 和 operator scheduled job 确认现场 cadence。
- 定位器默认 10 分钟 topology freshness 与 48 小时 link TTL 不一致；要复用周期事实，应同步收敛逻辑 freshness，并把成功 full-device snapshots 接入 locator dependency fencing，而不能只调大 Redis physical TTL。
- `topology_generation_status` 的自动 job 元数据值得单独校正，以免页面宣称的刷新频率与 operator job 不一致。
