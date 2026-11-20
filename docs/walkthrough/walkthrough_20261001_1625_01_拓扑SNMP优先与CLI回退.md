# 拓扑 SNMP 优先与 CLI 回退

## 本次核对结论

用户提供的 16:19 日志不是 SNMP 失败后 CLI 回退。8 台均明确记录 SNMP 获取有效邻居成功，随后执行 CLI reconciliation。只读查询同一 run `02e23e93-5d8f-4643-b968-573efd193c9e` 的 metadata，也确认每台 SNMP 和 SSH 均为 success、method=hybrid。

本轮 34 条观测全部匹配。日志中的 16 links 是全局派生图统计，8 台目标设备范围内实际为 11 条（9 物理、2 聚合），另 5 条属于范围外设备；不能将 16 解释为该站点关系数或重复设备数。

主机名未更新的直接原因也已确认：`10.254.0.1/.2/.3/.6` 在设备表和关联资产表中的 hostname 均为 IP，而设备 sys_name 分别已有 `S6850_1`、`S6850-2`、`S6850-3`、`S6850-6`。前端节点标签只读 Device.hostname；常规 SNMP 健康查询仅更新 sys_name，拓扑 LLDP 采集不调用资产导入的 hostname 同步。不能把旧 sys_name 或邻居报告名直接当成本轮本机验证结果。

## 实际改动

- `backend/services/topology_service.py`：完整成功 SNMP 直接返回、正常空表直接返回 no_neighbors，SSH 标记 not_attempted；SNMP 失败/partial/不可用记录仍 CLI 回退。主机名本轮验证接入在观测写入前，可选失败隔离，不触发额外 CLI。
- `backend/services/topology_local_identity_service.py`：辅助本机 IP 读取遵守主路径的 SSH not_attempted，避免从辅助流程重新建立 SSH。
- `backend/services/topology_hostname_service.py`：读取相同 SNMP 目标的 sysName.0，仅同步空/IP占位名称，保留已有真实名称冲突；同代次保护、原子同步设备/资产/拓扑观测，变更后刷新读缓存及监控目标。
- `backend/tests/topology/test_snmp_lldp_discovery.py`：SSH 有配置时 SNMP 成功仍零 CLI，Cisco/Huawei/H3C，以及空表/异常/不可用数据/partial 回退。
- `backend/tests/topology/test_topology_local_identity.py`：SNMP-only 且本机地址不可用时，bound/unbound 平台均不执行辅助 CLI。
- `backend/tests/topology/test_topology_hostname.py`：隔离 PostgreSQL 覆盖新名称同步与事务/代次边界。
- `backend/tests/topology/test_topology_run_identity.py`：发现入口名称刷新先于观测写入，名称读取失败不损害邻居，SNMP-only 不执行聚合 CLI。

## 验证记录

- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/topology/test_snmp_lldp_discovery.py -q`：32 passed。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/topology/test_topology_local_identity.py -q`：12 passed。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/topology/test_topology_hostname.py -q`：11 passed（137.18s）。使用隔离 PostgreSQL 与 mock SNMP，覆盖原子同步、未关联资产、真实名称冲突、管理 IP 修改/清空、旧 generation、空/IP形式 sysName、SNMP 异常、SNMP 失败不探测、已同名验证；未连接真实设备。
- 主机名接入前，`test_topology_run_identity.py`、`test_topology_lldp_snapshot.py`、`test_lldp_history_reset.py`、`test_topology_link_evidence.py`、`test_topology_discovery_performance.py` 5 文件回归：24 passed（133.76s）。
- 接入后 `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/topology/test_topology_run_identity.py -q`：13 passed（248.64s），包括新增两项发现入口集成测试。上述范围合计 81 个不同测试通过，不重复计算前后运行的相同项目。
- 本次 3 个服务与 4 个相关测试文件 Python 编译通过；`git diff --check` 无空白错误，只有工作树既有 LF/CRLF 转换提示。
- `.\.venv\Scripts\python.exe scripts/validate_postgresql_only.py`：0 violations。
- 独立只读审查：带 run_id 的手动发现路径无阻断问题；SNMP 成功提前返回、聚合及辅助路径零 CLI、名称校验顺序和事务保护成立。

## 未执行与限制

- 本次未触发真实设备发现、未重启用户后端、未修改现有 CMDB 名称；当前现场数据仍是上述 IP 占位名称，下一轮运行新代码时以本轮 sysName 读取结果回填。
- 未修改前端/API 类型或数据库结构，不重复前端构建，也不运行无关全量发布回归。
- LLDP 完整不保证 System MIB sysName.0 可读取；若本机名读取失败，保留名称并在采集 metadata 记录 unavailable，不猜测名称、不阻断有效拓扑。
- 此报告以用户最新“完整 SNMP 成功无需 CLI”要求替代早期“每台都双协议核对”的方案。已有 8 个图标、实线/虚线和本轮身份匹配规则继续沿用。
- SNMP 完整路径不执行 CLI 聚合库存刷新；链路继续按本轮 LLDP 观测和现有接口聚合库存计算，本次未改变聚合库存更新语义。
- 本机名验证及接口 IP 身份同步限定于带 run_id 的手动发现。定时 scheduler 当前仍传入 run_id=None，因此不会触发这两项同步；SNMP 成功不执行 CLI 的主路径规则同样对 scheduler 生效。本次未扩展定时任务架构。

## 回滚

仅撤回本次 SNMP 提前返回、辅助流程 SSH 选择和本轮 hostname 验证接入及新服务；保留此前平台绑定、MIB、拓扑匹配及用户其他未提交变化。未提交、推送或部署。
