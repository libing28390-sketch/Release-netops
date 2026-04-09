---
name: "topology-engineer"
description: "Designs topology discovery and visualization workflows. Invoke when implementing LLDP/CDP discovery, link mapping, or interactive network topology graphs."
---

# Network Topology Engineer Skill

你负责 Nexora 的拓扑发现与可视化，核心代码在 `services/topology_service.py` 和 `api/topology.py`。

---

## 发现流程 — `TopologyService`

1. **LLDP 发现**（优先）：通过 scrapli async 连接执行 `show lldp neighbors detail` 等命令。
2. **CDP 发现**（补充）：对 Cisco 设备执行 `show cdp neighbors detail`。
3. **Fallback**：scrapli 连接失败时自动降级到 netmiko 同步驱动。
4. **链路去重**：`rebuild_links_from_observations()` 将双向邻居观测合并为单条链路。

## 置信度评分

- LLDP 链路：`confidence = 0.9`
- CDP 链路：`confidence = 0.82`
- 多次发现同一链路会提升置信度。

## 数据结构

拓扑数据包含两部分：

```python
{
    "nodes": [
        {"id": "device_hostname", "device_id": 1, "ip": "10.0.0.1", "vendor": "cisco_ios", ...}
    ],
    "links": [
        {"source": "SwitchA", "target": "SwitchB",
         "source_port": "Gi0/1", "target_port": "Gi0/24",
         "protocol": "lldp", "confidence": 0.9}
    ]
}
```

## 前端拓扑图

- 使用 D3.js force-directed layout 渲染（`TopologyMap.tsx`）。
- 节点图标按设备类型区分（`src/assets/topology-icons/`）。
- 支持交互：拖拽、缩放、悬停显示详情、点击跳转设备。

## 扩展指南

- **新增发现协议**：在 `TopologyService` 中添加 `_discover_xxx()` 方法，返回 `(local_port, remote_device, remote_port)` 元组列表。
- **链路属性扩展**：修改 `rebuild_links_from_observations()` 的输出字段。
- **发现调度**：通过 `api/topology.py` 的 POST 端点触发全网扫描。
