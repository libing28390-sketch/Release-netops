# 执行走查与验证报告：巡检与网络事实库 (NSOT) 架构解耦与整改

## 1. 完成摘要

已彻底完成**自动化巡检系统（Inspection）**与**网络事实库（NSOT / Network Source of Truth）**的架构与交互解耦：
1. **巡检页面纯粹化 (`/automation/records` & `/automation/inspections`)**：
   - 彻底移除了 [`src/pages/InspectionTab.tsx`](file:///d:/nexora/nexora-private/src/pages/InspectionTab.tsx) 顶部错误嵌入的“设备采集计划（ARP/MAC/路由/LLDP等开关）”卡片及冗余状态/请求。
   - 巡检概览与记录模块聚焦于：**全网健康度打分（ScoreGauge）、设备健康状态指标看板、历史健康趋势图、巡检批次管理、异常设备隐患分析及巡检报告（Excel/PDF/HTML）导出下载**。
2. **事实库能力归位 (`/assets/nsot`)**：
   - 在 [`src/pages/IPLocatorPage.tsx`](file:///d:/nexora/nexora-private/src/pages/IPLocatorPage.tsx) 的 NSOT 工具栏增加了 **“采集策略与能力 (Collection Policy)”** 交互入口。
   - 新增了设备级采集能力策略配置模态窗（支持左侧设备检索切换，右侧分组管理“基础与接口事实”、“二层拓扑与转发表项”、“三层路由与协议状态”、“推导计算与 IPAM 事实”四大维度的采集能力开关），并支持一键恢复角色默认策略。
3. **底层契约与解耦校验**：
   - 修复了 `ip_locator_service._collect_live_interface_status` 与 `interface_collection_service._status_record` 的 5-tuple 解构契约。
   - 前端 TypeScript 编译与后端 37 项自动化回归测试全量通过。

---

## 2. 实际修改文件

- [`src/pages/InspectionTab.tsx`](file:///d:/nexora/nexora-private/src/pages/InspectionTab.tsx)：移除 `collectionPlans` 状态、`fetchCollectionPlans`、`updateCollectionPlan` 及顶部冗余的“设备采集计划”卡片。
- [`src/pages/IPLocatorPage.tsx`](file:///d:/nexora/nexora-private/src/pages/IPLocatorPage.tsx)：在 NSOT 事实库工具栏增加采集策略按钮，实现 NSOT 设备采集能力策略模态窗，提升 token 声明位置以确保作用域安全。
- [`backend/services/ip_locator_service.py`](file:///d:/nexora/nexora-private/backend/services/ip_locator_service.py)：修复 `_collect_live_interface_status` 解构 5-tuple。
- [`backend/tests/vendor_audit/test_interface_collection_contract.py`](file:///d:/nexora/nexora-private/backend/tests/vendor_audit/test_interface_collection_contract.py)：适配 `_status_record` 5-tuple 返回。
- [`backend/tests/vendor_audit/test_collection_regressions.py`](file:///d:/nexora/nexora-private/backend/tests/vendor_audit/test_collection_regressions.py)：适配 `_status_record` 5-tuple 返回。

---

## 3. 验证命令与结果

### 3.1 前端类型与语法门禁
```bash
npm run lint (tsc --noEmit)
# 结果：Process completed with exit code 0, 0 errors.
```

### 3.2 后端多厂商事实库与接口采集回归
```bash
.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit/test_ip_locator_arp_contract.py backend/tests/vendor_audit/test_interface_collection_contract.py backend/tests/vendor_audit/test_collection_regressions.py
# 结果：37 passed in 26.39s (100% 通过)
```

---

## 4. 剩余风险与后续建议

- **风险评估**：零风险。解耦后各模块职责边界清晰，巡检和事实库数据流独立运作。
- **后续建议**：
  1. 可在定时作业（`/automation/scheduled-jobs`）新建作业时，进一步增强 `inspection` 和 `nsot` 作业类型的 UI 说明，引导运维人员正确创建不同周期的任务。
