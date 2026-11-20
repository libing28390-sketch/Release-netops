# IPAM全项数据核查与业务VLAN终端逻辑

## 完成摘要与核查边界

本次检查现行IPAM的九个页面、API/service调用和当前本地PostgreSQL保存数据，修复能够复现的采集候选、作用域关联、清单计数和展示问题。终端口径是业务接入VLAN中的主机：三层VLAN网关ARP提供IP/MAC，接入交换机MAC表提供接入口。二层接入交换机自身的ARP表并不能完整列出其下终端。

原始ARP/MAC缓存继续服务全网定位和诊断；业务终端视图排除互联、管理、Loopback、未知用途，以及已知设备接口/管理地址、网关、IPv4网络和广播地址。源VRF不明时只能展示明确标识的候选，不能提升成完整覆盖证据或借用另一个上下文的MAC端口。

二层MAC表通常没有VRF字段，不能把“MAC源未声明VRF”本身当作永远无法定位的理由。同租户、站点、VLAN若通过有效VLAN与活跃网段关联唯一映射到一个VRF，可以把该映射用于关联显式ARP上下文；原始MAC源仍保持unknown。无映射或同VLAN多VRF歧义时不关联。接入口还必须具备非默认的正向access/untagged证据，排除Trunk、聚合和拓扑上联。

这是源码、隔离PostgreSQL测试及本地保存快照的核查。没有触发真实设备采集、修改设备配置或清洗现有库，没有提交、推送、部署；没有以单测替代设备现场或浏览器视觉验收。

## 当前库事实

只读脚本与聚合结果在 `.codex-build-validation-ipam-audit-20261029/audit.py`、`audit.json`，时间以结果文件为准。这些是动态快照，不是设备实时状态。

| 项目 | 结果与含义 |
|---|---|
| 网段 | 60；25互联、19服务器、12Loopback、3用户接入、1待确认 |
| VLAN/VRF目录 | 均为0；60个网段均未关联VLAN目录，不能宣称这些关联已核实 |
| IPAM登记 | 55，均由接口采集生成；应显示“接口生成台账”，不能当作55台用户终端。修正后58行=55个登记地址（带对应接口观察）+3个虚拟网关，不再重复展示113行 |
| 当前接口IP快照 | 55；52 up/up、1 down/down、2 unknown/unknown；只读取最后成功代次 |
| ARP缓存 | 90，只有10条带VLAN；6个源采集成功、4个源失败 |
| MAC缓存/独立终端缓存 | 均为0；无法证明交换机接入口 |
| IPAM发现历史 | 1127条观察、171个快照；源VRF均为unknown，范围均待确认 |
| 原始IP观察视图 | 92个源观察身份；12:46只读复核时近期0、历史92，全部范围待确认；不等于92台在线终端。源VRF不明时已停止凭同IP借用台账登记状态/主机名 |
| 业务VLAN候选 | 排除设备自身等地址后仅1条历史观察，近期0；VRF为推断，范围待核验，不是完整终端清单；最近源成功为12:19:58，默认ARP近期窗口22分钟 |
| 地址池/VIP/DHCP | 均为0；只能结合契约/隔离测试检查空态和规则，无法验证现场条目 |
| 基础一致性 | 无非法CIDR、同作用域重复网段、网关越界、登记IP越界或现存跨作用域父子关系 |

## 九个页面逐项结论

| 模块 | 已核查内容 | 修正与边界 |
|---|---|---|
| IP地址 | 来源、登记网段、站点、IP、用途、角色、主机名、设备、资产、接口、MAC、状态、时间、分页/筛选/导出 | 修复接口角色局部变量覆盖用户筛选导致只剩9条SVI；接口生成台账与对应快照合并为一行；接口Up/Down/未知与终端观察状态独立显示；未知用途不再默认为业务。保留人工登记值；接口无VRF沿用既有全局/默认候选政策。 |
| 发现终端 | ARP与MAC来源、时间/代次、租户/站点/VRF/VLAN、网段、登记匹配、冲突、定位、覆盖完整度 | 业务网段与源VLAN必须匹配，最精确网段/唯一默认VRF推断；排除基础设施地址；未知ARP上下文不得借用显式global MAC端口；推断不再冒充resolved/完整覆盖；主机名仅可来自明确IPAM记录并标来源，不能从交换机名杜撰。 |
| IP定位 | 单IP运行、强制刷新、ARP/MAC/接口/路由/拓扑来源和新鲜度 | 保留全局诊断原始缓存；修复独立终端投影跨VLAN关联及有SVI设备定时ARP候选漏传。批量采集目前不保证枚举所有VRF，不能宣称覆盖所有VPN实例。 |
| 利用率 | business/all范围、可用容量、登记占用、网关去重、站点汇总、Top与趋势 | 默认业务范围；错误、401/403和重试状态补全。占用为登记消费和配置网关，不是ARP在线率；趋势为登记创建时间累计，不是历史ARP利用率。现有19个server分类含历史默认值，仍待业务核验。 |
| IP对账 | 未登记、MAC不一致、长期未发现、从未观察、范围待确认、来源不可用；登记/校准保护 | 源时间、完整代次、VRF范围与人工确认仍严格校验。当前完整可证明源为0，55个登记地址缺可靠源覆盖；不能据此判离线或释放地址。接口配置快照不是终端ARP证据。 |
| 网段 | 地址族、掩码、站点/VRF/VLAN、父子层级、网关、分类、登记数、发现数、容量、筛选 | 层级只在同租户/站点/VRF内重建；树模式仅在其支持的筛选条件下可用，避免展示未生效筛选；前端/API/service新增默认均为待确认，接口生成不再一律server。未批量改写历史分类。 |
| 地址池 | 作用网段、起止地址、总量/已用、搜索、状态、导出 | reserved显示警示色；用量是范围内未释放登记地址，不含DHCP租约/发现/VIP。当前无现场数据。 |
| VIP | 地址、类型、控制设备、接口、真实服务器、状态、网段限定 | 非active不再全部绿色。数据为VIP台账而非现场HA探测；当前模型缺显式VRF/站点归属，跨上下文复用不能据CIDR自动断言归属。 |
| DHCP | IP/MAC/主机名、服务来源、租约开始/结束、状态、搜索 | 新建日期按本地日历初始化，避免上海午夜被UTC截到前一天。状态仍为保存租约状态，非在线状态；当前没有真实租约或已验证的DHCP同步源，默认服务名不代表已经连接该服务。 |

## 根因与实际修改

- `backend/services/ipam_service.py`：角色变量修正、台账/接口快照去重与状态元数据、未知用途/新网段默认、接口生成分类、父子作用域边界。
- `backend/services/ipam_discovery_service.py`：业务VLAN规则、基础设施IP排除、VRF推断/源证据分离、完整覆盖判断、源主机名标识、端口关联上下文约束。
- `backend/services/ipam_network_scope.py`、`backend/api/ipam.py`：沿用并检查本轮之前业务范围接口和共享分类规则。
- `backend/schemas/schemas.py`：新增网段缺省用途为unclassified。
- `backend/services/ip_locator_service.py`及相关采集策略测试：采集候选、终端ARP/MAC端口关联、正向接入端口证据helper和旧全局IP缓存跨scope写入阻断。IPAM与独立终端投影复用相同接入端口证据门禁，默认access字段不足以证明接入口。
- `src/pages/IPVlan/IPAddressTab.tsx`、`ipAddressTablePresentation.ts`：接口生成台账标签、接口状态、观察/登记解释与未知用途默认。
- `src/pages/IPVlan/IPUtilizationTab.tsx`、`PrefixManagementTab.tsx`、`prefixClassificationFilters.ts`、`IPPoolTab.tsx`、`VIPManagementTab.tsx`、`DHCPLeaseTab.tsx`及对应测试：错误/权限/重试、有效筛选、分类默认、状态色、本地日期。
- 后端回归在 `backend/tests/ipam/` 相关文件；前端回归在上述页面/helper对应测试。既有登录、首页及其他用户修改未回退。

## 验证记录

| 命令 | 结果 |
|---|---|
| `npx vitest run --config vitest.config.ts src/pages/IPVlan` | 最终15文件/58 tests passed，20.07秒 |
| `.venv/Scripts/python.exe -m pytest backend/tests/ipam/test_ipam_discovery_evidence.py -q` | 16 passed；随后补充L2 VLAN→VRF关联与unknown VRF不借台账，最终3项集成聚焦通过（99秒），覆盖唯一映射成功、歧义拒绝、原始unknown保留、接入/上联门禁 |
| 后端四文件聚焦（发现、层级、接口候选、接口快照） | 中间状态26 passed；最终快照去重新增case首次断言错误地读取create_subnet返回值字段，改为数据库断言后该case 1 passed；其他快照3项已通过 |
| `.venv/Scripts/python.exe -m pytest backend/tests/test_ipam_capacity_and_reconciliation.py -q` | 4 passed |
| `npm run lint` | 通过，tsc --noEmit退出0 |
| `npx vite build --outDir .codex-build-validation-ipam-audit-20261029/dist` | 最终前端代码构建通过，4358模块，57.85秒；输出和日志均隔离，未覆盖用户dist |
| `.venv/Scripts/python.exe scripts/validate_postgresql_only.py` | 0 violations |
| `py_compile`（IPAM service/discovery、locator、schemas）与 `git diff --check` | 通过；Git提示CRLF规范化，不是空白错误 |
| 本地只读聚合脚本 | 九个模块对应读取均成功，无库写入；结果为12:46快照 |
| ARP contract聚焦 | SVI默认策略、Huawei MAC规范化及VRF字段等5 passed / 50 deselected，128.30秒 |
| `backend/tests/ipam/test_endpoint_collector_site.py` | 全文件12 passed / 2 failed（211.79秒）；两失败为新增测试夹具漏填NOT NULL prefix_cidr，补齐后该两项2 passed / 12 deselected（80.50秒）。最终跨VRF设备接口排除专项另跑1 passed / 13 deselected（70.75秒），验证不会把另一个VRF的同IP主机删掉。未隐瞒中间失败，也未重复累计通过数 |
| 本地开发服务 | 开发后端重新启动后 `http://127.0.0.1:15310/api/health` 返回healthy；健康检查不代表现场ARP/MAC采集准确性 |

未运行全仓发布回归：本次不是发布候选，按模块风险选择聚焦验证。未做本轮浏览器视觉复测、完整真实设备ARP/MAC/VRF采集验收；当前环境此前浏览器工具不能定位Windows内嵌本地标签，不能把DOM测试称为浏览器验收。

早期更宽ARP/采集策略合并回归曾92 passed / 1 failed；该失败为Huawei MAC完整字典断言未同步新增VRF元数据，已更新明确字段断言并包含在最终5项聚焦通过结果中。这组早期结果不作为最终全量通过声明。

## 剩余证据缺口与风险

1. VLAN目录、MAC表和明确VRF上下文缺失是实际数据质量问题。严格过滤后的空白/减少不能用补造数据解决；完整清单须由后续成功采集与业务VLAN归属维护证明。
2. 历史19个server等自动分类不等于人工确认业务用途；本次阻止新增错误默认，没有未经核验重分类整个库。
3. 普通全表ARP命令及IP-MIB walk不能证明全部VRF覆盖；明确空表与解析失败也需有可靠parser信号才能区分，不能把空结果直接记作完整负向证据。
4. MAC“近期观察”窗口可以长于ARP窗口；展示接入口使用更严格的新鲜度及接入口证据，旧MAC不能当作当前位置。
5. VIP/DHCP的作用域模型、VIP状态编辑控件和真实同步来源仍有限制，已逐项记录，未擅自改变数据库设计或伪造现场采集。
   旧`network_endpoints`表按全局IP唯一，不能完整保存跨站点/VRF复用的多个终端。本次以保守阻断覆盖和保留独立ARP/MAC证据处理，不能宣称已改为多scope终端事实模型。
6. 层级修复只影响后续重建；当前库没有跨范围错误链接，未主动执行真实层级回填。
7. SVI定时候选目前仍从共享`interfaces`读取，并不使用last-good CMDB接口快照，也不检查接口运行状态。本次修正的是已发现SVI未传入采集策略的漏选，不声称已消除候选源清单滞后；显式arp=false策略继续生效。

## 回滚

只回退本任务对应代码块及新增测试即可；无数据库迁移或设备配置回滚。必须保留任务前的登录、首页、IPAM等未提交修改，不可整文件覆盖、reset或clean。
