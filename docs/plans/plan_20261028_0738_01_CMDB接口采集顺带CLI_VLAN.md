# CMDB 接口采集顺带 CLI VLAN

## 目标

复用现有 CMDB 接口采集任务，让启用 VLAN 采集策略的设备随接口任务读取 CLI VLAN 清单并写入 CMDB 独立快照。CMDB VLAN 页面继续从既有读接口展示结果，不新增 VLAN 采集按钮或另一套采集服务。

## 现状与问题

- `/cmdb/interfaces` 的手动 CMDB 任务已经使用 `cmdb_cli_collection_service`，同一次 `PlatformActionSession` 可请求接口与 `get_vlan_table`，VLAN 结果写入独立 snapshot。
- Network Reality/NSOT 共用库存入口的 `_collect_interface_status_target` 仍先尝试 Q-BRIDGE SNMP，只有 SNMP 失败时才走 CLI，并把 VLAN CLI 投影写入共享事实表。
- Q-BRIDGE 当前实现会读 VLAN 成员、PVID、端口映射，名称表为可选；这不能保证页面所需的完整 VLAN 命令记录，也不能用缺名结果替代 CLI 快照。

## 范围与约束

- 只调整库存调用编排和既有 CMDB CLI 快照复用代码。
- 保持接口 IF-MIB/IP-MIB 的原有 SNMP 行为、监控刷新函数、调度频率、告警与设备健康值不变。
- 不修改 `snmp_service.py`、共享 TextFSM 模板、解析逻辑或驱动默认容量策略。
- 保留设备 collection plan 的 VLAN 开关；仅在 VLAN 策略启用时，接口库存任务才请求 VLAN CLI。
- 不触发真实设备采集；Redis 按用户要求忽略。

## 预计修改文件

- `backend/services/interface_collection_service.py`：在现有接口库存任务中跳过 Q-BRIDGE VLAN 域，复用现有 CMDB CLI VLAN 快照写入。
- `backend/services/cmdb_cli_collection_service.py`：允许同一既有采集函数只运行 VLAN 域，供共享库存调用复用。
- `backend/services/nsot_collection_preview_service.py`：把 VLAN 传输说明更新为 CLI。
- `backend/tests/vendor_audit/`：覆盖库存接口任务触发 VLAN CLI 快照、跳过 SNMP VLAN，并确认接口 SNMP 域未改变。
- 更新本方案、walkthrough 和 `docs/fixes/fix_*.md`。

## 实施与验证

1. 复核默认 CMDB 手动路径的 VLAN action、快照与策略 gating。
2. 让现有库存接口任务在 VLAN 策略启用时复用该 CLI collector 的 VLAN-only 调用；保持原接口状态与地址采集分支。
3. 添加聚焦回归，断言 VLAN 不调用 Q-BRIDGE、不写共享 `interfaces`/`vlans`，CLI 写入 CMDB snapshot；接口 SNMP 分支保持原调用参数。
4. 运行相关 PostgreSQL 隔离 pytest、PostgreSQL-only 扫描及发布 workflow；推送 main 后核验该 SHA 的 Actions。

## 风险与回滚

- 设备 profile 不支持或未启用 `get_vlan_table` 时，VLAN snapshot attempt 失败并保留 last-good；接口事实仍按既有领域结果处理。
- 失败时用 `git revert` 撤销本提交；不清理历史 VLAN 行，也不回填旧数据。
