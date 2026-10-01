# 拓扑 SNMP 聚合口与成员采集完成记录

## 完成摘要

根因是 SNMP LLDP 完整成功后跳过 CLI，但聚合关系的同步入口仍只有 CLI 实现。实际设备的标准 LAG SNMP 表可以完整返回当前运营成员；此次增加 SNMP 采集和原子持久化，在不登录 SSH 的情况下恢复聚合口名称及成员端口。

本机实际发现 `830014cc-c199-42b0-b19a-5df413ee0288`：8 台成功，34 条 LLDP 观测全部匹配，0 未匹配/名称冲突/歧义；每台 method=snmp、SSH=not_attempted，聚合 CLI 调用计数为 0。WH-DC-02 当前 8 节点、9 条普通链路、2 条聚合链路，两组各 4 个活动成员，覆盖 17 个实际物理连接。

| 两端设备 | 两端聚合口 | 成员端口 | 成员与容量 |
| --- | --- | --- | --- |
| S6850_1 / S6850-2 | Bridge-Aggregation12 | Ten-GigabitEthernet1/0/49–52 | 4 / 4 活动，4×10G=40G |
| S6850-3 / S6850-4 | Route-Aggregation34 | GigabitEthernet1/0/1–4 | 4 / 4 活动，4×1G=4G |

S6850_1 还报告了无运营成员的 Route-Aggregation12。它作为接口库存保留，不会因此新增设备图标或虚构一条聚合边。

## 实际修改文件及分工

- backend_worker：新增 `backend/services/topology_snmp_aggregation_service.py` 与 `backend/tests/topology/test_topology_snmp_aggregation.py`。
- 主 Agent：新增 `backend/services/topology_aggregation_inventory_service.py`、`backend/tests/topology/test_topology_aggregation_inventory.py`；集成 `backend/services/topology_service.py`；增强 `backend/tests/topology/test_topology_run_identity.py`。
- frontend_worker：在 `src/components/TopologyGraph.tsx` 复用成员详情、完善现有 SVG tooltip。
- 主 Agent：将 TopologyGraph 和 `src/pages/TopologyPage.tsx` 的投影计数文案改为“链路”，避免将 11 条画布边误称为 11 个实际物理连接。
- 原有工作树变更全部保留，未提交或推送，未更改设备配置，未重启用户服务。

## 关键实现

1. 使用 `dot3adAggPortAttachedAggID` 的成员 ifIndex→父 ifIndex 关系，联查 ifName/ifDescr、ifType=161、ifOperStatus、ifHighSpeed。依据 [IEEE LAG MIB 定义](https://raw.githubusercontent.com/librenms/librenms/master/mibs/IEEE8023-LAG-MIB)，这是当前 attached 运营成员关系，不代表完整配置清单。
2. 标准表空且存在聚合父接口时可用 IF-MIB 活跃 ifStack 关系；忽略合法零端点及非 LAG 堆叠。冲突、孤立索引、缺失类型/名称、截断和超时不能提交完整快照。
3. 完整非空成员表、包括所有成员值为 0 的有效快照，可以替换成员关系。空或不支持的成员表同时存在父聚合口时返回 unavailable，避免误清空库存。没有聚合口且完整接口表有效时允许正常空快照。
4. PostgreSQL 事务先锁当前 snapshot generation 和设备，拒绝旧任务或管理 IP 已改变的写入；使用 canonical 接口名复用已有别名。成功快照解绑移出的 LAG 成员，保留子接口等其他层级关系。没有协议证据时不臆断 LACP/static。
5. SNMP-only 发现走 SNMP 聚合同步，辅助失败隔离于 LLDP，不因此打开 SSH。已有 LLDP 失败时 CLI 回退路径保留。
6. 两端聚合关系明确时折叠链路；反向 LLDP 观测的成员对统一对齐聚合边的两端。API 原有 members 和聚合字段保留。
7. 悬停聚合线的可见路径或透明命中路径均能看聚合名称、容量、活动/总成员、确认状态和每个成员端口。8 个设备图标、布局和双向实线/单侧虚线规则不变。

## 验证命令与结果

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/topology/test_topology_aggregation_inventory.py backend/tests/topology/test_topology_run_identity.py backend/tests/topology/test_snmp_lldp_discovery.py -q --tb=short
# 55 passed in 170.56s

.venv\Scripts\python.exe -m pytest --confcutdir=backend/tests/topology backend/tests/topology/test_topology_snmp_aggregation.py -q
# 22 passed；此文件为无持久化的设备 mock 单测，不重复启动 PG schema fixture

.venv\Scripts\python.exe -m pytest backend/tests/topology/test_topology_run_identity.py::test_full_lab_rebinds_34_observations_into_11_device_pairs_without_extra_devices -q --tb=short
# 增强为实际 SNMP 持久化两组聚合后，1 passed in 64.13s

npm run lint
# tsc --noEmit 通过

npm run test:frontend -- --run src/utils/topologyGraphLinks.test.ts src/utils/topologyDevices.test.ts
# 2 files / 5 tests passed

.venv\Scripts\python.exe -m py_compile backend/services/topology_service.py backend/services/topology_aggregation_inventory_service.py backend/services/topology_snmp_aggregation_service.py backend/tests/topology/test_topology_aggregation_inventory.py backend/tests/topology/test_topology_run_identity.py
# 通过；worker 另行编译了 collector 单测

.venv\Scripts\python.exe scripts/validate_postgresql_only.py
# 0 violation(s)

git diff --check
# 通过；仅既有 LF/CRLF 提示
```

共 77 个不同后端用例、5 个前端用例通过。PG 测试使用共享隔离数据库。完整实验用例增强过程中曾失败一次：fixture 在 LLDP snapshot 已完成后才写聚合关系，被 generation/state 保护正确拒绝；已调整为与真实 discovery 一致的“聚合写入→LLDP snapshot 完成”顺序，再次通过，没有弱化断言。

## 本机实际验证

- 在 S6850-1/2/3/4 上分别只读查询标准附着表、接口名、类型、状态及速度；结果与用户提供的物理图一致。
- 通过新的 collector 分别采集这四台设备，全部 status=success、members=4、来源为 dot3adAggPortAttachedAggID。
- 在没有其他同站点活动 run 时，对该站点 8 台网络设备执行了一次完整 discovery；用 CLI 聚合同步调用计数、逐台协议结果和站点过滤后的链路读模型核对结果。
- 实际读取的两条聚合边均为 bidirectional_confirmed、4 活动成员，members 保留两端设备和端口，速率分别 10000/1000 Mbps。
- 验证脚本第一次读 run 结果时误把 partial_devices 当作表字段（实际在 summary_json），已用正确 schema 只读重取；该读错误未影响已完成的 discovery。

## 未执行验证及剩余边界

- 浏览器调用现有 `http://127.0.0.1:5400/monitor/topology` 标签时，CDP 的 Emulation.setFocusEmulationEnabled 超时，因此没有取得最终截图，也没有声称视觉效果已人工核验。后端真实采集和返回的成员字段已验证；页面刷新后可查看最新投影。
- 不同设备可能不提供标准 LAG 或有效 ifStack；此时保留物理 LLDP 边和最后有效接口关系，不凭并行线数量猜聚合，不隐式执行 CLI。
- 采集范围是当前运营 attached 成员；未附着且未在 ifStack 暴露的纯配置成员无法仅凭这些表确认。
- 现有 discovery summary 的 total_links 为全局投影（本次 16 条，其中 5 条在其它范围）；本次站点过滤后的实际画布读模型为 11 条，记录中以此核对结果。此次未扩大修改全局统计口径。
- 没有生产构建或全量业务回归：变化集中于聚合采集、持久化和 tooltip，未改变打包、路由或公共基础设施。

## 回滚

可移除本次 SNMP 聚合 collector/持久化入口及调用，恢复本次 tooltip 拼接；保留此前资产、主机名同步、SNMP 优先、LLDP 身份关联和用户已有改动。此次没有数据库迁移，不需要恢复设备配置。
