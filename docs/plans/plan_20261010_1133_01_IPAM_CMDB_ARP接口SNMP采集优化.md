# IPAM/CMDB ARP 与接口采集改为 SNMP 优先

## 目标

评估并降低 IPAM/CMDB 定时采集对设备 CLI/SSH 的依赖：对标准 MIB 能完整提供的数据优先使用 SNMP；SNMP 未配置、不支持或 walk 未完整结束时继续走现有 CLI 采集，避免把部分表写成完整快照。

## 已确认现状

- ARP 全表采集 `_collect_full_arp_result` 当前经 `collect_operational_data(categories=['arp'])` 走 CLI/TextFSM，SNMP 服务未实现 ARP MIB walk。
- 接口状态采集当前先通过 IF-MIB SNMP 采集大量计数器，再调用 CLI 采集接口状态与描述；当前服务仅接受 community，SNMPv3 配置不能复用。
- IF-MIB 可承载接口名、管理/运行状态、速率与别名；接口 IPv4 地址、VLAN/switchport 等字段不是同一组通用 IF-MIB 字段，仍保留现有 CLI 路径。
- ARP 快照已写入现有 `arp_cache`、`arp_table` 并用于 IP 定位、IPAM 终端和 CMDB VLAN 投影；本次不改存储契约或授权范围。

## 实施方案

1. 在 SNMP 服务增加不设行数上限、能将超时/错误传给调用方的完整 bulk-walk，并以 IP-MIB IPv4 ARP 表与 IF-MIB 接口索引映射输出现有 ARP 记录形状。
2. ARP 全表采集在 SNMP 凭据可用时先尝试 SNMP；SNMP walk 完整且有可解析结果才选用，SNMP 空表、异常或结果不可用时回退原 CLI/TextFSM；记录实际使用的 transport，不记录任何凭据。
3. 为 CMDB 高频接口状态增加轻量 IF-MIB 采集（名称、admin/oper 状态、速率、alias、物理地址、MTU），支持已解析的 v1/v2c/v3 凭据。采集完整成功时用 SNMP 结果同步状态；IF-MIB alias 可用时跳过描述 CLI，不支持 alias 时只回退描述命令；接口状态 walk 失败时保持原 CLI fallback。
4. 在统一 NSOT 调度器的接口采集中复用 IF-MIB 结果，成功时跳过大型 `show/display interfaces` 明细命令；保留接口 IP/Prefix、Cisco VLAN 和自定义平台路径所需的 CLI 命令，因为通用 IF-MIB 不能提供等价 IP/交换信息。设备未配置 SNMP 或 walk 失败时保持完整 CLI fallback。
5. 复查采集预览/transport 文案，保证展示与实际行为一致。

## 验收

- 所有新增完整 SNMP walk 不存在固定结果行数截断；v1 走 GETNEXT，v2c/v3 走 GETBULK；超时或异常必须可识别并触发 CLI fallback。
- SNMPv1/v2c 与 SNMPv3 均使用 `resolve_collector_credentials` 的统一凭据契约，不输出社区串或认证/隐私密钥。
- SNMP 与 CLI 最终都进入现有记录规范和 ARP/接口持久化路径。
- 保留现有接口 IP、Prefix、VLAN 投影与采集策略；SNMP 路径失败不清除或覆盖现有完整快照。
- 做静态检查（Python 编译、diff whitespace）；按当前任务约束不增加或运行测试。

## 风险与回滚

- ARP 先接入 IPv4 `ipNetToMediaTable`；设备未实现该表、权限不足或 walk 超时会走原 CLI。IPv6 邻居发现不属于当前 ARP 存储契约。
- IF-MIB 无法替代接口 IP/掩码和交换 VLAN 命令，因此这些字段仍有 CLI 采集；只有成功完整拿到状态表时才跳过大体量接口详情命令，alias 不支持时仍保留描述 CLI 兜底。
- 本次不改数据库结构，也不下发设备配置。若遇到设备兼容问题，可回滚本次代码变更，现有持久化结构和 CLI fallback 仍可用。
