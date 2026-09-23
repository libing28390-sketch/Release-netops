# 执行走查报告：SNMP 优先拓扑采集诊断

## 完成摘要

- 拓扑采集代码原本已先尝试 SNMP LLDP/CDP，只有无有效邻居、异常或未配置凭据时才回退 SSH CLI；本次保留该采集策略。
- 新增不含凭据的日志，明确 SNMP 无邻居、缺少凭据或异常后发生了 CLI 回退。
- 采集状态现在按真实路径记录 `snmp` 或 `ssh`，修复了 SNMP 成功仍显示 SSH 的问题。
- 修正瞬时错误重试日志占位符参数不匹配的问题。
- 邻居身份匹配现在也读取关联物理资产的 `management_ip` 和 `serial_number`；保留设备表字段作为备用身份值。这样 SNMP 返回的邻居管理 IP 能匹配只在资产记录中维护地址的设备。
- 对 `SW5`/`Switch5` 形式的未匹配邻居显示灰阶交换机图标，检查器和悬停说明都明确它是“已发现但未匹配 CMDB”，减少问号图标带来的误解。
- 确认拓扑图灰色问号表示 LLDP 已发现、但尚未匹配到 CMDB 设备。将检查器说明改成“尚未匹配到 CMDB 资产”，并提示核对通告主机名、管理 IP 和机箱 ID；“未匹配”不能说明该资产一定没有登记。
- 用户给出的实际图只有 R1-R4 与 Switch5/Switch6。页面若同时显示 R5/R6 和 SW5/SW6，代表现有 CMDB 设备与未匹配邻居目前被视作不同对象。身份合并仍需可靠设备标识；没有 IP、机箱标识或明确主机名映射时，不按编号相似度自动合并。

## 实际修改文件

- `backend/services/topology_service.py`
- `src/components/TopologyGraph.tsx`
- `src/components/TopologyInspectorPanel.tsx`
- `docs/plans/plan_20260923_2053_01_SNMP优先拓扑采集诊断.md`
- `docs/walkthrough/walkthrough_20260923_2053_01_SNMP优先拓扑采集诊断.md`

## 关键实现说明

- SNMP 采集成功日志保留原样；如果未产出有效邻居，记录 SNMP 回退到 SSH CLI 的原因范围；凭据缺失或异常时也会记录相应路径，不输出 community 或其他秘密。
- `device_collection_status.transport` 成功时记录真实传输方式；失败时按已到达的采集路径记录，`metadata.attempted_methods` 保存本次尝试顺序，未开始传输则留空。
- 为重试日志补上传入 `run_id`，避免日志格式器自身异常覆盖设备采集错误。
- 未匹配邻居提示不再断言“未录入 CMDB”，引导核对身份字段。
- 图标类型依据邻居名称的 SW/Switch 前缀显示，不用于设备身份合并。
- SNMP 失败或无数据时仍允许 CLI 兜底，因此仅靠代码变更不能修复部署环境里的 UDP 161、SNMP 凭据或设备 LLDP/CDP MIB 配置问题。

## 验证命令与结果

- `.\.venv\Scripts\python.exe -m pytest backend/tests/topology/test_snmp_lldp_discovery.py backend/tests/topology/test_topology_lldp_snapshot.py backend/tests/topology/test_server_device_exclusion.py -q`：11 项通过。
- `npm run lint`：通过。
- `git diff --check`：通过。
- 已人工检查 SNMP 成功、空结果、缺少凭据、CLI 回退、传输状态、重试日志、资产字段匹配和未匹配邻居提示。

## 未执行验证及原因

- 未运行全量后端测试，也未在用户的 Linux Docker 主机或真实网络设备上触发发现。
- 部署镜像需包含本次代码后重建并重启，再触发一次发现；如继续回退，新增日志会区分缺少 SNMP 凭据与 SNMP 无有效邻居。无有效邻居时还需在部署端核对 UDP 161、community/版本及设备 LLDP/CDP 表。

## 剩余风险与后续建议

- 新日志只能说明 SNMP 路径未产出邻居；底层 SNMP walk 当前把单项 walk 失败收敛为空结果，因此具体设备 ACL、认证或 MIB 问题仍需结合设备侧 SNMP 访问验证。
- 页面同时展示 R5/R6 与 SW5/SW6 时，不应仅凭尾号推定它们是同一设备；成功的 SNMP LLDP 管理地址或与资产序列号相符的可靠标识能将邻居正确匹配到 CMDB。若这些标识仍缺失，需要通过 CMDB 主机名/别名或现场设备信息明确映射。
- 回滚 `backend/services/topology_service.py`、`src/components/TopologyGraph.tsx` 与 `src/components/TopologyInspectorPanel.tsx` 可撤销本次行为；无数据库迁移。
