# 开发一套 NetOps 平台（二）：为什么一个真正的 NetOps 平台，必须先做好 CMDB，而不是先画网络拓扑？

在上一篇文章《从 Python 脚本满天飞，到构建网络知识图谱》中，我提到过一个观点：**没有资产（CMDB），就没有后面的一切。**

许多网络工程师或开发团队在启动网络运维自动化项目时，最喜欢展示的第一个界面通常是：一张布满设备图标、连线发光、甚至带 3D 效果的网络拓扑图。然而在实际生产中，这些看似炫酷的拓扑图往往会在上线几个月后，因为一次网络变更、设备割接或板卡更换，迅速沦为没人敢信的“历史文物”。

为什么会这样？因为**拓扑只是数据的呈现形式，而 CMDB 才是数据的动态源头。** 

如果底层的物理网格与逻辑接口模型是残缺的，再漂亮的拓扑图也只是断了线的风筝。今天，我就以 Nexora 平台的真实代码和架构演进为例，深入聊聊如何从零构建一套专业、硬核的网络 CMDB，以及我们在开发中踩过的坑与工程实践。

---

## 1. 物理网格：防物理重叠的“机柜与 U 位模型”

网络设备是必须安放在物理空间里的。因此，CMDB 的第一步是建模物理空间的格子。

我们设计了清晰的空间拓扑链条：
$$\text{区域 (Region)} \longrightarrow \text{数据中心 (Datacenter)} \longrightarrow \text{机房 (Room)} \longrightarrow \text{排 (Row)} \longrightarrow \text{机柜 (Rack)} \longrightarrow \text{U位 (Rack Unit)}$$

在这个链条里，最核心、也最容易出错的逻辑在于**机柜的 U 位规划与防重叠校验**。

### 痛点：物理世界的不重叠法则
在物理机房中，两台 2U 的服务器绝对不可能强行塞进同一个 U 位空间里。但如果你的 CMDB 只是一个简单的 Excel 表或普通关系表，没有在逻辑层实现强校验，那么系统里很快就会出现“在同一个机柜的第 12U 空间同时重叠挂载了三台交换机”的离奇数据。

### 代码层实践：无重叠区间校验
在 Nexora 的 [rack_service.py](file:///e:/data/netsops/backend/services/rack_service.py) 中，我们在创建和更新机柜设备绑定关系时，在服务层（Service Layer）引入了硬性约束。

当尝试在机柜中上架设备时，系统必须验证：
1. **边界安全**：设备起始 U 位 $S \ge 1$，且设备结束 U 位 $E = S + \text{高度} - 1$ 不能超过该机柜的总 U 位数（通常为 42U 或 47U）。
2. **防重叠冲突（Overlap Check）**：新设备的区间 $[S_{new}, E_{new}]$ 不能与已上架设备的区间 $[S_{exist}, E_{exist}]$ 产生任何数学交集。

在后端，我们使用 SQL 与 Python 进行双重区间重叠判定：

```python
# 核心重叠判定逻辑 (防重叠区间相交)
# 已上架设备的范围是 [start_u, start_u + u_height - 1]
# 新上架设备范围为 [planned_start_u, planned_start_u + u_height - 1]
conflict = conn.execute("""
    SELECT device_id, name, planned_start_u, u_height 
    FROM rack_devices 
    WHERE rack_id = ? 
      AND NOT (planned_start_u + u_height - 1 < ? OR planned_start_u > ?)
""", (rack_id, new_start_u, new_end_u)).fetchall()

if conflict:
    raise ValueError(f"U位空间产生冲突！该位置已被设备 {conflict[0]['name']} 占用。")
```

将物理世界的规则转化为数据库和 API 的硬约束，是 CMDB 专业性的最基础体现。

---

## 2. 逻辑纽带：从设备中心，到“接口与链路中心”

在设计 CMDB 的第二阶段，我曾犯过一个直觉性的错误：将设备作为连接的实体。
* **错误模型**：设备 A 连接到 设备 B。

这种模型在复杂的生产网中瞬间就会崩溃。因为一个核心交换机可能连着 50 台接入交换机，如果只记录“设备 A 连接到设备 B”，我们根本无法回答以下运维核心问题：
* “设备 A 的哪个物理千兆口连的设备 B？”
* “这条连线当前是聚合口（Port-channel）还是物理单口？”
* “这条链路两端的光衰、双工模式和速率是否匹配？”

### 解决方案：Interface 与 Link 模型
网络链路（Link）的本质，是**接口与接口之间的映射关系**。设备只是接口的容器。

因此，我们的 CMDB 模型调整为三个核心实体：
1. **Device (设备)**：承载管理 IP、序列号（SN）、软件版本、设备角色等“大局属性”。
2. **Interface (接口)**：属于具体 Device，记录 MAC 地址、VLAN 划分、物理状态、IP 地址、MTU 等“接口微观状态”。
3. **Link (物理连线/逻辑链路)**：记录 `local_interface_id` 和 `remote_interface_id` 的双向一对一映射。

有了这套模型，无论是日后通过 LLDP（链路层发现协议）自发现来自动往 `Link` 表中插入数据，还是在前端呈现拓扑图时动态画出接口连线，都可以通过标准的 SQL Join 轻松完成：

```sql
SELECT 
    d1.hostname AS src_device, i1.name AS src_port,
    d2.hostname AS dst_device, i2.name AS dst_port
FROM links l
JOIN interfaces i1 ON l.local_interface_id = i1.id
JOIN devices d1 ON i1.device_id = d1.id
JOIN interfaces i2 ON l.remote_interface_id = i2.id
JOIN devices d2 ON i2.device_id = d2.id;
```

---

## 3. 工程实践：“智能纠错与异常防御”导入机制

在建设 CMDB 的过程中，我们面临的又一大考验是：**数据的批量导入**。

在真正生产环境里，网络工程师最常用的方式是使用 Excel 表格整理数千台设备，然后一键导入系统。在这个过程中，数据的拼写不一致是防不胜防的魔鬼。

### 遭遇的挑战
当从 Excel 批量导入设备资产时：
1. **机柜拼写错误**：表格里把 `BJ-DC1` 下的 `A-01` 机柜错打成了 `A-O1`（字母 O 与数字 0 混淆）。
2. **机柜尚未录入**：网络建设初期，50 个新机柜还没有在机柜管理（CMDB 物理管理）中建立，用户就尝试导入放置在这些新机柜里的服务器数据。

如果直接导入，设备与机柜的关联就会断档；如果直接报错弹窗，用户必须中断操作去一具具建机柜，体验极差。

### 我们的设计：异常拦截纠错面板 (Option 3)
在 Nexora 平台的 [index.tsx](file:///e:/data/netsops/src/pages/AssetManagement/index.tsx) 中，我们引入了前端解析校验与**异常交互映射机制**：

```text
Excel文件上传 ──> 本地读取 ──> 对比全量机柜数据 ──> 发现不存在的机柜？
                                                      │
     ┌────────────────── 存在未注册机柜 ──────────────┘
     ▼
触发 [AssetImportValidationModal] 确认弹窗 (排重展示缺失机柜与受影响行)
     │
     ├──> 选项 A：自动新建缺失机柜（一键调用 /api/racks/batch 创建42U默认机柜）
     ├──> 选项 B：纠错映射（在网页上拉下选框将 "A-O1" 替换为正确的 "A-01"）
     └──> 选项 C：跳过导入（从Payload中剔除该设备，只导入完全合规的行）
```

我们在 [AssetImportValidationModal.tsx](file:///e:/data/netsops/src/pages/AssetManagement/components/AssetImportValidationModal.tsx) 中实现了清晰的批量映射状态转换：

```typescript
const handleValidationConfirm = async (resolutions: Record<string, RackResolution>) => {
  // 1. 提取出需要自动创建的机柜列表，调用后端 /api/racks/batch 批量建档
  if (autoCreateList.length > 0) {
    await fetch('/api/racks/batch', { ...body: JSON.stringify(autoCreateList) });
  }

  // 2. 将在网页上执行了“纠错映射”的行进行在内存中替换字段
  finalPayload = finalPayload.filter(row => {
    const key = `${row.datacenter}|${row.rack}`;
    if (skipKeys.has(key)) return false; // 跳过不合规行
    if (mapConfig[key]) row.rack = mapConfig[key]; // 替换为已有机柜
    return true;
  });

  // 3. 最终提交干净的数据包到 /api/assets/import
  await doImport(finalPayload);
};
```

---

## 4. 为什么先做好 CMDB，而不是先画拓扑？

现在我们可以回答开头提出的那个问题了。

很多工具之所以把“网络拓扑”摆在第一位，是因为他们把拓扑当成了网络运维的主体。但网络是**活的**，配置在变，物理跳线在变，路由策略在变。

如果先画拓扑，你的数据是**从图到数据**的流向。这意味着你的数据是由画图的动作所决定的，极其脆弱。而先做 CMDB，你的数据是**从源到图**的流向：

1. **自动采集源**：通过 SNMP、SSH、Netconf 或 Syslog 实时发现设备的真实接口、物理邻居（LLDP）和路由。
2. **模型沉淀**：数据自动更新到 CMDB 的 `devices`、`interfaces` 和 `links` 关系表。
3. **拓扑即视图**：前端页面根据 `links` 数据，通过 D3.js, Cytoscape 或 G6 自动演算并实时呈现出拓扑连线。

在这套体系下，**网络拓扑图只是一张动态渲染出来的“视图（View）”**。一旦网络中有一根跳线被网工拔掉：
- 交换机产生 Port Down ➜ 触发 LLDP 邻居失效 ➜ 自动清理 CMDB 中的 `Link` 记录 ➜ 前端拓扑连线自动变红/消失。

**无需任何人工拖拽修改，拓扑就实时反映了物理世界的真实网络拓扑。**

这就是数据中心资产账本（CMDB）的力量。它看似枯燥、满是字段与增删改查，但它为整个网络自动化系统提供了一个唯一的可信数据源（Single Source of Truth）。

下一篇文章，我们将开启另一个极具挑战的模块——**IPAM 模块的设计：如何优雅地对上万个子网与网关进行无重叠动态树形规划。** 敬请期待！
