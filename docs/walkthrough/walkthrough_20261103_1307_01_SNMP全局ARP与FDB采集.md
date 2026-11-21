# SNMP 全局 ARP 与 FDB 采集走查

## 2026-11-03 15:29 FDB 深度核查

- 服务进程本轮核查已于北京时间 14:41 启动，早于当前 15:29；小时 interval 没有设置立即首跑，预计首次约 15:41。该时间依据启动与代码推算，尚未通过运行进程 job 对象确认。
- 数据库只有 ARP 采集状态，没有 mac_table 采集状态，mac_table 行数为 0。14:46 的 ARP 批次不等于联合作业已经跑过 FDB。
- 使用现有保管凭据对 S6850-5 只读 SNMP FDB 查询：首次成功返回 1 条、耗时 0.14 秒；稍后再次查询 S6850-5/6 动态 FDB 均为空。
- 两台设备 Q-BRIDGE FDB 和经典 BRIDGE FDB 均 0 行，VLAN/FDB 映射均 2 行、桥端口/ifIndex 映射均 54 行。说明 SNMP 可读、动态表内容发生变化；无法单凭这些样本确认具体老化计时器。
- 发现空表异常被分类 unsupported，导致 86400 秒退避；修正为 no_data，按下一个 ENDPOINT_FACT_INTERVAL_SECONDS 周期重试，继续保留历史快照。此修正尚未部署。
- 自动联合作业及全量 ARP 是 SNMP-only；手动 NSOT 的 FDB 路径仍允许 SNMP 失败后 CLI 回退，按 IP 主动定位也存在 SSH 查询，所以不能称整个系统全部通过 SNMP。
- 最新源观测到 IPAM 投影差约 34 秒，包含 60 秒投影调度的等待；没有测量出 SNMP 请求花费 34 秒。
- 本轮 SNMP 探测未写入源表、未更改设备配置或凭据。
- 空表分类/退避和 SNMP-only 禁止 CLI 回退聚焦回归 2 项通过（36.85 秒）；git diff --check 通过。

## 完成摘要

- 自动采集配置统一为每 60 分钟执行一轮，先采 ARP、再采 FDB；两者都使用 SNMP-only 路径。
- 新周期启动后，每日 `arp-daily-sweep` 由 migration `m0307` 软停用，避免重复采集入口。
- ARP/FDB 的“近期”判定改为两轮采集周期加 2 分钟缓冲；当前小时周期对应 122 分钟。
- ARP 扫描仍使用最大设备批次和游标；ARP、FDB 的设备并发均不超过 2，周期任务不重叠。
- 手动 ARP 全量采集和手动 NSOT 全量同步入口仍保留，可在自动周期之外额外触发设备采集。

## 采集周期核对

| 场景 | 频率/行为 | 是否访问设备 |
|---|---|---|
| 修改后的自动 ARP+FDB 作业 | 每 60 分钟一轮，先 ARP 后 FDB | 是，SNMP-only |
| 当前仍运行的旧服务/数据库 | ARP 每 10 分钟；`arp-daily-sweep` 每天 02:00 仍启用；FDB 没有自动周期 | 是；配置修改和 `m0307` 尚未应用 |
| IPAM 发现投影 | 每 60 秒 | 否，只读现有数据库证据 |
| 手动 `/ip-locator/arp-sweep` | 操作者触发一次全局 ARP 扫描 | 是 |
| 手动 `/ip-locator/nsot-sweep` | 操作者触发 ARP、FDB 和其他网络事实同步 | 是，属于额外采集入口 |
| 按 IP 定位 | 用户按需触发目标查询 | 是，独立于周期任务 |

因此新逻辑不是“每天采一次”，而是自动每小时采一轮；部署并应用迁移前，当前实例仍按旧周期运行。手动按钮会产生额外设备访问。

## 关键行为与边界

- ARP 入选不再以设备角色或 SVI 为硬门槛；显式关闭该采集项的设备仍会跳过。无 SNMP 凭据、不支持或采集失败会记状态，不回退到 CLI。
- FDB 从在线纳管网络设备读取；SNMP 凭据缺失或读取不完整会记失败并退避。只有完整非空快照才替换该设备旧表，失败保留旧数据。
- 原始 ARP/FDB 数据继续保留来源与观测时间。失败不等于终端离线，也不更新最近观测时间。
- 端口定位继续要求站点/VLAN/MAC 等证据及唯一接入端口；证据不足仍显示未定位。虚拟网关 MAC 保留在原始观测中，但不算业务终端。
- 每小时采集会漏掉两轮间出现又消失的短时终端。H3C S6850 资料提到动态 FDB 默认老化时间为 300 秒，实际设备值需现场核验；高完整度还需 DHCP 绑定或事件数据。
- `nsot-sweep` 手动入口仍可能在自动周期之外运行旧的端点收集路径；本次没有移除该人工操作，也没有验证真实设备 SNMP 能力。若未来要求严格限频，可再统一手动与周期任务的共享锁。

## 实际修改文件

- `backend/main.py`：注册单一小时 ARP+FDB 作业；保留 60 秒只读投影。
- `backend/services/ip_locator_service.py`：全局 SNMP-only ARP/FDB、设备选择、退避、快照保留，并修正 SNMP 异常状态被标成 SSH 的分支。
- `backend/services/ipam_discovery_service.py`：近期窗口跟随 ARP/FDB 周期，修正旧默认值。
- `backend/database/migrations/m0307_disable_duplicate_arp_daily_job.py`：幂等软停用内置每日 ARP 作业。
- `.env.example` 和本机忽略文件 `.env`：周期值更新为 3600 秒；示例中的 FDB 近期窗口改为自动推导。
- `backend/tests/ipam/test_ipam_discovery_evidence.py`、`backend/tests/vendor_audit/test_ip_locator_arp_contract.py`、`backend/tests/database/test_m0307_disable_duplicate_arp_daily_job.py`：刷新周期、SNMP-only 和迁移行为回归覆盖。
- `docs/modules/ipam-group/发现终端采集与排查指南.md`：补充周期、当前运行与代码配置的区别、手动入口说明。

## 验证结果

- 聚焦回归：
  `python -m pytest backend/tests/ipam/test_ipam_discovery_evidence.py backend/tests/database/test_m0307_disable_duplicate_arp_daily_job.py backend/tests/vendor_audit/test_ip_locator_arp_contract.py::test_snmp_only_arp_collection_never_falls_back_to_cli backend/tests/vendor_audit/test_ip_locator_arp_contract.py::test_snmp_only_fdb_collection_does_not_use_cli_when_snmp_is_disabled backend/tests/vendor_audit/test_ip_locator_arp_contract.py::test_snmp_endpoint_cycle_uses_all_fdb_devices_except_explicit_opt_out backend/tests/vendor_audit/test_ip_locator_arp_contract.py::test_arp_sweep_device_selection_uses_bounded_cursor_batch -q`
  结果：24 passed。
- 新增周期窗口测试单独复跑：1 passed。
- `python -m py_compile backend/services/ip_locator_service.py backend/services/ipam_discovery_service.py backend/main.py backend/database/migrations/m0307_disable_duplicate_arp_daily_job.py`：通过。
- `python scripts/validate_postgresql_only.py`：0 violations，通过。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 提示。

## 未执行验证与剩余风险

- 未重启服务、未应用迁移、未部署；因此当前运行实例尚未切换到小时周期，数据库中的每日 ARP 作业也尚未停用。
- 未连接真实设备执行 SNMP walk；S6850-5 的 ARP/FDB MIB、凭据和返回完整性仍需在部署后查看采集状态确认。
- 本次没有删除手动全量入口；运维人员手动触发仍可能增加额外 SNMP/CLI 访问。
- 回滚代码不会自动恢复已软停用的每日任务；如需回滚应通过新迁移或受控管理操作恢复，避免直接反复启停造成重复采集。
