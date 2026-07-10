# 2. 实时监控产品使用手册 (Monitoring)

实时监控模块负责网络运行状态的采集、趋势渲染以及多厂商网络物理拓扑的发现与动态画图呈现。

![实时监控](file:///e:/data/netsops/docs/images/monitor_overview.png)

## 1. 核心功能概述

实时监控模块提供以下子功能菜单：
1. **监控概览 (Monitoring Dashboard)**：展示当前设备的总在线状态趋势、CPU 与内存利用率的历史走势图。
2. **设备性能详情 (Device Health Details)**：通过 SNMP、SSH 等协议定期轮询状态，绘制端口流量、光衰及硬件资源图表。
3. **智能拓扑呈现 (Network Topology)**：基于 LLDP 物理拓扑关系，动态绘制拓扑图谱，实时感知链路变化。

---

## 2. 详细操作步骤

### 2.1 性能指标监控
* **数据源定义**：监控服务会按照后台设定的频率轮询获取设备的基本信息（CPU/内存、风扇、电源状态）。
* **接口流量趋势**：在实时监控中，选择具体交换机，页面会实时绘制出各核心上行口和下行口的实时入向 (Input) 和出向 (Output) 流量速率折线图，帮助排查链路拥堵和环路风暴。

### 2.2 物理邻居发现与拓扑渲染
智能拓扑功能在后台的运作非常关键：
1. **数据发现**：拓扑引擎在后台定期向设备下发 LLDP 读取命令（Cisco 设备的 `show lldp neighbors`，Huawei 设备的 `display lldp neighbor brief`），采集物理接口互连信息。这一逻辑可在服务层 [topology_service.py](file:///e:/data/netsops/backend/services/topology_service.py) 中查看。
2. **拓扑绘图**：在 **实时监控 -> 拓扑发现** 界面中，系统采用 D3 或 Canvas 引擎动态绘制网络拓扑图。在图谱中：
   * 节点代表网络设备（路由器、核心、接入交换机），连线代表物理物理链路。
   * 悬停在连线上可直接看到连接的两端接口名称（如 `GigabitEthernet1/0/1 <-> GigabitEthernet0/0/24`）。
   * 当链路状态发生变化（比如发生端口 Up/Down 震荡）时，连线的颜色会实时变红或变绿，实现真正的链路拓扑动静感知。
