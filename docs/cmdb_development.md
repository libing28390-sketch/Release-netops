# 开发一套 NetOps 平台（二）：为什么真正的 CMDB，从来不是一张设备清单？

> **如果把一个 NetOps 平台比作一座大厦，那么拓扑、监控、自动化、AI 都只是上层建筑，而 CMDB，才是真正的地基。**

上一篇文章《开发一套 NetOps 平台（一）：为什么我要从零重新设计网络运维平台？》发布后，有不少朋友留言问我一个问题：
> **为什么你的第二个模块不是网络拓扑，而是 CMDB？**

这其实也是很多网络运维平台容易走偏的地方。很多产品一打开，就是一张炫酷的网络拓扑图，设备之间的连线会闪烁，节点会跳动，看起来很有科技感。但我一直认为，**真正优秀的 NetOps 平台，不应该先画拓扑，而应该先建立一套可信的数据模型。**

因为拓扑只是展示。而 CMDB，才是真正的数据源。

---

## 1. 我也曾经认为，CMDB 就是一张设备表

刚开始设计 Nexora 的时候，我的想法其实和很多人一样，认为 CMDB 无非就是记录设备，例如：

| 主机名 | 管理 IP | 厂商 | 型号 |
| :--- | :--- | :--- | :--- |
| Core-SW1 | 10.0.0.1 | Cisco | C9500 |
| Access-SW3 | 10.0.0.23 | H3C | S5560 |
| FW-01 | 10.0.0.254 | Huawei | USG |

甚至很多公司的 CMDB，也就是这样一张 Excel。后来随着项目越做越深，我发现这种理解太浅了。因为真正的网络资产，并不是单独的一台台设备，而是一整套网络世界。

---

## 2. 真正的 CMDB，记录的是整个网络世界

想象一下，一个网络工程师每天都在做什么：添加交换机、查看接口、规划 IP、分析链路、定位故障、备份配置、生成拓扑……

这些工作看起来零散无关联，但实际上它们都依赖同一份底层数据。例如我要生成网络拓扑，系统必须知道：
* 有哪些设备？
* 每台设备有哪些接口？
* 哪些接口已经 Down？
* 哪些接口属于聚合口？
* 哪些接口属于 VLAN？
* 哪些接口拥有三层地址？
* 哪两个接口连接在一起？

如果我要分析业务中断，系统又必须知道：
* 源 IP 属于哪个网段？
* 下一跳是谁？
* ACL 有没有阻断？
* 路由有没有变化？
* 哪条物理链路已经断开？

这些功能依赖的始终是同一份底层数据。这也是为什么我们不能只把 CMDB当做“设备表”，它是**整个网络世界唯一可信的数据源（Single Source of Truth）。**

---

## 3. 描述物理世界：防物理重叠的“机柜与 U 位模型”

现实中的设备不是漂浮在空中的，它一定存放在物理空间的某个格子里。因此，Nexora 最先建立的，并不是设备，而是物理空间：
> **空间层级链：** 区域（Region） ──> 数据中心（Datacenter） ──> 机房（Room） ──> 排（Row） ──> 机柜（Rack） ──> U位（Rack Unit）

在这个链条里，核心难点是：**如何让数据库遵守现实世界的物理规则？**

在物理机房中，两台 2U 的服务器绝对不可能塞进同一个 U 位空间里。但是在数据库中，如果没有进行区间校验，这种重叠的脏数据会非常频繁地产生。

在 Nexora 的 [rack_service.py](file:///e:/data/netsops/backend/services/rack_service.py) 中，我们在上架设备时实现了严密的区间重叠（Overlap Check）和边界安全检测：

```python
# 校验起始 U 位与结束 U 位是否超出机柜最大容量限制
if start_u < 1:
    raise ValueError(f"start_u must be >= 1 (got {start_u})")
if end_u > total_u:
    raise ValueError(
        f"Device exceeds rack capacity: U{start_u}-U{end_u} but rack only has {total_u}U"
    )

# 校验当前 U 位空间是否被同方向（正/反面）设备重叠占用
query = """
    SELECT rd.id, rd.name, rd.start_u, dt.u_height
    FROM rack_devices rd
    JOIN device_types dt ON rd.device_type_id = dt.id
    WHERE rd.rack_id = ? AND rd.position = ?
"""
params = [rack_id, position]
if exclude_device_id:
    query += " AND rd.id != ?"
    params.append(exclude_device_id)

existing = conn.execute(query, params).fetchall()
for dev in existing:
    d = _row_to_dict(dev)
    existing_start = d['start_u']
    existing_end = existing_start + d['u_height'] - 1
    # 重叠判断的核心算法：[start_u, end_u] 与 [existing_start, existing_end] 是否存在交集
    if start_u <= existing_end and end_u >= existing_start:
        raise ValueError(
            f"U-position conflict: U{start_u}-U{end_u} overlaps with "
            f"'{d['name']}' at U{existing_start}-U{existing_end}"
        )
```
数据库不能允许现实中不存在的事情发生，这是物理 CMDB 的最基本职责。

### 物理微观设计：数据中心的“正反面双向挂载”
在普通资产管理系统中，机柜是以 U 位为单位的垂直槽位，一格只能挂一台设备。但实际物理世界里，很多设备（如理线架、PDU、光纤盒）非常浅，它们只占用了机柜正面（Front）或背面（Rear）局部的深度。

为了最大化空间利用率，Nexora 在 CMDB 模型中为每个上架设备定义了 `position` 属性（`front`/`rear`）。在做重叠校验时，系统只匹配同侧的占用情况：
```sql
-- 仅对同一机柜且在正/反面相同安装方向上的设备进行重叠匹配
WHERE rd.rack_id = ? AND rd.position = ?
```
这种正反面双面挂载的校验规则，允许前后两侧短深设备共用同一个 U 位刻度，使得系统的物理孪生精度达到了机房级别的物理细节水平。

---

## 4. 描述网络连接：真正连接网络的，从来不是设备

项目做到第二层设计时，我们遇到了最大的架构转折。最开始，关系非常简单：
> **起初设计：** Core-SW1 (Device) <──────> Access-SW3 (Device)
但这个模型回答不了任何细节问题：
* Core-SW1 到底是哪个接口连接 Access-SW3？
* 连线是光纤还是网线？聚合口还是物理单口？
* 两端接口的双工模式、速率、MTU 是否一致？是否有 CRC 错误包？

因为**真正连接网络、承载链路状态的，从来不是设备本身，而是物理接口。** 于是我们重构了整个模型：
> **重构后关系：** Device ──> Interface <──> Link <──> Interface <── Device
网络里的所有关系，全部围绕 Interface 建立。这为我们日后支持 LLDP/CDP 拓扑自发现奠定了完美的基础。

---

## 5. 描述接口清单：Interface，才是真正的网络资产

一个 Interface 本身就是一个高频更新的独立资产。它记录着极其微观的网络运行参数：
- **基础属性**：接口名、MAC 地址、物理 IP。
- **状态参数**：Admin Status（管理状态）、Oper Status（物理状态）、Speed（速率）、Duplex（双工模式）。
- **指标参数**：Input/Output Errors、CRC Errors、流量带宽、Discards（丢包数）、光衰（Tx/Rx Power）。
- **网络特性**：VLAN 属性、Port-channel 绑定状态、STP 生成树状态等。

所有的监控、告警、端口抖动（Flapping）分析以及光模块健康预测，全部都是基于这个 Interface 实体开展的。我们甚至可以说，**真正的网络资产是：Device + Interface。**

### 多厂商接口命名“归一化”治理 (Interface Canonicalization)
在网络开发中，最麻烦的往往是多厂商接口命名的不统一。例如思科叫 `GigabitEthernet1/0/1`，华为叫 `GigabitEthernet0/0/1`，瞻博叫 `ge-0/0/0`，而在同厂商的不同机型中，它又可能叫 `Gi1/0/1` 甚至 `Gig1/0/1`。

如果把这些参差不齐的名称直接录入，后续进行链路匹配和物理自发现（LLDP）时，字符串精准匹配会大面积失效。

因此，Nexora 引进了**接口归一化（Canonicalization）拦截机制**，在入库时自动通过正则匹配将厂商非标大写名称全部转换为标准的全局规范简写，例如：
* `GigabitEthernet1/0/24` ➜ 统一归一化为 `Gi1/0/24`
* `TenGigabitEthernet0/1` ➜ 统一归一化为 `Te0/1`
* `FortyGigabitEthernet1/1` ➜ 统一归一化为 `Fo1/1`

这一细节极大简化了多厂商接口比对和聚合口关联分析，这也是成熟 NetOps 系统必不可少的数据清洗设计。

---

## 6. 实战避坑：批量导入时的“数据防污染”校验设计

在真实生产中，网工习惯使用 Excel 表批量整理数百台设备并导入系统。在这个阶段，常常会遇到以下问题：
1. **输入错误**：把机柜 `A-01` 错写成 `A-O1`。
2. **机柜尚未注册**：大批量导入放置在新机柜下的服务器时，CMDB 中尚未建立这些新机柜。

如果直接通过，数据库会被脏机柜数据污染；如果直接中断报错，用户必须先去机柜管理页面一具具创建，体验很差。

Nexora 设计了**“异常拦截与交互式映射确认”**机制（方案三）：

```text
上传 Excel ──> 前端解析 ──> 本地比对已存机柜
                              │
  ┌─────────────────── 发现未注册的机柜 ──────────────────┐
  ▼                                                      ▼
[通过校验]                                       [触发拦截弹窗]
直接同步导入                                  展示受影响设备行数
                                                         │
                             ┌───────────────────────────┴───────────────────────────┐
                             ▼                           ▼                           ▼
                 【选项A: 自动批量建档】       【选项B: 交互映射替换】         【选项C: 跳过不合规行】
                 系统批量建立对应 42U 机柜     在网页上将 "A-O1" 纠错为 "A-01"   剔除异常行，仅导入合规行
```

在前端导入核心入口中，我们做到了如下拦截判断：
```typescript
// 本地扫描比对，查找不在 CMDB 中的机柜
const missingMap: Record<string, { datacenter: string; rack: string; rowCount: number }> = {};
mapped.forEach(row => {
  if (row.rack) {
    const dcName = row.datacenter || '';
    const exists = allRacks.some(r => r.name === row.rack && (r.datacenter || '') === dcName);
    if (!exists) {
      const key = `${dcName}|${row.rack}`;
      if (!missingMap[key]) {
        missingMap[key] = { datacenter: dcName, rack: row.rack, rowCount: 0 };
      }
      missingMap[key].rowCount += 1;
    }
  }
});
```
这种设计既避免了垃圾数据进入数据库，又为用户提供了极佳的柔性处理通道，真正体现了 NetOps 平台在工程实践上的专业性。

---

## 7. 为什么我没有立即开始做网络拓扑？

因为拓扑只是数据在某一瞬间的**呈现结果**，它不应当被做成数据库。

只要把设备、接口、LLDP 邻居和路由数据采集准确，网络拓扑图的画出只是顺理成章的静态渲染（View）。一旦有物理连线被拔掉：
> **自动链路更新：** 接口 Oper Status Down ──> LLDP 邻居失效 ──> Link 表自动删除 ──> 前端拓扑实时连线变红/断开
整个过程中**不需要任何人工修改拓扑的操作**，它真实映射了网络世界的物理孪生。

---

## 8. 一个好的 CMDB，应该具备什么能力？

总结来说，一个专业的 NetOps CMDB 必须具备以下四个维度的描述能力：
1. **物理维度**：精确感知物理格子，严格遵循机柜高度与 U 位防叠防超限校验。
2. **逻辑维度**：将连接关系解耦到 Interface，描述接口级的邻居、双工、速率和光模块指标。
3. **地址维度**：关联 IPAM，提供无冲突的子网划分、网关与 IP 资源全生命周期图谱。
4. **时间维度**：不仅有当前状态，更要沉淀状态抖动和配置漂移的历史纪录，供上层 AI 分析。

---

## 9. CMDB 从来都不是终点

CMDB 只是整个 Nexora 平台演进图谱的起点：

```text
  CMDB (网络资产源头)
    ├── IPAM (地址规划与管理)
    ├── Interface Inventory (接口微观指标)
    ├── LLDP/CDP Discovery (链路自发现)
    ├── Network Topology (动态拓扑呈现)
    ├── Endpoint Tracker (终端追踪)
    ├── Route Intelligence (智能路由表图谱)
    ├── Smart Path Trace (多协议业务路径追踪)
    ├── Configuration Center (配置版本与合规审计)
    └── AI Root Cause Analysis (故障根因分析)
```

数据模型设计错一步，上层建筑就面临全部返工的风险。打磨好这颗螺丝钉，Nexora 才有机会承载起未来网络数字孪生平台的技术架构。

---

## 10. 写在最后

多年前我认为网络自动化最难的是写脚本，后来觉得是多厂商多协议兼容，而当真正开发 Nexora 时，我才意识到最难的是**如何构建一套包容网络全生命周期的实体数据模型**。

CMDB 看起来是设备、机房、接口、IP 这些基础账本，但它是一切逻辑演进的基石。

**下一篇文章，我将聊聊同样被严重低估的 IP 资产管理：**
* 《开发一套 NetOps 平台（三）：IPAM，不只是管理 IP 地址，而是网络地址空间的数字化规划。》敬请期待！
