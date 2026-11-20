# 实施计划 - Nexora NetOps 综合问题修复与 UI 优化

本计划针对系统当前发现的思科备份出错、IPAM 接口未纳入及掩码缺失、华三设备事实库同步失败、资产与告警工作台 UI 拥挤、以及多 Site 拓扑乱飞和链路缺失等 6 个核心问题，进行联合代码修复和 UI 精美重构。

- 任务目标：修复特权备份账号读取、对齐 IPAM 接口简写全称、修复华三 TextFSM 匹配与路由同步、分页总是可见、卡片化标签布局、毛玻璃告警工作台、拓扑跨 Site 链路呈现与分簇。
- 实施时间：2026-07-25 20:38
- 实施序号：01

## 拟修改文件

### 后端核心逻辑修复
- [MODIFY] [backend/api/configs.py](file:///d:/netops/netsops-main/backend/api/configs.py)
- [MODIFY] [backend/services/ipam_service.py](file:///d:/netops/netsops-main/backend/services/ipam_service.py)
- [MODIFY] [backend/services/ip_locator_service.py](file:///d:/netops/netsops-main/backend/services/ip_locator_service.py)
- [NEW] [data/textfsm_templates/hp_comware_display_interface_brief.textfsm](file:///d:/netops/netsops-main/data/textfsm_templates/hp_comware_display_interface_brief.textfsm)

### 前端 UI 美化与交互优化
- [MODIFY] [src/pages/IPVlan/PrefixManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/PrefixManagementTab.tsx)
- [MODIFY] [src/pages/IPVlan/IPAddressTab.tsx](file:///d:/netops/netsops-main/src/pages/IPVlan/IPAddressTab.tsx)
- [MODIFY] [src/pages/IPLocatorPage.tsx](file:///d:/netops/netsops-main/src/pages/IPLocatorPage.tsx)
- [MODIFY] [src/pages/TagManagementTab.tsx](file:///d:/netops/netsops-main/src/pages/TagManagementTab.tsx)
- [MODIFY] [src/pages/AlertDeskTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertDeskTab.tsx)
- [MODIFY] [src/pages/AlertHistoryTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertHistoryTab.tsx)
- [MODIFY] [src/pages/AlertRulesTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertRulesTab.tsx)
- [MODIFY] [src/pages/AlertMaintenanceTab.tsx](file:///d:/netops/netsops-main/src/pages/AlertMaintenanceTab.tsx)
- [MODIFY] [src/hooks/useTopology.ts](file:///d:/netops/netsops-main/src/hooks/useTopology.ts)
- [MODIFY] [src/components/TopologyGraph.tsx](file:///d:/netops/netsops-main/src/components/TopologyGraph.tsx)

## 实施步骤

1. **后端物理层与解析引擎修复**
   - 修复 backend/api/configs.py 获取设备的 SELECT 语句，添加 admin_credential_id。
   - 编写自定义 data/textfsm_templates/hp_comware_display_interface_brief.textfsm，添加过滤 ^\s*[\[<].*$$。
   - 在 backend/services/ipam_service.py 中引入 normalize_interface_name 解决掩码缺失。
   - 修改 backend/services/ip_locator_service.py 支持 hp_comware 平台 OSPF/BGP 同步。

2. **前端 UI 与功能重构**
   - 优化 PrefixManagementTab.tsx 未纳入接口的滚动条和药丸 Tag。
   - 在 IPAddressTab.tsx 中为网段引入 16x16 IP 占用矩阵视图。
   - 在 IPLocatorPage.tsx 中将 NSoT 分页设置为总是可见。
   - 重构 TagManagementTab.tsx 标签列表为四列网格卡片式布局。
   - 全面美化告警工作台（当前告警、历史告警、规则和维护期）行高、Badge、Modal 弹窗和快速操作。

3. **拓扑多 Site 联合渲染优化**
   - 修改 useTopology.ts 保留跨 site 对端设备，标记为 is_external。
   - 修改 TopologyGraph.tsx，将外部节点/链路进行不透明度淡化，提升 D3 力聚拢强度。

## 验证计划
- 运行 pytest 测试。
- 运行 npm run lint 验证前端规范。
- 手动查看备份、矩阵视图、卡片布局和拓扑分簇呈现。
