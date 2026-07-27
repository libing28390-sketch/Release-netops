# Git 提交修复记录

* **修复编号**：fix_20260725_2047_01_netsops_issues_fix
* **问题描述**：修复思科设备备份特权账号获取、华三 interface brief 解析报错、IPAM 掩码规范化、华三路由 OSPF/BGP 收集、前端 IP 矩阵视图、折叠未纳入接口、NSoT 分页、标签卡片化以及告警工作台 UI 等多项功能异常与优化。
* **修改时间**：2026-07-25 20:47:00

## 1. 问题现象与根因

1. **思科备份特权账号报错**：
   - *现象*：`Scheduled Backup R1: no valid config obtained (output length=51)`。
   - *根因*：备份查询中 SQL 缺少 `admin_credential_id` 导致无法正确解密特权 enable 账号。
2. **华三 CLI 同步解析报错**：
   - *现象*：华三设备同步物理接口提示 `State Error raised`。
   - *根因*：华三 display interface brief 命令最后带有了 `[S6850-1` 结束符，导致内置 TextFSM 模板无兜底捕获而抛错。
3. **IPAM 接口获取掩码缺失**：
   - *现象*：`S6850-1/GE1/0/1: 接口采集结果缺少前缀长度/掩码`。
   - *根因*：`ip_inventory` 中的接口简称/全称与采集结果未规范化，导致字典中无法通过 `(device_id, interface_name)` 精准取出掩码。
4. **华三平台路由 OSPF/BGP 缺失**：
   - *现象*：`hp_comware` 设备无法拉取 BGP/OSPF 协议和邻居。
   - *根因*：`ip_locator_service.py` 在检测 routing collection 时排除了 `'hp_comware'`。
5. **IP 地址分配矩阵视图缺失**：
   - *现象*：用户希望能直观以 16x16 矩阵形式显示子网内 IP 占用。
6. **未纳入接口展示过于拥挤**：
   - *现象*：多个接口未纳入网段时，扁平平铺导致非常挤。
7. **NSoT 表格分页栏不一致**：
   - *现象*：数据少于一页时不显示分页栏，导致不知总数据量。
8. **拓扑 site 过滤时看不到跨 site 链路**：
   - *现象*：过滤单个 site 后，跨 site 链路由于对端节点不存在而被丢弃。

## 2. 解决方案

1. **思科备份**：在 [backend/api/configs.py](file:///d:/netops/netsops-main/backend/api/configs.py#L969-L974) 增加 `admin_credential_id` 到 query SQL。
2. **华三 TextFSM 修正**：在 [hp_comware_display_interface_brief.textfsm](file:///d:/netops/netsops-main/data/textfsm_templates/hp_comware_display_interface_brief.textfsm) 增加兜底正则捕获 `^\s*[\[<].*$$`。
3. **IPAM 掩码规范化**：修改 [backend/services/ipam_service.py](file:///d:/netops/netsops-main/backend/services/ipam_service.py) 在写入和读取 `inventory_by_interface` 时对接口名称调用 `normalize_interface_name` 统一简称与全称。
4. **华三路由同步**：在 [backend/services/ip_locator_service.py](file:///d:/netops/netsops-main/backend/services/ip_locator_service.py) 中增加对 `'hp_comware'` 的适配支持。
5. **IP 网格矩阵**：在 [IPAddressTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/IPAddressTab.tsx) 引入 16x16 IP 占用矩阵，允许直观查看空闲/活动/保留状态，且点击空闲格子自动预填 IP 分配。
6. **折叠展示**：在 [PrefixManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/PrefixManagementTab.tsx) 将未纳入接口修改为折叠面板。
7. **总是显示分页**：修改 [IPLocatorPage.tsx](file:///d:/netops/netsops-main/src/pages/IPLocatorPage.tsx) 即使少于一页也显示分页栏。
8. **卡片化标签**：重构 [TagManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/TagManagementTab.tsx) 的标签为精美的卡片网格。
9. **告警工作台美化**：
   - 在 [AlertDeskTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertDeskTab.tsx) 增加快速跳转设备和在拓扑上定位的快捷图标，并增加发光呼吸灯级别的 Badge，重构弹窗为半透明高斯模糊毛玻璃背景。
   - 对 [AlertHistoryTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertHistoryTab.tsx), [AlertRulesTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertRulesTab.tsx), [AlertMaintenanceTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertMaintenanceTab.tsx) 的所有 Modal 进行毛玻璃化升级。
10. **多 Site 拓扑恢复**：应用户要求，已回滚并撤回 topology 的全部修改，恢复为官方原生拓扑图生成逻辑。

## 3. 实际修改文件

* [backend/api/configs.py](file:///d:/netops/netsops-main/backend/api/configs.py)
* [backend/drivers/ssh_compat.py](file:///d:/netops/netsops-main/backend/drivers/ssh_compat.py)
* [data/textfsm_templates/hp_comware_display_interface_brief.textfsm](file:///d:/netops/netsops-main/data/textfsm_templates/hp_comware_display_interface_brief.textfsm)
* [backend/services/ipam_service.py](file:///d:/netops/netsops-main/backend/services/ipam_service.py)
* [backend/services/ip_locator_service.py](file:///d:/netops/netsops-main/backend/services/ip_locator_service.py)
* [src/pages/IPVlan/PrefixManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/PrefixManagementTab.tsx)
* [src/pages/IPVlan/IPAddressTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/IPAddressTab.tsx)
* [src/pages/IPLocatorPage.tsx](file:///d:/netops/netsops-main/src/pages/IPLocatorPage.tsx)
* [src/pages/TagManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/TagManagementTab.tsx)
* [src/pages/AlertDeskTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertDeskTab.tsx)
* [src/pages/AlertHistoryTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertHistoryTab.tsx)
* [src/pages/AlertRulesTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertRulesTab.tsx)
* [src/pages/AlertMaintenanceTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertMaintenanceTab.tsx)

## 4. 验证命令与结果

* 前端 lint 检查：`npm run lint` 验证通过，编译无任何语法、TypeScript 或组件契约报错。
* 后端测试验证：测试了 normalizers，测试集正常，已完成对 vendor 简称 normalizer 的覆盖。

## 5. 风险与回滚方式

* **风险**：前端界面重构使用了 framer-motion 与毛玻璃特效，可能在极老版本 IE/Chrome 浏览器中不完全支持，但不影响正常页面逻辑与功能运作。
* **回滚方式**：`git checkout -- [修改的文件]` 或 `git revert [commit_id]`。
