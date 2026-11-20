# 从资产表到可信拓扑：复杂网络场景下，拓扑图如何自动生成

> 副标题：园区网、双核心、双上联、HA、IRF、环网、跨站点、OOB 与未知邻居的统一建图方法
>
> 摘要：自动拓扑真正困难的地方，不是把设备画到画布上，而是让每一条线都有证据、每一种关系都不被误判、每一次刷新都保持稳定。本文结合 Nexora 的工程实践，介绍一套“资产身份 + 协议证据 + 语义关系 + 动态布局”的自动拓扑方法，并说明它如何应对标准园区网和各种非标准网络场景。

## 一、为什么传统自动拓扑经常“看起来很对，用起来不敢信”

很多拓扑系统从一个简单假设开始：防火墙在最上面，核心交换机在第二层，汇聚在第三层，接入在最下面。

这个假设适合演示，却不适合真实网络。

现实中可能出现：

- 防火墙上方还有互联网接入交换机；
- 防火墙位于核心下游，只负责某个 DMZ；
- 两台核心互为 Peer，接入交换机同时双上联；
- 两个站点通过防火墙、MPLS 或隧道互联；
- 一组交换机组成 IRF、CSS、VC、Stack 或环网；
- AP 与接入交换机存在物理关系，同时又受 AC 控制；
- OOB 管理网与生产网共用设备节点，却必须保持独立；
- 只能看到邻居，却无法确认方向、角色或资产身份。

如果系统根据 Role 强行决定上下层，拓扑会被“画得整齐”，但语义可能是错的；如果把 OSPF、ARP 或接口 IP 都当作物理直连，拓扑会产生大量并不存在的线；如果每次采集都重新排序，用户又无法依赖它排障。

因此，我们先确定一个原则：

> 拓扑不是设备角色的投影，而是多源证据经过归一化、关系分类、冲突处理和稳定布局后形成的图。

## 二、整体架构：把“设备是什么”和“设备怎么连接”分开

整个自动拓扑链路可以分成六层：

```text
资产导入 / CMDB
        ↓
只读协议采集（LLDP、CDP、OSPF、ISIS、BGP、STP、路由等）
        ↓
Observation 归一化与资产身份解析
        ↓
Evidence 聚合、Relation 分类、置信度计算
        ↓
Node / Edge / Group / History 持久化
        ↓
Rank 计算、特殊布局、多视图 API、前端渲染
```

这六层各自只做一件事。

资产层回答“这是谁”；采集层回答“看到了什么”；证据层回答“这些观察是否指向同一个事实”；关系层回答“这是什么关系”；布局层回答“如何稳定地画出来”。

这样做的价值是，Role、Function、Site、Zone 不再被混成一个模糊的“层级”字段。

例如，一台 Firewall 可以位于互联网出口、核心下游、站点互联或 OOB 边界。它的 Role 都是 Firewall，但它在图上的位置必须由关系决定，而不是由名字决定。

## 三、第一步：以资产导入模板建立可信身份基线

自动拓扑的起点不是扫描 IP，而是建立可追踪的资产身份。

Nexora 复用了资产管理页面现有的 Excel 导入模板。模板中的网络设备工作表包含主机名、资产编号、厂商、型号、平台、管理 IP、Role、设备分类、站点、功能、区域、标签和投产状态等字段。

其中，对拓扑最重要的是：

| 字段 | 作用 | 是否决定上下层 |
| --- | --- | --- |
| 主机名、资产编号、管理 IP | 解析设备唯一身份 | 否 |
| 厂商、平台 | 选择驱动、只读命令和解析器 | 否 |
| Role、设备分类 | 描述设备身份 | 否 |
| Site | 建立站点边界和跨站点关系 | 否 |
| Function | 描述 Internet Edge、Campus Core、OOB Management 等功能 | 仅辅助语义 |
| Zone | 区分 LAN、WAN、DMZ、OOB、Wireless | 仅辅助语义 |
| 标签 | 标记批次、场景和测试租户 | 否 |

Role 不参与硬编码 Rank，是这套设计最关键的约束之一。

同样需要注意：Internet、ISP、MPLS、未知邻居和逻辑 Group 不应伪装成普通资产导入。它们属于图对象，可以分别使用 EXTERNAL、UNKNOWN、SITE、GROUP 等 Node Type 表达。

## 四、第二步：只采集事实，不让采集器替算法下结论

设备采集全部使用只读命令。不同协议产生不同类型的事实：

| 证据来源 | 可以说明什么 | 不能直接说明什么 |
| --- | --- | --- |
| LLDP/CDP | 设备与接口之间存在物理邻接 | 谁是上游、谁是下游 |
| OSPF/ISIS | 存在三层邻接 | 两台设备物理直连 |
| BGP | 存在路由会话，eBGP 可辅助识别 WAN 边界 | 底层传输路径 |
| Routing Table | 存在下一跳或默认路由 | 下一跳是否直连 |
| STP | 二层邻接及 Forwarding/Blocking 状态 | 三层上下游 |
| ARP/MAC | 终端或地址出现位置 | 交换机之间的可靠物理关系 |
| Interface Description | 运维人员提供的低权重语义线索 | 单独证明物理链路 |
| HA/VRRP/Stack/IRF/Control | 特殊逻辑或虚拟化关系 | 合并成同一台物理设备 |

系统设置了一条硬规则：只有 LLDP、CDP 或人工确认可以声明 PHYSICAL。OSPF、BGP、接口 IP、路由、ARP、MAC 等证据即使目标名称完全匹配，也不能被提升成物理边。

这条规则可以显著减少“图上有线、机房里没线”的误判。

## 五、第三步：把多次观察合并为一条可解释的 Edge

同一条链路通常会被看到多次：A 看到 B，B 也看到 A；LLDP 看到一次，CDP 又看到一次；下一轮采集还会重复出现。

系统会把端点、接口和关系类型进行规范化，生成稳定的 Canonical Edge Key。对无向关系以及方向未知的物理事实，A→B 与 B→A 会归并为同一条 Edge；对真正有方向的 HIERARCHICAL、BRANCH、TUNNEL、WAN 等关系，则保留方向。

Edge 与 Evidence 分开保存：

- Edge 是当前图中的关系；
- Evidence 是支持这条关系的观察记录；
- Existence Confidence 表示“这条关系是否存在”；
- Semantic Confidence 表示“我们是否正确理解了这条关系的含义”。

例如，双向 LLDP 会提高存在可信度；LLDP 加人工确认可以同时提高存在与语义可信度；接口描述只能作为较低权重的语义辅助。

这使前端不仅能画线，还能回答：“这条线为什么存在？”

## 六、第四步：用图关系计算层级，而不是用设备类型排队

标准园区网通常可以表达为：

```text
Firewall → Core → Aggregation → Access
```

如果关系被确认成有向 HIERARCHICAL，目标节点的 Rank 至少比源节点高一级。Peer、L2/L3 邻居、Ring 等平级关系可以约束节点处于同一层；HA、VRRP、Stack、OOB、跨站点等特殊关系则不参与主生产拓扑 Rank，避免污染纵向层级。

### 有向环为什么必须特殊处理

真实数据中可能因为配置、描述冲突或多源证据形成：

```text
A → B → C → A
```

如果直接反复执行“目标 Rank = 源 Rank + 1”，Rank 会不断增长，或者在设置上限后随 Edge 输入顺序变化。

解决方法是先计算强连通分量（SCC）：

1. 找出所有可以互相到达的节点；
2. 把一个有向环压缩成一个逻辑分量；
3. 环内节点使用同一基础 Rank；
4. 在压缩后的有向无环图上计算最长路径；
5. 按稳定顺序处理节点和 Edge。

这样，无论 Edge 顺序如何变化，或增加一个无关的孤立节点，原有节点 Rank 都不会漂移。

稳定性比“看起来层级很多”更重要，因为拓扑需要被持续刷新和比较。

## 七、第五步：Node、Edge、Group 与 History 分别承担什么职责

为了表达复杂网络，单纯的 Device + Link 不够。

### Node

Node 支持 DEVICE、SITE、EXTERNAL、VIRTUAL、GROUP、UNKNOWN。

非 DEVICE 节点可以出现在图上，但不能被统计成在线设备。例如 ISP、站点、未知邻居和 HA Group 可以展示为拓扑对象，其状态不会伪装成 online。

### Edge

Edge 保存源、目标、接口、关系类型、方向、状态、置信度、首次发现、最后发现、是否人工确认等信息。

### Group

Group 用于表达 HA、VRRP/HSRP、Stack、IRF、CSS、VC、Ring 等“多个节点共同构成一个逻辑单元”的场景。

Group 不是把多台设备合并成一台设备。它保留每个成员身份，只在需要时提供折叠展示。构建 Group 时必须记录关系两端成员，并按 Group + Node 去重，否则最后一段环网或 HA 对端很容易丢失。

### History

History 记录新增、保持、消失、重新出现、关系变更、人工确认和布局调整。

自动发现不应物理删除暂时消失的 Edge，而应将其标记为 stale 或 historical。人工确认的 Relation 也不能被下一轮自动发现覆盖。

## 八、复杂场景如何自动成图

下面是这套模型对典型和非典型场景的处理方式。

### 1. 标准园区网

HIERARCHICAL 关系形成 DAG，Rank 自动得到 Firewall、Core、Aggregation、Access 的纵向层次。Role 只用于图标和标签，不参与层级计算。

### 2. 防火墙上方还有交换机

只要证据表达 Internet → Edge Switch → Firewall → Core，即使 Edge Switch 的 Role 是 Access，它仍会出现在防火墙上方。算法服从关系，不服从角色刻板印象。

### 3. 防火墙位于核心下游

Core → DMZ Firewall → DMZ Switch 会被正常绘制。Firewall 不会因为身份被强制移动到全图顶部。

### 4. 双核心、双汇聚与接入双上联

系统不使用单一 parent_id，而是允许一个节点拥有多条入边。两个 Core 可以通过 PEER 处于同 Rank；两个 Aggregation 也可以平级；Access 同时保留两条上联。

### 5. 双 ISP 与多 Anchor

ISP-A、ISP-B 都可以成为 EXTERNAL Anchor。系统没有“全图只能有一个 Root”的限制，因此双出口、多运营商和多边界网络可以自然表达。

### 6. 跨站点互联

设备级 WAN、TUNNEL 或 PHYSICAL 关系仍然保留；当两个端点属于不同 Site 时，系统额外派生 INTER_SITE 关系。跨站点关系不参与单站点内部 Rank，避免北京站点的层级继续传递到上海站点。

### 7. Firewall HA

HA_PEER 作为独立关系类型保留，不再被粗略降级成 HA。两台防火墙仍是两个 DEVICE，同时加入 HA Group；该关系可以在 Logical View 展示，并排除主 Rank。

### 8. IRF、Stack、CSS、VC、MLAG 与 vPC

这些关系不是普通上下游。系统将成员关系保存在 Group 中，并允许它们进入 Physical、L2 或 Logical 视图。设备身份和管理地址仍分别保留，Group 只负责表达虚拟化或多机协同语义。

### 9. VRRP/HSRP

VRRP_HSRP 表示共享网关关系，不把两台设备合并，也不创建虚假的物理边。它属于逻辑视图，并从主 Rank 计算中排除。

### 10. 环网

Ring Edge 形成闭环，Group 保存完整成员。普通分层或力导向布局容易把环拉成一条线，因此系统对 RING 使用专用确定性圆形布局：成员按稳定名称顺序围绕 Group 中心排列，人工坐标仍然优先。

### 11. 无线网络

同一 AP 可以同时拥有两种关系：Access Switch — AP 是 PHYSICAL，AC — AP 是 CONTROL。Physical View 只看布线，Logical View 可以看到控制关系，两者互不覆盖。

### 12. OOB 管理网

OOB 是独立关系族，拥有单独视图，并通过 rank_excluded 与生产 Rank 隔离。这样，同一台核心交换机可以同时出现在生产网络和管理网络语义中，而不会被 OOB 交换机改变层级。

### 13. 三层邻接穿越二层网络

如果 R1 与 R2 建立 OSPF 邻接，但物理路径是 R1—SW1—SW2—R2，Physical View 显示三条物理边，L3 View 只显示一条 R1—R2 逻辑邻接。系统不会把 OSPF 邻接误画成一根直连网线。

### 14. 未知方向和未知邻居

Unknown 是正式状态，不是异常兜底。`direction=unknown` 会被完整保留，不强制解释成 parent/child；未匹配资产的邻居创建 UNKNOWN Node。后续资产补录或身份匹配成功后，可以合并身份，而无需丢弃原始 Evidence。

## 九、多视图不是多份数据，而是同一证据图的不同投影

同一套 Node、Edge、Evidence 可以生成不同视图：

| 视图 | 主要关系 |
| --- | --- |
| Physical | PHYSICAL、STACK、IRF、CSS、VC |
| L2 | PHYSICAL、L2_NEIGHBOR、RING、MLAG_PEER、VPC_PEER、ENDPOINT 等 |
| L3 | L3_NEIGHBOR、WAN、LOGICAL、TUNNEL、HIERARCHICAL、BRANCH、PEER |
| Logical | HA_PEER、VRRP_HSRP、CONTROL、Stack/IRF、Ring 及其他逻辑关系 |
| Site | HIERARCHICAL、INTER_SITE |
| External | WAN、TUNNEL、ENDPOINT、UNKNOWN |
| OOB | OOB |

这比为每个视图维护一份独立拓扑更可靠，因为 Edge 的身份、Evidence、状态和 History 始终只有一个事实来源。

在数据库读取上，Evidence 数量通过聚合查询一次取得，避免为每条 Edge 单独执行 COUNT。对于大图，还需要结合分页、站点过滤、前端聚合和标签降采样，避免浏览器一次渲染所有细节。

## 十、人工修订如何与自动发现共存

自动拓扑不可能永远百分之百理解网络语义，因此系统把两类人工操作分开：

- Relation Override：确认“这是什么关系”；
- Layout Override：确认“这应该画在哪里”。

拖动节点只改变坐标，不改变关系；人工确认 Relation 后，自动采集只能补充 Evidence，不能静默覆盖人工结论。

同时，图 API 需要认证并执行租户边界检查，避免用户通过 tenant_id 读取或修改其他租户的拓扑。

## 十一、我们如何验证这套方案

测试数据沿用现有资产导入模板，构造了 23 台 Cisco、Huawei、H3C、Fortinet 网络设备，覆盖北京、上海两个站点，并额外构造 ISP、MPLS、Ring Group、HA Group、IRF Group 等图对象。

测试分为五层：

1. 纯函数测试：归一化、Edge 去重、置信度、SCC Rank、Group 成员、Ring Layout；
2. 数据库测试：Node、Edge、Evidence、Group、History 的持久化和幂等；
3. API/视图契约：Physical、L2、L3、Logical、Site、External、OOB 隔离；
4. 前端布局测试：环形布局确定性、碰撞修复和链路穿越处理；
5. 工程质量门：TypeScript、Python 编译检查和 Vite 生产构建。

本轮实际结果：

| 验证项 | 结果 |
| --- | --- |
| 后端拓扑专项 | 18 项通过 |
| 数据库迁移、性能契约、厂商链路规范化 | 10 项通过 |
| 前端布局 | 4 项通过 |
| TypeScript `tsc --noEmit` | 通过 |
| Python 拓扑服务/API/AI 模块编译 | 通过 |
| Vite 生产构建 | 通过 |

重点回归包括：有向环输入顺序不变、增加孤立节点不影响原 Rank、HA_PEER 保真、Unknown Direction 保真、Group 双端成员完整、Ring 坐标稳定、CONTROL/HA 等特殊关系可从 Logical View 读取、非设备图对象不伪装成在线资产。

## 十二、哪些能力已经闭环，哪些仍需设备联调

需要坦诚区分“图引擎能处理”和“采集器已经覆盖所有厂商”。

目前，资产导入、标准 Evidence 契约、关系归一化、图构建、持久化、SCC Rank、Group、多视图、Ring Layout、人工覆盖和前端展示已经形成闭环。

LLDP/CDP、OSPF、ISIS、BGP、路由、接口描述、STP 等已有明确的协议采集路径。HA、VRRP/HSRP、部分 Stack/IRF 以及无线 CONTROL 的自动采集，则仍需针对不同厂商和版本准备真实只读输出夹具，验证命令目录与解析器。

这不是图模型无法表达，而是设备侧数据源存在厂商差异。正确做法不是猜命令或解析未验证的文本，而是让每个厂商适配器输出统一 Observation，再复用同一建图链路。

## 十三、生产落地建议

如果要把自动拓扑从实验环境推向生产，建议按以下顺序：

1. 先导入资产模板，确保设备身份、Site、平台和管理 IP 准确；
2. 使用只读账号，在测试租户执行 LLDP/CDP 与路由协议采集；
3. 对 Unknown、低 Confidence 和冲突关系建立人工复核队列；
4. 先上线 Physical、L3、OOB 三个边界清晰的视图；
5. 再按厂商逐步接入 HA、VRRP、Stack/IRF 和无线控制证据；
6. 保留 Edge History 和 Evidence，观察至少一个变更周期；
7. 对 500、2,000、5,000 节点分别做 API、数据库和浏览器压力测试；
8. 将人工 Relation Override 纳入审计，避免“为了画得好看而修改事实”。

真实设备测试只应执行 show/display 等只读命令，不在夹具、日志或文章中保存密码、私钥、Enable Secret 和 SNMP Community。

## 结语

自动拓扑的目标，不是生成一张永远整齐的图，而是生成一张可以解释、可以追溯、可以持续更新、遇到未知时敢于说未知的图。

当资产身份、协议事实、语义关系和视觉布局被拆开之后，标准园区网只是最简单的一种情况。双核心、双上联、Firewall HA、IRF、环网、无线控制、跨站点和 OOB，都可以在同一张证据图中得到一致表达。

最终，拓扑图不再是一张静态网络插图，而会成为排障、变更评估、影响分析和自动化运维共同依赖的网络事实底座。

---

## 公众号发布信息

推荐标题：**从资产表到可信拓扑：复杂网络场景下，拓扑图如何自动生成**

备选标题：

1. **别再按设备角色画拓扑：一套能处理双核心、HA 与环网的自动建图方法**
2. **自动拓扑最难的不是画图，而是让每一条线都有证据**
3. **园区网之外：复杂网络拓扑自动生成的工程实践**

推荐摘要：

> 自动拓扑为什么经常“看起来正确，却不敢用于排障”？本文从资产模板、只读协议采集、Evidence 聚合、关系分类、SCC 动态层级和特殊布局出发，完整介绍园区网、双核心、双上联、HA、IRF、环网、跨站点、OOB 与未知邻居的统一自动建图方法。

推荐关键词：`自动拓扑`、`网络自动化`、`NetOps`、`LLDP`、`CMDB`、`图算法`、`SCC`、`多厂商网络`

配图建议：

1. 首图：资产表、协议证据、关系图三层叠加的科技风架构图；
2. 文中图一：六层自动拓扑流水线；
3. 文中图二：双核心 + 双汇聚 + 双上联场景；
4. 文中图三：Physical View 与 L3 View 对照；
5. 文中图四：普通分层布局与 Ring 专用布局对照；
6. 结尾图：Evidence → Relation → History → Automation 的闭环。
