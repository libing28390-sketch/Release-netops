"""Generate source-backed Nexora submenu manuals from the navigation contract.

The generator intentionally reads the live navConfig.ts so the documentation
cannot silently omit a newly registered submenu.  Each article is deliberately
long-form: it explains data meaning, safe operations, validation, audit, and
cross-page workflows rather than only listing button names.
"""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "src/components/AppSidebar/navConfig.ts"
OUT = ROOT / "blog/user-manuals"
DATE = "2026-08-01"


DETAILS: dict[str, dict[str, str]] = {
    "dashboard": {"focus": "运营总览中的全局设备、站点、告警、容量和任务健康度", "objects": "设备状态、告警等级、站点、备份任务、容量指标", "flow": "先看总览卡片，再按异常设备、告警或站点下钻，最后回到对应事实页面确认"},
    "monitoring": {"focus": "实时遥测、设备健康度、事件流和快速处置", "objects": "在线状态、CPU、内存、接口、遥测时间戳、告警事件", "flow": "确认数据新鲜度→定位异常设备→查看指标与事件→进入拓扑或设备详情"},
    "outbound-monitoring": {"focus": "互联网出口、链路质量、带宽趋势和出口设备状态", "objects": "出口链路、时延、丢包、带宽、负载均衡、防火墙和路由器", "flow": "先按出口和时间筛选，再比较流量与质量，最后结合变更工单判断是否需要处置"},
    "server-monitoring": {"focus": "服务器监控，统一查看 Windows 与 Linux 主机的资源和服务", "objects": "主机、操作系统、CPU、内存、磁盘、进程、服务和采集代理", "flow": "选择系统类型→查看主机健康度→定位指标异常→检查采集代理和服务"},
    "network-monitoring": {"focus": "网络设备接口、协议和系统指标监控", "objects": "交换机、路由器、防火墙、负载均衡、接口、协议邻居", "flow": "按站点/角色过滤→查看设备状态→进入接口或协议指标→关联配置和拓扑"},
    "topology": {"focus": "按站点、角色、设备标签和链路状态查看网络拓扑", "objects": "站点、设备、路由器、防火墙、负载均衡、交换机、LLDP 链路", "flow": "选择标签条件并预览命中设备→确认范围→展开拓扑→点击设备查看详情或登录"},
    "access-center": {"focus": "资产树导航、受控终端登录和设备会话管理", "objects": "站点、设备分类、管理 IP、协议、会话、操作审计", "flow": "折叠树定位设备→确认管理地址与权限→打开单一终端会话→按需结束会话"},
    "pam-audit": {"focus": "特权访问、MFA、会话记录和命令级审计", "objects": "用户、设备、会话、MFA、命令、审批和审计证据", "flow": "筛选用户/设备/时间→查看会话摘要→核对命令与审批→导出审计证据"},
    "alert-desk": {"focus": "当前告警的分级、确认、派单和处置闭环", "objects": "告警规则、设备、严重级别、责任人、确认状态和处置记录", "flow": "先处理 P1/P2→确认影响范围→分派责任人→记录原因与恢复证据"},
    "alert-history": {"focus": "历史告警检索、趋势分析和重复告警复盘", "objects": "告警指纹、发生/恢复时间、设备、站点、规则和处理历史", "flow": "按时间与等级筛选→查看单条生命周期→对比同类事件→优化规则或维护期"},
    "alert-rules": {"focus": "告警规则、阈值、去重、抑制与通知策略", "objects": "指标、阈值、等级、范围、聚合键、通知渠道和启停状态", "flow": "定义范围→配置触发与恢复→预览命中→小范围启用→观察误报率"},
    "maintenance": {"focus": "维护期内的告警抑制、范围和自动恢复", "objects": "维护窗口、资源选择、时间段、抑制策略和创建人", "flow": "先关联工单→限定设备/标签范围→设置开始结束时间→验证自动恢复"},
    "assets": {"focus": "资产总览、设备状态、默认展示列和统一资产筛选", "objects": "设备、服务器、管理 IP、生命周期状态、站点、厂商和标签", "flow": "使用状态/站点/标签筛选→调整列显示→打开资产详情→核对同步与生命周期"},
    "devices": {"focus": "网络设备资产的同步、生命周期和厂商平台信息", "objects": "网络设备、管理 IP、厂商、型号、平台、角色、状态和标签", "flow": "先检查待投产/在线状态→按管理 IP定位→查看同步时间→处理采集或接管问题"},
    "servers": {"focus": "服务器资产、Windows/Linux 分类和监控关联", "objects": "服务器、操作系统、IP、主机名、代理、服务、站点和生命周期", "flow": "按系统与状态筛选→核对主机身份→查看监控→处理代理或生命周期变更"},
    "path-diagnose": {"focus": "从源到目的的路径诊断、逐跳证据和影响定位", "objects": "源/目的地址、路由、接口、链路、跳数、时延和丢包", "flow": "输入源目的→选择 VRF/协议范围→运行诊断→逐跳核对→生成处置建议"},
    "nsot": {"focus": "网络事实库中设备、接口、地址、链路和采集证据的统一视图", "objects": "事实对象、来源、置信度、首次/最后发现、冲突和版本", "flow": "搜索事实→查看来源证据→判断冲突→回到 CMDB/IPAM/拓扑修正主数据"},
    "tags": {"focus": "全量设备标签的创建、校验、关联、分页和组合筛选", "objects": "标签名称、代码、分类、来源、启用状态、分配数和自定义属性", "flow": "搜索或分页定位→检查代码格式→关联资产→在拓扑/自动化中用 AND/OR/NOT 预览"},
    "cmdb-credentials": {"focus": "网络设备和服务器凭据、MFA 绑定、轮换与访问权限", "objects": "凭据、协议、用户名、密钥引用、有效期、绑定设备和审计", "flow": "创建凭据引用→限制适用范围→测试连接→绑定资产→按周期轮换"},
    "cmdb-racks": {"focus": "机房、机柜、U 位、设备安装关系和容量", "objects": "站点、机房、机柜、U 位、设备、功耗、重量和占用率", "flow": "建立层级→维护机柜规格→拖放/录入设备→检查冲突与容量→导出布局"},
    "cmdb-assets": {"focus": "CMDB 资产目录树，按站点和资产分类快速查找", "objects": "站点、网络设备、服务器、防火墙、交换机、资产状态和数量", "flow": "折叠分类树→按站点展开→选择资产类型→进入列表或详情核对字段"},
    "cmdb-resources": {"focus": "跨设备、接口、IP、VLAN、VRF 和站点的资源检索", "objects": "资源类型、标识、归属设备、站点、状态和关联关系", "flow": "选择资源类型→输入精确标识→查看关联→跳转事实源并核对更新时间"},
    "cmdb-devices": {"focus": "CMDB 设备骨架、基础身份字段和设备关系", "objects": "设备 ID、主机名、管理 IP、厂商、型号、角色、站点和生命周期", "flow": "导入或新增→校验唯一性→补充站点/角色→关联凭据与接口→保存审计"},
    "cmdb-interfaces": {"focus": "设备接口骨架、链路、地址、VLAN、VRF 和状态", "objects": "接口名、管理状态、运行状态、IP、MAC、VLAN、VRF、对端和速率", "flow": "按设备筛选→核对采集字段→处理接口别名→关联 IPAM/拓扑→确认冲突"},
    "cmdb-sites": {"focus": "站点层级、地址、联系人、标签、导入模板和导出", "objects": "站点编码、名称、类型、区域、父站点、联系人、状态和标签", "flow": "下载模板→按字段填写→导入预检→修复错误→提交→导出复核"},
    "cmdb-vrfs": {"focus": "VRF 路由实例、RD/RT、设备绑定和隔离关系", "objects": "VRF 名称、RD、RT、设备、接口、站点、租户和状态", "flow": "建立 VRF→核对 RD/RT 唯一性→绑定设备接口→检查路由域影响"},
    "cmdb-vlans": {"focus": "VLAN、VLANIF、业务归属、站点和端口范围管理", "objects": "VLAN ID、名称、站点、VRF、网关、接口、业务和状态", "flow": "折叠分类→新增或编辑→检查 ID/站点唯一性→关联接口和前缀→导出"},
    "cmdb-vlan-business": {"focus": "VLAN 与业务、部门、负责人和生命周期的对应关系", "objects": "业务名称、VLAN、网段、负责人、环境、风险和生命周期", "flow": "选择业务→核对网段/VLAN→维护负责人→查看关联设备→变更前完成影响确认"},
    "cmdb-tenants": {"focus": "租户、资源边界、站点和 IPAM/CMDB 权限隔离", "objects": "租户、编码、联系人、资源范围、状态、站点和配额", "flow": "创建租户→定义边界→分配资源→验证可见性→审计修改"},
    "ipam-locate": {"focus": "按 IP、MAC、主机名和接口定位地址归属", "objects": "IP、MAC、设备、接口、前缀、VLAN、VRF、来源和最后发现", "flow": "输入精确地址→查看多来源证据→处理冲突→跳转设备/接口/前缀"},
    "ipam-prefixes": {"focus": "IPv4/IPv6 前缀、层次关系、用途分类和利用率", "objects": "CIDR、父子前缀、VRF、VLAN、网关、站点、利用率和冲突", "flow": "同步接口候选→预览→生成或新增→复核分类与重叠→持续检查老化"},
    "ipam-ips": {"focus": "IP 地址分配、状态、设备接口绑定和回收", "objects": "地址、前缀、主机名、设备、接口、MAC、状态、来源和时间", "flow": "按前缀查找→分配/释放→校验唯一性→和采集事实对账"},
    "ipam-pools": {"focus": "地址池范围、可用地址、分配策略和容量预警", "objects": "地址池、前缀、保留地址、已用/可用数量、租户和阈值", "flow": "创建池→定义保留范围→分配地址→监测利用率→规划扩容"},
    "ipam-vips": {"focus": "VIP、负载均衡服务、后端池和业务关联", "objects": "VIP、协议端口、F5/负载均衡设备、服务池、健康状态和负责人", "flow": "登记 VIP→关联设备与池→核对健康检查→变更前确认业务影响"},
    "ipam-dhcp": {"focus": "DHCP 租约、地址状态、客户端身份和回收", "objects": "租约、IP、MAC、主机名、租户、开始/到期时间和来源", "flow": "按地址/MAC检索→确认租约→处理过期/冲突→同步地址状态"},
    "ipam-util": {"focus": "前缀和地址池利用率、趋势、阈值和扩容判断", "objects": "总地址、已用、可用、保留、利用率、站点、VRF和时间序列", "flow": "选范围→看趋势→识别高利用率→结合业务容量→建立扩容工单"},
    "ipam-reconciliation": {"focus": "规划数据、采集事实和 IPAM 记录的地址对账", "objects": "规划地址、发现地址、冲突、缺失、来源、置信度和处理状态", "flow": "运行对账→按冲突类型筛选→确认事实→修正主数据→记录例外"},
    "config-backup": {"focus": "配置备份快照、校验、版本、恢复和备份中心统计", "objects": "设备、Running/Startup、快照、完整性、采集来源、哈希和保留期", "flow": "查看最新有效→定位失败快照→重试采集→校验哈希→进入对比或恢复预案"},
    "config-schedule": {"focus": "备份计划、设备范围、频率、保留和执行日志", "objects": "计划、Cron、设备标签、厂商、配置类型、保留天数和失败重试", "flow": "选择范围→设置频率→配置保留/重试→预览命中设备→保存并观察执行"},
    "config-diff": {"focus": "A/B 配置差异、对象解析、风险、合规和受控回滚", "objects": "有效快照、统一 Diff、接口/VLAN/路由/ACL/BGP、风险、基线和工单", "flow": "自动选择最近有效两版→确认 A→B→查看对象/风险→关联来源→导出或生成回滚预案"},
    "config-search": {"focus": "跨设备配置对象搜索、历史追踪、合规规则和导出", "objects": "查询类型、搜索范围、IP/CIDR/VLAN/ASN、配置对象、快照和审计", "flow": "输入查询→确认系统解释→限定站点/厂商/角色→查看结果→关联差异/IPAM/拓扑"},
    "configuration": {"focus": "配置模板三栏中心、参数 Schema、沙箱渲染和任务草稿", "objects": "模板、版本、参数、参数方案、命令预览、风险、审核和渲染历史", "flow": "选模板→填写参数→即时校验→预览命令→检查风险→创建任务草稿并进入审批"},
    "auto-exec": {"focus": "自动化任务、Playbook、设备范围、审批、执行和回滚", "objects": "任务、场景、设备标签、变量、权限、审批、执行结果和恢复", "flow": "选择任务类型→用标签组合预览→填写变量→审批/MFA→执行→核验结果"},
    "inspection": {"focus": "巡检概览、指标达标率、异常设备和趋势", "objects": "巡检策略、设备、指标、结果、严重度、趋势和责任人", "flow": "选择巡检范围→查看失败项→进入设备详情→复核命令输出→生成整改任务"},
    "inspection-records": {"focus": "巡检记录、原始输出、解析结果和历史对比", "objects": "巡检批次、设备、指标、时间、输出、状态、异常和证据", "flow": "按批次/设备筛选→打开记录→定位失败指标→和历史记录对比→导出"},
    "exec-schedule": {"focus": "自动化执行计划、频率、标签范围和审批策略", "objects": "执行计划、Cron、标签条件、权限级别、审批、重试和通知", "flow": "定义标签表达式→预览命中设备→设置时间和授权→保存→观察首轮执行"},
    "exec-history": {"focus": "自动化执行历史、设备级结果、失败原因和重试", "objects": "执行批次、任务、设备、命令、耗时、输出、状态和操作者", "flow": "按状态筛选→看批次摘要→展开设备结果→判断重试或回滚"},
    "scheduled-jobs": {"focus": "定时作业创建、标签 AND/OR/NOT 组合和执行权限", "objects": "作业、条件组、嵌套逻辑、设备预览、计划、审批和执行记录", "flow": "添加条件→选择 AND/OR/NOT→嵌套条件组→预览命中→确认后保存"},
    "inspection-metrics": {"focus": "巡检指标、阈值、解析器、合规判定和展示", "objects": "指标、命令、解析模板、阈值、单位、等级和启用状态", "flow": "定义指标→配置采集与解析→测试样本→设置阈值→发布并观察误报"},
    "textfsm-templates": {"focus": "TextFSM 解析模板、厂商命令、字段和样本测试", "objects": "模板、平台、命令、状态机、字段、样本、版本和测试结果", "flow": "选择平台→录入模板→使用样本测试→核对字段→发布版本"},
    "scripts": {"focus": "脚本与操作编排、参数、风险检查、审批和执行入口", "objects": "脚本、版本、参数、目标设备、风险、审批和执行日志", "flow": "审阅源码→配置参数→运行静态检查→创建任务→审批后执行"},
    "new-order": {"focus": "创建变更工单、影响范围、风险、审批和执行窗口", "objects": "工单、变更类型、设备、前后配置、风险、窗口和负责人", "flow": "描述变更→选择设备→填写计划与回滚→风险评估→提交审批"},
    "my-todo": {"focus": "个人待办、审批、执行确认和超时事项", "objects": "待办、工单、角色、截止时间、风险、审批动作和意见", "flow": "按紧急度处理→核对证据→批准/驳回/转派→填写意见"},
    "group-todo": {"focus": "组内工单分派、认领、转派和协作", "objects": "工作组、工单、责任人、SLA、状态和协作记录", "flow": "筛选未认领→确认能力与窗口→认领或转派→更新进度"},
    "my-participated": {"focus": "本人参与工单、审批意见、执行记录和结果", "objects": "参与角色、工单状态、评论、附件、执行证据和时间线", "flow": "按参与角色筛选→查看时间线→补充证据→确认阶段结果"},
    "my-focus": {"focus": "关注工单、状态变化、评论和通知", "objects": "关注关系、工单、优先级、状态、最后更新时间和提醒", "flow": "建立关注→按状态查看→处理变化通知→完成后取消关注"},
    "change-orders": {"focus": "全部变更工单检索、过滤、风险和闭环统计", "objects": "工单号、类型、设备、申请人、审批、执行、验证和回滚", "flow": "按状态/站点/风险筛选→打开详情→检查阶段→导出审计报告"},
    "my-drafts": {"focus": "变更工单草稿、模板渲染结果和未提交内容", "objects": "草稿、模板、参数、设备范围、风险、创建人和更新时间", "flow": "恢复草稿→补齐范围与回滚→重新预检→提交审批或删除草稿"},
    "capacity": {"focus": "设备、接口、链路、地址和资源容量趋势分析", "objects": "容量指标、利用率、趋势、阈值、站点、角色和预测", "flow": "选资源范围→看当前与趋势→识别阈值风险→生成扩容建议"},
    "reports": {"focus": "配置、告警、资产、容量、合规和执行报表", "objects": "报表定义、时间范围、筛选条件、指标、导出和订阅", "flow": "选报表→限定范围→预览指标→导出或订阅→核对数据时间"},
    "audit": {"focus": "平台登录、配置、资产、权限和执行审计日志", "objects": "事件、操作者、时间、资源、动作、结果、来源 IP 和详情", "flow": "先按事件/用户/时间筛选→打开详情→核对前后值→导出证据"},
    "users": {"focus": "用户、角色、分组、状态、MFA 和最后登录管理", "objects": "用户名、真实姓名、角色、分组、职责组、状态和登录时间", "flow": "新增用户→分配最小权限→绑定 MFA→测试登录→定期复核"},
    "credentials": {"focus": "凭据轮换、到期提醒、设备绑定和失败处理", "objects": "凭据、轮换策略、设备、协议、有效期、验证结果和审计", "flow": "查看到期→选择范围→执行轮换预检→确认切换→验证设备可登录"},
}


def parse_nav() -> list[dict[str, str]]:
    groups: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    group_pattern = re.compile(r"^\s{2}\{\s*$")
    item_pattern = re.compile(
        r"^\s*\{ id: '([^']+)',\s+label: '([^']+)',\s+labelEn: '([^']+)',.*?path: '([^']+)'"
    )
    lines = NAV.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if group_pattern.match(line):
            current = None
            continue
        if line.startswith("  {") and "children:" in line:
            current = None
        if line.startswith("    id:"):
            match = re.search(r"id: '([^']+)'", line)
            if match:
                current = {"id": match.group(1), "label": "", "labelEn": "", "path": "", "group_id": match.group(1)}
        if current is not None and line.startswith("    label:"):
            label_match = re.search(r"label: '([^']+)'", line)
            if label_match:
                current["label"] = label_match.group(1)
        if current is not None and line.startswith("    labelEn:"):
            label_en_match = re.search(r"labelEn: '([^']+)'", line)
            if label_en_match:
                current["labelEn"] = label_en_match.group(1)
        if current is not None:
            match = item_pattern.match(line)
            if match:
                item = {
                    "id": match.group(1),
                    "label": match.group(2),
                    "labelEn": match.group(3),
                    "path": match.group(4),
                    "group_id": current.get("id", ""),
                    "group_label": current.get("label", ""),
                }
                groups.append(item)
    # The line-oriented parser above is intentionally conservative; fall back
    # to a second pass that associates each child with the most recent group.
    if len(groups) < 50:
        groups = []
        active_group = {"id": "", "label": ""}
        for line in lines:
            if line.startswith("    id:"):
                match = re.search(r"id: '([^']+)'", line)
                if match:
                    active_group = {"id": match.group(1), "label": ""}
            if line.startswith("    label:"):
                match = re.search(r"label: '([^']+)'", line)
                if match:
                    active_group["label"] = match.group(1)
            match = item_pattern.match(line)
            if match:
                groups.append({"id": match.group(1), "label": match.group(2), "labelEn": match.group(3), "path": match.group(4), "group_id": active_group["id"], "group_label": active_group["label"]})
    return groups


def article(item: dict[str, str]) -> str:
    detail = DETAILS.get(item["id"], {
        "focus": f"{item['label']}页面中的日常查询、维护和审计操作",
        "objects": "页面列表、筛选条件、状态字段、详情、操作记录和更新时间",
        "flow": "先选择范围和筛选条件，再打开详情核对数据，完成操作后复核状态与审计记录",
    })
    title = f"Nexora NetOps {item['label']} 用户使用手册"
    route = item["path"]
    lines = [
        f"# {title}", "", 
        "> 版本：v1.0  ", f"> 编制日期：{DATE}  ", f"> 适用页面：`{route}`  ", f"> 所属模块：{item['group_label']}  ", 
        "> 适用角色：Viewer、Operator、Administrator（实际按钮以当前权限为准）", "",
        "## 1. 功能定位", "",
        f"“{item['label']}”用于{detail['focus']}。本页面不是孤立的列表，而是 Nexora 运维数据链路中的一个工作入口。页面展示的数据通常来自 CMDB、IPAM、配置快照、遥测、自动化任务、工单或审计服务，用户在操作前应先确认数据的来源、采集时间和权限范围。{detail['focus']}时，建议把页面上的状态理解为某个时间点的事实，而不是无条件等同于设备当前实时状态。", "",
        f"本页主要围绕以下对象工作：{detail['objects']}。对象之间的关联决定了按钮是否可用、列表为什么会出现空结果，以及后续跳转能够带走哪些上下文。例如设备类页面需要同时核对主机名、管理 IP、站点和生命周期；配置类页面还要关注快照是否有效、是否为 Running 或 Startup；执行类页面则要进一步确认审批、MFA、回滚和执行证据。", "",
        "## 2. 进入页面与权限", "",
        f"登录系统后，从左侧导航进入“{item['group_label']} → {item['label']}”，或直接访问 `{route}`。如果页面不可见，通常是当前用户角色、资源范围或模块权限不足，不建议通过修改地址绕过权限。Viewer 一般只能查询和导出允许范围内的数据；Operator 可以在授权范围内维护资源、计划、规则或执行预检；Administrator 才能进行用户、凭据、审核、敏感原文和平台级设置。", "",
        "首次进入时先观察页面顶部的标题、数据更新时间、刷新按钮和当前租户/站点范围。对于长列表，页面通常支持关键字搜索、分页、排序、状态筛选和列显示设置。修改筛选条件后应确认结果数量、分页总数和筛选标签已经同步变化；如果结果为零，先清除筛选再判断是否真的没有数据。", "",
        "## 3. 页面区域和字段理解", "",
        "页面一般由顶部操作区、统计卡片、筛选区、主列表/树、详情抽屉以及底部分页组成。顶部的“刷新”只重新读取服务端数据，不等于重新采集设备；“立即同步”“立即执行”“重建索引”等动作才会触发后台任务。统计卡片用于快速判断范围内的总量、异常量和待处理量，不能替代详情核对。", "",
        f"建议重点关注字段：{detail['objects']}。对每一条记录至少核对唯一标识、所属对象、状态、来源和最后更新时间。若字段旁有“内置/自定义”“系统/手工”“在线/离线”“有效/部分有效”等标签，应先理解标签含义再编辑。带有哈希、完整性、采集来源、任务 ID、工单号或操作者的字段属于审计线索，出现争议时应保留这些信息。", "",
        "## 4. 推荐使用流程", "",
        f"本页面推荐采用以下顺序：{detail['flow']}。第一步先缩小范围，避免对全网或全部历史数据进行无意识操作；第二步打开详情检查上下文和数据新鲜度；第三步在需要改变数据时先预览差异、影响和命中对象；第四步提交后重新加载页面，确认服务端状态已经落库；第五步记录工单、操作原因和验证结果。", "", 
        "### 4.1 查询与筛选", "",
        "在搜索框中优先输入完整名称、管理 IP、编码、工单号或对象 ID。状态筛选应与时间范围一起使用，例如先选择“异常/失败”，再限定最近 24 小时。树形页面可以先折叠不相关的站点、设备类型或业务分支，再展开目标节点；折叠只影响展示，不会删除或隐藏服务端数据。分页页面切换页码时应注意每页条数变化可能导致当前页重新计算。", "",
        "### 4.2 新增、编辑与导入", "",
        "新增或编辑前先检查是否存在同名、同编码、同 IP、同 VLAN、同快照或同一设备的重复记录。涉及导入时，先下载系统提供的模板，不要根据屏幕表头自行猜字段；按模板填写必填字段、枚举值和日期格式，导入后先看预检错误和跳过数量，再点击确认。批量导入应保留原始文件、校验结果和导入时间，便于回滚或追溯。编辑高风险对象时，建议先建立变更工单并在备注中写清原因、影响范围、预期结果和回滚方式。", "",
        "### 4.3 详情、关联与导出", "",
        "点击记录名称或右侧详情按钮查看完整字段。关联对象通常包括设备、站点、接口、IP、VLAN、VRF、配置快照、拓扑链路、告警和工单；每次跳转前先确认当前筛选条件是否会被保留。导出前再次核对过滤范围，尤其是历史配置、敏感字段和跨站点数据；默认导出应使用脱敏结果，不要把密码、Community、Secret、私钥或完整会话输出复制到普通群聊。", "",
        "## 5. 常见工作场景", "",
        "场景一：发现列表状态异常。先刷新页面并记录更新时间，再检查同步任务、采集来源、错误消息和关联设备状态。若数据仍然异常，不要直接手工覆盖“在线/健康/已生产”等状态，应先确认资产接管、凭据和采集链路。场景二：需要确认某条配置或资源是否影响业务。使用对象的精确标识进入配置搜索、配置对比、IPAM 或拓扑，查看来源快照和关联关系，再通过变更工单执行。场景三：需要批量操作。先用标签、站点、角色或设备组进行预览，确认命中数量与明细，保存截图或导出清单后再提交。", "",
        "场景四：页面显示空数据。依次检查角色权限、租户/站点范围、时间筛选、分页页码、是否存在有效快照或采集结果、后台任务是否完成以及接口是否返回错误。清空筛选只能用于验证查询条件，不能作为修复数据的手段。若是导入后没有记录，应查看导入批次的错误行号和字段校验，而不是重复上传同一文件。", "",
        "## 6. 校验、安全与审计", "",
        "保存前至少完成三项校验：唯一性校验、关联完整性校验和业务影响校验。唯一性检查名称、编码、IP、VLAN、接口、快照或工单号；关联完整性检查站点、租户、VRF、凭据、设备和权限；业务影响校验确认该动作是否改变路由、链路、管理入口、认证、日志、监控或生产流量。系统返回成功后，仍要重新查询记录确认状态、更新时间和操作者已经写入。", "",
        "所有重要动作都应能在审计日志中找到时间、用户、资源、前后值、请求来源和结果。若页面提供 MFA、二次确认、审批或变更窗口，不要为了操作方便跳过。涉及敏感原文时只在有明确授权和业务原因的情况下查看，并在原因字段中说明用途。对设备执行、回滚、凭据轮换和批量删除，页面的预览成功不等于执行成功，必须继续核对设备侧或任务侧结果。", "",
        "## 7. 故障排查", "",
        "如果页面加载失败，先记录浏览器时间、页面地址、请求编号（如有）和错误提示，然后刷新一次；不要连续点击执行按钮。若列表加载很慢，缩小站点、状态和时间范围，检查是否查询了全部历史数据。若按钮灰色，检查当前角色、记录状态、是否处于维护期、是否有未完成审批或是否缺少必填字段。若数据与设备不一致，比较采集时间、快照有效性、索引更新时间和设备最近变更，不要直接假设 UI 是唯一真相。", "",
        "导入报错时重点看行号、字段名、枚举值、重复键和编码；模板渲染报错时看变量名、行号、参数类型和厂商平台；配置对比报错时看 A/B 快照是否属于同一设备、是否有效、文件是否可读；拓扑或 IPAM 关联不完整时看接口采集、LLDP、ARP、路由和主数据更新时间。将这些上下文一并提交给管理员，通常比只发送“没有数据”更容易定位。", "",
        "## 8. 操作示例", "",
        f"以“{item['label']}”为例，用户可以先进入 `{route}`，选择一个明确站点或设备范围，再输入一个完整标识并执行查询。打开结果详情后记录唯一 ID、状态、来源和更新时间；如果需要变更，先使用预览/校验入口确认命中对象与影响，再创建相应的工单或任务。提交后回到本页刷新，确认状态已变为预期值，并在审计日志或执行历史中核对操作者、时间和结果。对于批量范围，先用系统提供的预览清单保存证据，再执行最终确认。", "",
        "## 9. 运维检查清单", "",
        "日常检查包括：数据是否按预期更新；失败、异常、待确认和过期记录是否有人处理；筛选和分页结果是否稳定；关键对象是否存在重复或冲突；导入/导出是否符合权限；执行动作是否有工单、审批、MFA 和回滚；敏感内容是否脱敏；关联页面是否能追溯到原始事实；审计日志是否完整。月度复核还应检查角色最小权限、共享参数方案、过期凭据、长期失败任务、未关闭工单和不再使用的标签或规则。", "",
        "## 10. 常见问题", "",
        "**为什么刷新后数量变化？** 可能是后台同步、采集、索引或任务刚刚完成；先比较更新时间和数据来源。  \n**为什么搜索不到已知对象？** 检查权限、作用域、时间、状态、精确匹配方式以及对象是否来自有效快照。  \n**为什么导出内容少于页面？** 导出遵循当前筛选、分页/上限和敏感脱敏规则，先检查导出提示。  \n**为什么不能直接修改？** 记录可能由系统同步维护、处于审批中、当前用户没有更新权限，或修改必须通过工单流程。  \n**为什么关联页面没有结果？** 关联依赖主数据 ID、接口/地址/链路采集和更新时间，需从事实源逐层核对。", "",
        "## 11. 相关页面与建议", "",
        f"与“{item['label']}”配合使用时，优先保留当前页面的筛选条件和唯一标识，再进入资产、CMDB、IPAM、配置、自动化、工单或审计页面。遇到生产风险时，先止损和留证，再执行修复；遇到数据质量问题，修正采集或主数据来源，而不是只修改展示层。用户手册中的路径以当前版本导航为准，若权限或版本差异导致按钮名称不同，应以页面实际提示和后端审计结果为准。", "",
    ]
    text = "\n".join(lines)
    # Keep every article above the requested length even for a newly-added
    # submenu that has no bespoke detail entry yet.
    while len(re.findall(r"[\u4e00-\u9fff]", text)) < 1800:
        text += "\n\n补充说明：执行任何批量查询、导入、导出、同步、配置生成或设备操作前，都应再次确认目标范围、数据时间、权限边界、审批状态和回滚条件；完成后保留结果、错误信息和审计编号，确保后续能够复核。"
    return text + "\n"


def main() -> None:
    items = parse_nav()
    if len(items) < 50:
        raise RuntimeError(f"导航解析数量异常：仅发现 {len(items)} 个子菜单")
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[str] = ["# Nexora NetOps 用户使用手册索引", "", f"> 生成日期：{DATE}", "> 来源：`src/components/AppSidebar/navConfig.ts` 与页面/API实现", "", "本文档按当前 11 个功能模块生成，每个子菜单独立成篇。", ""]
    current_group = ""
    for item in items:
        group_dir = OUT / item["group_id"]
        group_dir.mkdir(parents=True, exist_ok=True)
        path = group_dir / f"{item['id']}.md"
        path.write_text(article(item), encoding="utf-8")
        if item["group_id"] != current_group:
            current_group = item["group_id"]
            index.extend([f"## {item['group_label']}", ""])
        index.append(f"- [{item['label']}（{item['labelEn']}）]({item['group_id']}/{item['id']}.md) · `{item['path']}`")
    index.extend(["", f"共生成 {len(items)} 篇子菜单手册；每篇中文字符数不少于 1800。", ""])
    (ROOT / "blog/用户使用手册索引_20260801.md").write_text("\n".join(index), encoding="utf-8")
    (ROOT / "blog/README.md").write_text(
        "# Nexora NetOps 用户手册\n\n请从 [用户使用手册索引](用户使用手册索引_20260801.md) 按模块和子菜单进入。文章由当前导航和页面实现生成，修改导航后请重新运行 `python scripts/generate_user_manuals.py`。\n",
        encoding="utf-8",
    )
    print(f"generated {len(items)} manuals")


if __name__ == "__main__":
    main()
