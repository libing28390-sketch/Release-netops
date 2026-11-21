# SNMP 目标恢复部署 Walkthrough

> **历史结论已被后续部署取代。** 本文件早期记录“AC_11 AP/无线尚未恢复”，这是当时的状态，不是当前结论。2026-10-09 后续版本已部署 AP/客户端/无线电采集；当前设备状态和完整验证见[多厂商硬件与无线采集恢复 walkthrough](walkthrough_20261009_1102_01_多厂商无线采集恢复.md)。AC_11 的两台 AP 已报告 `run`，但四个无线电在设备 MIB 中是 admin-disabled / oper-down。

## 结果

2026-10-09 已在 `192.168.204.128` 部署 Monitoring V1 编译器修复并发布 collector 配置 v83。Grafana 接口流量、SNMP 健康和硬件 CPU/内存面板均已恢复；LibreNMS 来源的 CPU 指标为 9/9 设备，内存池为 7/9 设备。AC_11 的 AP/无线指标尚未恢复：固定 LibreNMS Comware 源没有无线发现实现，旧 `h3c_wireless` 来源不符合当前可信来源策略。完整后端回归仍在运行，结果待补。

## 变更

- `backend/services/monitoring_compiler.py`：编译器只为经过 RFC 基线确认的 IF-MIB 和 SNMP system 模块生成目标、Exporter 模块及认证别名。编译器版本为 `monitoring-compiler-1.1.0`；未经验证的厂商/自定义模块继续排除。
- `backend/tests/monitoring/test_monitoring_v1_compiler.py`：覆盖基线目标保留，以及目标模块/认证必须存在的回归场景。
- 服务器 checkout 中只替换了编译器文件；构建并重启 `netops` 服务。未重启数据库、vmagent、SNMP Exporter、VictoriaMetrics 或 Grafana。
- 管理界面生成并发布 `collector-local` v83。运行 artifact 标记为 `APPLIED`。

## 线上核验

- v83 manifest：18 个 assignment/目标组，9 个唯一资产，2 个模块，0 个非基线排除项，1 个认证别名。目标模块和 Exporter 配置一致：`generic_ifmib_interface_std`、`generic_system_std`。
- vmagent 已发现 18 个 `network_snmp` 目标组。IF-MIB 模块 9/9 UP；system 模块 4/9 UP，另外 5 条目前是 Down 且没有首次抓取时间。system 模块配置为 900 秒抓取周期；逐条直接请求这 5 个目标均返回 HTTP 200 和 13–14 条指标，因此设备响应和 exporter 模块配置正常，待下一个 vmagent 周期后复核状态。
- VictoriaMetrics 对 `up{job="network_snmp"}` 返回样本。
- Grafana `04 接口流量`显示入流量 47.9 kb/s、出流量 69.0 kb/s、错误速率 0、丢弃速率 0；`05 SNMP 采集健康`显示 9 个在线设备、0 个失败设备、平均耗时 476 ms、最大耗时 724 ms。
- Grafana 嵌入页最初短暂显示 nginx 500，稍后重新打开后已成功加载并返回上述指标；没有证据表明这次 500 与编译器补丁存在因果关系。
- **v83 首次目标恢复时的硬件状态（后续已由下文恢复）**：当时 `platform_hardware_inventory` 抓取目标自身为 UP，但硬件指标端点没有 CPU 或内存样本；数据库对当时 9 台目标设备的 v2 LibreNMS 规则能力状态为 `unsupported / no_hardware_definition`。该问题与 `generic_system_std` 的 900 秒抓取周期无关，需独立补齐硬件发现及 CPU/内存规则覆盖。

## LibreNMS 硬件规则恢复（2026-10-09，Asia/Shanghai）

- 新采集实现使用固定 LibreNMS commit `6c26b4fe4a40f7b392c19c36a44257212736e38c` 的 OS PHP 类和 MIB 来源。Cisco IOS 对应 `Ios.php` 与 `Shared/Cisco.php`；H3C Comware 对应 `Comware.php`。`ios.yaml`、`comware.yaml` 的 SNMP 目标编译路径仍与硬件 CPU/内存发现分离。
- Cisco CPU 遵从上游选择顺序：`cpmCPUTotal5minRev`、`cpmCPUTotal5min`/`cpmCore5min`，再回退 `OLD-CISCO-CPU-MIB::avgBusy5`；QFP 取五分钟值。Cisco 内存按 LibreNMS 顺序使用 CEMP、Cisco Memory Pool、CPM used/free 池计算百分比。H3C CPU 排除零值，内存只取 `entPhysicalClass=module` 且 usage > 0 的实体。
- 当前 9 台设备的 LibreNMS OS 能力结果：CPU 9/9 `success`；内存 7/9 `success`，两台 Cisco vIOS-L2 为 `not_found / no_cisco_memory_pool`，设备实际未返回 LibreNMS 内存池数据。
- 硬件 metrics endpoint 与 VictoriaMetrics 均有 9 条 `nexora_hw_cpu_usage_percent{source_type="librenms_os_rule"}`、7 条 `nexora_hw_memory_usage_percent{source_type="librenms_os_rule"}`。Grafana 设备详情中 AC_11 显示 CPU 16%、内存 45%。F1090-9 的最新采样为 CPU 7%、板卡内存 75%，两项质量均为 `good`。
- 发现 F1090-9 偶发 `NoActiveSqlTransaction` 后，追到 PostgreSQL 连接池复用了数据库启动初始化时留下的 `autocommit=True` 状态。现在线程池连接归还时会回滚并重置为默认事务模式，避免硬件 discovery/sample 中 `SELECT ... FOR UPDATE` 偶发失败。
- 连接池修复后 `netops` 再构建并健康运行；`nexora-db` 重启计数为 0，vmagent、SNMP Exporter、VictoriaMetrics、Grafana 未重启。后端镜像 ID：`sha256:dd343508512889aa83f4e2138597755b9c9b94b07bd00730fea9dcb97a74ea6c`。
- 备份位于 `/var/backups/nexora/librenms-hardware-20261009`，其中包含修复前后镜像标签和连接池源码备份。
- 验证：硬件 SNMP 探测/库存测试 33 passed；PostgreSQL 连接池测试 5 passed；PostgreSQL-only policy 0 violations；服务器 Python 编译、Compose 配置和 `git diff --check` 通过。完整 `pytest backend/tests` 当时仍在运行，最终结果应在完成后补入。

## H3C AP/无线采集诊断（2026-10-09，Asia/Shanghai）

- AC_11 的命令行确认 AP_12、AP_13 均处于 `R/M`。生产库中留有 4 条 AP、80 条 radio、9 条 controller 旧传感器，来源为 `h3c_wireless`；数据标记为 `legacy_snmp` 且 `enabled=false`，没有当前 discovery version。旧无线能力最后成功于 2026-10-08 19:19，传感器最后样本为 2026-10-09 06:49。
- 10:46 的新硬件发现生成了 LibreNMS 规则 CPU/内存等指标，没有无线类别。Grafana 无线面板筛选 `source_type="librenms_rule"`，旧 `h3c_wireless` 行不会通过当前采样和展示路径。
- 固定 LibreNMS commit 中的 Comware 类实现 `MempoolsDiscovery`、`ProcessorDiscovery` 和 `TransceiverDiscovery`，不实现 Wireless discovery；打包了 `HH3C-DOT11-*` MIB 文件不代表上游提供了 AP/radio 的发现和轮询规则。该问题与 SNMP 基线目标、AC/AP 在线状态无关。
- 遵循用户确认的来源约束，没有重新启用本地旧 `h3c_wireless` 采集器或将其冒充为 LibreNMS。正式恢复需先补足固定 LibreNMS 来源的 Comware wireless discovery/polling，再通过来源校验接入库存和指标导出并重新部署；本次部署未包含该工作。

## 验证

- `& .\.venv\Scripts\python.exe -m pytest -q backend/tests/monitoring/test_monitoring_v1_compiler.py`：23 passed。
- `& .\.venv\Scripts\python.exe -m pytest -q backend/tests/monitoring/test_collector_artifact_service.py`：2 passed。
- `git diff --check -- backend/services/monitoring_compiler.py backend/tests/monitoring/test_monitoring_v1_compiler.py`：通过。
- 服务器 `docker compose config -q`：通过；后端容器健康，数据库仍健康。
- v83 manifest / 文件校验、目标组统计、运行时版本状态和 Grafana 实际面板均已检查。

## 备份与回滚

- 备份目录：`/var/backups/nexora/snmp-target-fix-20261009_0834`，目录权限 700。
- 原编译器：`monitoring_compiler.py.pre`；旧镜像标签：`nexora-netops:pre-snmp-target-fix-20261009_0834`。
- 可用的 v81 artifact 已复制到 `artifact-v00000081`，checksums 全部通过（18 assignment、2 modules、1 auth alias）。v82 是空目标 artifact，不能作为回滚目标。
- 未提交、未推送代码。后续更新服务器 checkout 时应保留并纳入此补丁。
