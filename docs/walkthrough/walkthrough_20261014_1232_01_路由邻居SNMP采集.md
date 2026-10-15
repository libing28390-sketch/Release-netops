# 路由邻居 SNMP 采集完成记录

## 完成摘要

- `/automation/metrics` 中默认 BGP/OSPF 邻居 Down 项改为 SNMP 优先，使用标准 BGP4-MIB（IPv4 peer）和 OSPF-MIB（OSPFv2）；表不可用、凭据缺失、数据不完整或解析不可靠时回退平台 CLI/TextFSM。
- 后台 BGP/OSPF 状态变化告警改为 SNMP 优先、CLI 回退。空的 CLI 解析结果不会被当成完整邻居快照，也不会误把所有旧邻居标记为 Down。BFD 继续走 CLI。
- 巡检保存逐邻居状态并在状态改变时记录 finding；OSPF `two_way` 和带角色后缀的 `Full/DR` 按健康状态处理。
- 默认指标已覆盖 Cisco IOS/NX-OS、Huawei VRPv5/VRPv8、H3C Comware、Juniper JunOS、Arista EOS。
- 自动化脚本、SNMP 和 TextFSM 调用链已只读审查，建议见下文。

## 实际修改文件

- `backend/services/routing_neighbor_service.py`：封装 SNMP 凭据、版本、端口和短超时；只返回完整邻居表。
- `backend/services/inspection_service.py`：识别 BGP/OSPF 邻居巡检项、归一化状态、计数 Down peer、保存状态变化，并在 SNMP 失败时走 CLI 回退。
- `backend/services/background_monitor_service.py`：后台邻居状态告警改为 SNMP 优先和 CLI 回退；避免空表误告警；增加 `two_way` 状态处理。
- `backend/database/seed.py`：将现有各平台 BGP 默认项改为 SNMP，并增加常见平台 OSPF 项。
- `backend/api/alerts.py`、`backend/services/snmp_metric_profile_service.py`：描述 BGP/OSPF 的 SNMP 优先采集源。
- `src/pages/InspectionItemsTab.tsx`：BGP/OSPF 标准邻居表不用填写单个 scalar OID。
- `src/pages/alertManagementShared.ts`：显示 SNMP/CLI 回退采集源。

## 关键行为与限制

- SNMP 采集失败或快照为空时，巡检和状态变化告警保留已有 peer 状态，避免传输失败或解析失败产生假 Down。
- BGP4-MIB 的当前解析覆盖 IPv4 peer；OSPF 默认项使用 OSPFv2。设备未开放标准 MIB 或 SNMP view 不完整时会用现有厂商 CLI/TextFSM 路径。
- SNMP 邻居项不是 LibreNMS 硬件 YAML 规则；它复用仓库已有的标准路由邻居 MIB 采集器。LibreNMS 原生规则仍用于硬件和无线数据。
- BFD 未改成 SNMP。

## 可继续纳入 SNMP 的常用指标

| 优先级 | 指标 | 当前代码基础 | 建议 |
|---|---|---|---|
| 高 | 接口流量速率、错误/丢弃速率、端口 flap | IF-MIB/IF-X-MIB OID、接口采集与错误率告警已有基础 | 将 counter delta、采样间隔和速率单位统一接入巡检/告警；使用迟滞避免瞬时抖动。 |
| 高 | 设备重启与运行时间 | 已有 `sysUpTime` 指标定义 | 比较相邻样本并区分 SNMP agent 重启与设备重启语义。 |
| 中 | CPU、内存、温度、风扇、电源 | LibreNMS 硬件实体和传感器解析已有实现 | 巡检执行器当前只汇总 CPU、内存和温度；风扇、电源以及接口 SNMP 检查还没有完整接入巡检快照。 |
| 中 | 光模块 DOM、PoE 状态/功耗 | 已有光模块 SNMP 采集/OID catalog 的厂商定义；PoE 需按设备 MIB 覆盖核对 | 优先把 DOM 告警接入接口维度；PoE 按支持型号逐步启用并显示 unsupported。 |
| 中 | OSPFv3、RIP、EIGRP、IS-IS 邻居状态 | 底层 `collect_snmp_routing_neighbors` 已有相应标准/厂商 MIB 解析 | 后续可纳入健康指标；当前巡检和后台变化告警只接入 BGP/OSPF。 |
| 低/厂商相关 | BFD、队列丢弃、无线射频/客户端 | 需要确认设备 MIB、数据新鲜度和归一化能力 | 保持按厂商试点，SNMP 表/字段支持不完整时继续走 CLI 或 LibreNMS 采集。 |

## 自动化 SNMP / CLI / TextFSM 审查建议

| 优先级 | 现状与建议 | 风险/工作量 |
|---|---|---|
| P2 | `inspection_service._collect_snmp_for_inspection` 目前只从 LibreNMS 快照汇总 CPU、内存和温度；同文件的提取器虽有风扇、电源、接口分支，但采集器没有填充这些数据。接入新指标前应同时明确 freshness、单位和“不支持”状态。 | 中；约 1–2 天；会影响健康分。 |
| P2 | `/operational-data` 即使部分 category 失败也会写 `completed`；旧路径对平台未配置 category 可能记为 `success=True` + `unsupported_by_platform`。建议历史状态统一成成功、失败、部分成功、不支持，并检查各历史页的枚举映射。 | 中；约 0.5–1 天。 |
| P2 | 巡检保存 CLI 原始输出时只保存公开 `platform`；历史重解析时再用该平台找模板。H3C 不同 Comware 版本可能拿错 TextFSM 模板。建议保存具体 `parser_platform` 或模板版本并在历史重解析时复用。 | 中；约 1 天；需变更历史结果契约。 |
| P3 | 快捷查询批量执行对多台设备用 `Promise.all`，但解析器、采集源和 parse status 会被后续设备覆写，最终多厂商结果可能标为同一个解析器。建议保留逐设备解析元数据或标记 mixed。 | 低；约 0.5 天。 |
| P3 | SNMP-only 巡检跳过 SSH 时当前仍会把 `ssh_ok` 设为成功。建议增加 skipped/unchecked 语义，避免将“没测”显示成“通过”。 | 低；约 0.5 天；需确认存储/UI 状态值。 |

## 验证命令与结果

- `python -m py_compile`：通过，覆盖修改的 Python 服务、API、seed 和指标配置文件。
- `npm run lint`：通过（`tsc --noEmit`），覆盖 SNMP 指标编辑提示、告警来源标签和批次历史前端类型。
- `git diff --check`：通过；Git 仅提示部分工作树文件按仓库属性会将 LF 转为 CRLF。
- 未运行测试，也未连接真实设备或触发外部通知。

## 剩余风险与建议

- SNMP/CLI 回退效果仍取决于设备 SNMP view、凭据、CLI 命令权限以及平台 TextFSM 模板完整度。
- 建议下一步优先补足 IF-MIB 接口错误/丢弃速率与接口 flap，再接入巡检页面；随后把 LibreNMS 风扇、电源快照的 freshness 语义接通。
