# LLDP 采集完整性与 Docker 日志排查

## 完成摘要

LLDP 代码已完成专用 30 秒预算、10000 行上限、正确机箱 OID、二进制 MAC 保留和截断状态处理。通用 SNMP 默认值保持原调用契约，自定义端口沿设备凭据传入底层 client。

Docker 日志排查已完成，发现三类独立数据库缺陷。日志分析与下面的只读导出工具没有修改部署机器、数据库结构或业务数据；这三类缺陷尚未实施代码/迁移修复。现场结果当前没有 OOM 或连续重启证据。

对应计划：[plan_20261002_1423_01_LLDP采集完整性.md](../../docs/plans/plan_20261002_1423_01_LLDP采集完整性.md)。

## 实际修改文件

- `backend/services/snmp_service.py`：walk 结果元数据、LLDP 专用参数、OID 与 chassis 解析。
- `backend/services/topology_service.py`：不完整结果显示行数上限及 OID。
- `backend/tests/topology/test_snmp_lldp_discovery.py`：正确 `.5` OID 样本及机箱断言。
- `backend/tests/snmp/test_snmp_lldp_walk_limits.py`：预算、端口、截断、超时、签名兼容、二进制机箱回归。
- `backend/tests/topology/test_snmp_lldp_row_limit_status.py`：CLI 降级、完整 fallback、普通 partial 文案兼容及 PostgreSQL 旧观测保护。
- `artifacts/run_lldp_completeness_tests_20261002.py`：测试专用源库执行器，避免 pytest session fixture 初始化应用数据库。
- `artifacts/collect_container_errors.sh`：部署机器上使用的只读全容器诊断工具。
- `artifacts/error_log_audit_20261002.md`：日志详细证据、代码位置及未确定项。

`artifacts/` 为本地证据目录，不作为产品部署代码。保留当前工作区其他告警/IPAM及用户已有变更。

## LLDP 关键行为

### 超时和端口

| 层级 | 当前设置 | 含义 |
|---|---|---|
| 通用 `_snmp_walk` | 默认 5 秒 / 200 行 | 调用方没有覆盖时使用 |
| 拓扑 LLDP collector | 默认 30 秒 / 10000 行，显式传入 walk | 每个 OID 子树 walk 的累计预算 |
| 诊断 API / 页面 | 默认 5 秒，界面行数上限 10000 | 本次未更改 |
| UDP transport | 1 秒、最多两次发送 | 单次 SNMP 请求策略，本次未更改 |
| 拓扑设备总预算 | 300 秒 | 仍保留总任务保护及并发 limiter |

`port=161` 是默认参数。拓扑通过 `resolve_collector_credentials` 取得设备绑定的 SNMP 地址/端口，传入 collector、walk、client。回归使用非默认端口 1161，覆盖这条传参链。错误端口仍被验证并拒绝，不会静默改成 161。

30 秒 walk 预算不会自动把 UDP 单次请求超时改成 30 秒。单次请求仍可能失败；更长的 walk 预算主要允许较大的子树完成多次请求。此处没有取消时间/行数上限。

### OID 与机箱类型

- `.1.0.8802.1.1.2.1.4.1.1.2` 实际是 `lldpRemLocalPortNum` 索引，不能作为机箱 ID。
- 正确机箱 ID 使用 `.5`。旧 `.4` 端口 fallback 已移除；`.4` 现在仅正确读取 `lldpRemChassisIdSubtype`。
- 远端端口继续用 `.7 lldpRemPortId`，必要时辅助 `.8 lldpRemPortDesc`。
- `SnmpWalkResult` 保持 list 兼容。`preserve_octets=True` 仅为 `.5` walk 保存原始 bytes；其他 walk 返回字符串的行为不变。
- subtype=4 的 MAC 无损格式化为冒号十六进制，包括恰好全为可打印字节的 MAC。非 MAC 保留可打印 UTF-8 文本，否则使用安全十六进制，避免替换字符损坏身份。

### 完整性保护

- 达到行数上限即保守标记 `truncated=True`，即使恰好读完也不能据此声称完整。
- 任一 walk 失败/截断且仍有邻居：返回 partial，保留可用邻居并尝试 CLI 补充。
- 没有可用邻居且失败/截断：返回 `snmp_lldp_walk_failed:`，不能当成完整空表。
- CLI 完整时可以形成完整快照，但协议结果仍保留 SNMP 的 partial 诊断。
- CLI 不可用时，partial 发现通过 `complete_snapshot=False` 合并观测，未观察到的旧邻居不老化，未发布为完整 Redis 快照。
- 普通失败错误串和普通 partial 文案保持兼容；截断 detail 增加 `walk_row_limit` 和 `truncated_oids`。日志不输出 SNMP community。

## Docker 日志结论

### 数量及根因

主日志 36,922,981 字节、313955 行；其中数据库 ERROR 19284 条。旧粘贴片段 105 条已包含在主日志内；新实时附件额外 229 条。三份资料去重后合计 **19513 条数据库错误**。

主文件只有 `nexora-db` 的 268627 行和 `nexora-docker-socket-proxy` 的 45327 行服务前缀，其他九个容器的应用日志未出现在该文件内。因此本报告不能据这份文件断言其余容器均无错误，需用全容器导出脚本补齐 stdout/stderr；应用若另写文件日志，也需单独读取。

| 错误 | 主日志 | 新附件 | 根因与实际影响 |
|---|---:|---:|---|
| `integer = boolean` | 18644 | 229 | `snmp_mibs.is_active` 是 INTEGER，LibreNMS 查询却用 `= TRUE`；savepoint 回滚后返回空 OID，调用方继续，后续发现再次查询 |
| `integer out of range` | 624 | 0 | `interface_telemetry_raw.in_pkts/out_pkts` 是 INTEGER，采集写入 64 位 HC 总计数；写入失败使整个本设备 raw_rows 事务回滚 |
| `topology_edges_pkey` | 16 | 0 | 同一确定性 edge ID 重复写入，`target_interface=NULL` 导致普通自然唯一键未命中预期冲突处理；已有非手工边的 ID 未复用 |

主要代码证据：

- `backend/services/librenms_rule_service.py:1186` 与 `backend/database/migrations/m0134_mib_repository_import_tracking.py:26`。硬件 probe 的 `backend/services/snmp_hardware_probe_service.py:130` 也有同类潜在查询问题。
- 主日志 MIB 错误为 292 个簇，完整簇每次 64 条；间隔中位数约 140 秒。代码的慢采集循环会等待设备任务后再休眠 60 秒，因此不是每条错误都对应独立容器故障。空硬件能力始终被判过期可能放大重试，但缺少设备上下文，不能证明每个簇均来自这一条件。
- `backend/database/schema.py:2342`、`backend/services/snmp_service.py:2914`、`backend/services/background_monitor_service.py:2168`。624 条中 out_pkts 全部超过 int4，in_pkts 有 582 条超过；最大约 94.92 亿。失败不仅丢日志中的这一行，同一事务的其他原始样本也会回滚。确切批次宽度无法由日志恢复。
- 计数基线在原始样本 INSERT 前保存，存在基线已前进但原始样本缺失的问题，应连同持久化失败状态一起处理。
- `backend/services/topology_graph_service.py:900` 与 `backend/database/migrations/m0105_ai_security_operations_graph.py:414`。16 条均为同一边，图投影本轮可能跳过。

### 修复建议

1. 两处 MIB 查询与整数列对齐为 `= 1`；区分“未找到 OID”与“查询失败”，避免异常被长期静默当成无匹配。缓存必须有失效策略，不能靠压低错误日志掩盖查询失败。
2. 更新新建 schema 和已有表迁移，核对 raw/rollup 的相关计数列。BIGINT 可容纳当前样本，但无法覆盖完整 unsigned Counter64 或多个 HC 计数求和范围；可采用 NUMERIC(20,0) 或明确限制的表示。禁止把计数裁到 32 位。验证基线与样本写入的事务顺序。
3. 先优先考虑复用已有边 ID 并一致处理空接口的幂等写入；若调整唯一键，必须核查已有重复自然关系和手工边保留语义，再安排迁移。

以上为本次分析得出的实施建议，尚未应用到源代码或部署数据库。

### OOM 和资源证据

- 实时结果 11 个容器均为 `OOM=false / Exit=0 / Restarts=0`。
- `nexora-netops`：CPU 99.28%，内存 425.5 MiB / 2 GiB（20.78%）。`nexora-db`：CPU 3.01%，内存 213.2 MiB。当前快照没有接近后端内存上限。
- Linux Docker 的约 100% CPU 通常表示约一个核心的使用量。单次快照不能证明持续 CPU 饱和，更不能证明这三类错误就是全部高 CPU 来源。
- 主日志无 OOM/FATAL/PANIC 证据。有一次 PostgreSQL fast shutdown/重新启动，但日志不能证明其为 OOM。
- 当前仓库 Compose 为日志配置了 local 轮转 10 MiB × 3；netops 2 GiB/2 CPU，数据库及多数监控服务未设置独立 mem_limit。实际部署参数需在该机器 inspect 确认。
- checkpoint 的较长 write elapsed time 包含主动平滑写入过程，不能单凭 80 秒或 269 秒就判定磁盘慢；需要 sync/I/O 指标。[PostgreSQL checkpoint 文档](https://www.postgresql.org/docs/current/wal-configuration.html)。

## 部署机器上的查询方法

本机没有 Docker，未在本机运行 Docker 命令。将 `artifacts/collect_container_errors.sh` 复制到部署机器后执行：

```bash
bash collect_container_errors.sh 2h 20000
# 若需近24小时全部日志，取消每容器行数限制
bash collect_container_errors.sh 24h all
```

脚本覆盖 `docker ps -a` 的所有容器，逐个写文件，不把所有日志合并驻留内存；记录日志上下文、匹配行数、OOM/退出码/重启数、资源限制、轮转配置、stats 和 OOM/die/restart 事件。关键词匹配数不等于独立故障数。默认 20000 行上限意味着更早日志可能未包含。

简短查询：

```bash
# 当前Compose项目，保留错误上下文
docker compose logs --since 2h --timestamps --no-color 2>&1 \
  | grep -Ei -B 2 -A 4 'error|exception|traceback|fatal|panic|out of memory|oom'

# 所有容器的历史OOM事件（Docker最多保留最近256个事件）
docker events --since 24h --until "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --filter type=container --filter event=oom

# 宿主机内核OOM证据
journalctl -k --since "24 hours ago" --no-pager \
  | grep -Ei 'oom-kill|out of memory|killed process'
```

`OOM=false` 和零重启仅反映当前容器实例的记录，不排除被删除/重建实例的历史事件；Docker 事件保留范围有限。[Docker logs](https://docs.docker.com/reference/cli/docker/container/logs/)、[Docker events](https://docs.docker.com/reference/cli/docker/system/events/)。

## 验证结果

- 独立最终审查：无阻断缺陷，检查超时、端口、OID、bytes、partial 保护、旧签名和日志脱敏。
- `.venv/Scripts/python.exe artifacts/run_lldp_completeness_tests_20261002.py`：首轮 147 passed / 1 failed，199.91 秒。唯一失败来自新增测试替身未给全 SSH 凭据字段；生产逻辑没有在该处修改。
- 第一次定向复测发现替身还缺 `enable_password`，4 passed / 1 failed，90.30 秒。已按 resolver 契约补全全部字段，未降低旧观测保护断言。
- 第二次定向复测：4 passed / 1 failed，90.49 秒；空快照版本替身缺少 action/parser/schema 契约字段。已移除多余版本替身，使用实际本地版本计算；仍不进行网络采集。
- 最终定向复测：5 passed，80.92 秒。结合首轮中其余 143 项通过，148 个不同聚焦用例均已有通过结果；没有宣称单次最终全量运行 148 项。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- 所有目标 Python 文件 `py_compile` 通过；目标源码 `git diff --check` 通过。
- `C:/Program Files/Git/usr/bin/bash.exe -n artifacts/collect_container_errors.sh`：通过。仅语法检查，未执行 Docker。
- 临时 PostgreSQL 库均由 finally 强制清理；`assert_no_test_databases` 最终目录检查通过，无测试库残留。

## 未执行验证与剩余风险

- 未进行真实 SNMP/SSH、容器集成测试或部署；用户表示本机没有 Docker。另一套平台具体 LLDP 故障根因仍需在部署机器验证。
- 未改 UDP 单次请求预算；对单个响应很慢的设备，更长的 walk 总预算不保证成功。
- 历史错误导致的丢失原始样本不能靠后续修改自动找回；上述三类数据库缺陷仍需单独实施修复和 PostgreSQL 回归。
- 未运行前端构建/全量业务回归，无前端/API schema 或发布候选变更。
- 未提交、推送、修改设备配置或变更生产数据库。回滚仅本次 LLDP 服务/测试差异，保留已有告警、IPAM 及用户文件。
