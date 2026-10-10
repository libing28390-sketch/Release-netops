# IPAM/CMDB ARP 与接口采集 SNMP 优先改造记录

## 完成摘要

- ARP 全表改为先通过 IP-MIB IPv4 `ipNetToMediaTable` 做完整 SNMP walk；完整 walk 且数据可用时使用 SNMP 结果，否则沿用 SSH/CLI 与 TextFSM 采集。
- IF-MIB 接口状态采集改为只读接口名、管理/运行状态、速率、别名、物理地址和 MTU，不再为该用途额外读取计数器。
- 统一 NSOT 接口采集在 IF-MIB 完整成功时跳过 `show/display interfaces` 大体量明细查询；仍读取接口 IP 信息，Cisco 仍读接口 VLAN 状态。SNMP 不可用时保留原完整 CLI 路径。
- SNMP walk 不设置结果行数上限。v1 使用 GETNEXT；v2c/v3 使用 GETBULK。SNMPv3 复用凭据解析结果，不记录社区串或认证密钥。
- 设备不支持 IF-MIB alias 时，接口状态服务只回退接口描述 CLI 命令。采集预览中的传输方式已同步。

## 实际修改文件

- `backend/services/snmp_service.py`
- `backend/services/ip_locator_service.py`
- `backend/services/interface_collection_service.py`
- `backend/services/scheduler_service.py`
- `backend/services/collection_plan_service.py`
- `backend/services/nsot_collection_preview_service.py`
- `docs/plans/plan_20261010_1133_01_IPAM_CMDB_ARP接口SNMP采集优化.md`

## 关键实现

- 完整 walk 遇到超时或协议异常会抛给调用方，不能把部分结果伪装成完整快照；ARP 的 MAC 表和类型表、接口状态表也会做行索引覆盖检查。
- ARP 只接受完整且可规范化的 IPv4 条目，包含接口索引到接口名映射；空表或不可解析时回退 CLI。旧快照在采集失败时仍按原路径保留。
- IF-MIB 关键状态完整且名称可匹配后才视为 SNMP 成功。接口 IP/掩码不由该通用 IF-MIB 路径取代；VLAN/switchport 仍按原 CLI 数据来源采集。
- 统一 NSOT 普通设备路径和平台注册路径都会优先复用 IF-MIB 行，减少大体量接口详情命令。SNMP 速率/物理地址不可用时数据库更新会保留已有的已知值。

## 验证

- `python -m py_compile backend/services/snmp_service.py backend/services/interface_collection_service.py backend/services/ip_locator_service.py backend/services/collection_plan_service.py backend/services/nsot_collection_preview_service.py backend/services/scheduler_service.py`：通过，退出码 0。
- `git diff --check`：通过，退出码 0；Git 仅提示工作区文件可能发生 LF/CRLF 转换，没有 whitespace 错误。
- 未新增或运行测试。当前执行约束要求不要在未被要求时运行测试；本地 Python 环境也未安装 `puresnmp`，未做真实设备 SNMP 联调。

## 未覆盖范围与剩余风险

- ARP 目前接入 IPv4 的 IP-MIB `ipNetToMediaTable`。设备若只提供新式 `ipNetToPhysicalTable`、不提供旧表，或权限/ACL 不允许访问，会回退 CLI；IPv6 邻居表不在本次范围。
- 接口 IP/掩码及 VLAN/switchport 仍有 CLI 查询，因此这次减少的是完整接口明细和 ARP 表的 CLI 负载，并未把所有接口相关 CLI 全部移除。
- 尚未在目标网络设备上验证各厂商 SNMP 实际返回的 IF-MIB 字段与 ARP 表覆盖率；需部署后观察设备采集记录中的 `transport` 和接口 `snmp_used` 结果。
- 本次没有修改设备配置、数据库结构、提交或推送代码；如需回退，可还原上述六个服务文件，本次数据库契约未变化。
