# LLDP 邻居采集入口盘点

## 结论

邻居发现统一使用 LLDP。思科 IOS/IOS-XE、NX-OS 不发送 CDP；华为、华三以及其他已验证平台继续使用现有 Automation Playbook/TextFSM 的 LLDP 命令和解析模板。

## 当前入口矩阵

| 入口 | 代码位置 | 命令/解析来源 | 当前处理 |
| --- | --- | --- | --- |
| Automation Quick Query | `src/pages/AutomationExecute/index.tsx` | 场景 `neighbors`，厂商命令由前端选择 | 已移除 Cisco CDP 拼接，保留 LLDP 命令 |
| Operational Data Service | `backend/services/operational_data_service.py` | `COMMAND_CATALOG` + NTC/TextFSM | `neighbors` 目录加入 LLDP allow-list 和场景校验 |
| Topology Discovery / scheduled topology | `backend/services/topology_service.py` | `DISCOVERY_COMMANDS` + 已验证 TextFSM/共享解析 | 发送前再次校验，统一记录 `topology_lldp` 和 `lldp_playbook` |
| Diagnose path trace | `backend/services/diagnose_service.py` | 逐跳 LLDP 查询 | LLDP 禁用时明确返回禁用状态，不切换 CDP |
| Topology API/UI | `backend/services/topology_service.py`, `src/pages/TopologyPage.tsx` | 拓扑观测/链路 | 过滤器和图形不再把 CDP 当作有效邻居协议 |

## 统一结果契约

Playbook/TextFSM 负责设备回显解析，业务层统一为：

```json
{
  "local_interface": "Gi1/0/1",
  "neighbor_name": "dist-01",
  "neighbor_interface": "Gi1/0/48",
  "neighbor_management_ip": "192.0.2.10",
  "neighbor_platform": "",
  "neighbor_capabilities": ["bridge", "router"],
  "protocol": "lldp"
}
```

采集状态分为 `success`、`no_neighbors`、`lldp_disabled`、`command_failed`、`parse_failed`、`unsupported_platform` 和 `timeout`，避免把 LLDP 未启用误报为空邻居。

## 后续入口

发现服务、ARP/MAC/DHCP、接口/VLAN/VRF/路由等前缀证据采集将在后续任务中接入同一批次/快照模型；本批先冻结 LLDP 协议边界，避免前缀分类建立在不一致的邻居数据上。
