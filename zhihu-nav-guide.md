# Nexora 知乎系列文章 — 导航索引

> 以下是 Nexora 网络自动化平台的系列介绍文章，按功能模块划分，每篇带截图讲解。

---

## 文章目录

| # | 文章 | 覆盖模块 | 建议阅读顺序 |
|---|------|---------|-------------|
| 0 | [项目整体介绍](zhihu.md) | 技术栈、架构、功能总览、性能数据 | 必读（入口） |
| 1 | [实时监控篇](zhihu-part1.md) | 仪表盘 / 监控中心 / 网络拓扑 / 健康检测 | 基础篇 |
| 2 | [告警处置篇](zhihu-part2.md) | 告警信息 / 告警规则 / 维护期 | 基础篇 |
| 3 | [资产管理篇](zhihu-part3.md) | 设备列表 / IP-VLAN / 资产管理 / 标签系统 | 核心篇 |
| 4 | [自动化篇](zhihu-part4.md) | 直接执行 / 方案库 / 执行历史 | 进阶篇 |
| 5 | [配置中心篇](zhihu-part5.md) | 备份历史 / 差异对比 / 配置搜索 / 配置漂移 | 进阶篇 |
| 6 | [合规审计篇](zhihu-part6.md) | 合规检测 / 修复建议 / 自动化修复 | 高级篇 |
| 7 | [容量与报表篇](zhihu-part7.md) | 容量规划 / 报表中心 | 运营篇 |
| 8 | [平台管理篇](zhihu-part8.md) | 审计日志 / 平台配置 / 用户管理 | 管理篇 |

---

## 按导航栏结构索引 (6 大主菜单)

### 1. 实时监控 (Real-time)
- 仪表盘 → [第一篇](zhihu-part1.md#1-仪表盘)
- 监控中心 → [第一篇](zhihu-part1.md#2-监控中心)
- 网络拓扑 → [第一篇](zhihu-part1.md#3-网络拓扑)
- 健康检测 → [第一篇](zhihu-part1.md#4-健康检测)

### 2. 告警处置 (Alerts)
- 告警信息 → [第二篇](zhihu-part2.md#1-告警信息-alert-desk)
- 告警规则 → [第二篇](zhihu-part2.md#2-告警规则-alert-rules)
- 维护期 → [第二篇](zhihu-part2.md#3-维护期-maintenance)

### 3. 资产与配置 (Inventory)
- 设备列表 → [第三篇](zhihu-part3.md#1-设备列表-inventory)
- IP/VLAN 管理 → [第三篇](zhihu-part3.md#2-ipvlan-管理)
- 资产管理 → [第三篇](zhihu-part3.md#3-资产管理-assets)
- 标签管理 → [第三篇](zhihu-part3.md#4-标签管理-tags)

### 4. 自动化与合规 (Automation)
- **自动化子模块**：
  - 直接执行 → [第四篇](zhihu-part4.md#1-直接执行-direct-execution)
  - 方案库 → [第四篇](zhihu-part4.md#2-方案库-scenario-library)
  - 执行历史 → [第四篇](zhihu-part4.md#3-执行历史-execution-history)
- **配置与合规子模块**：
  - 备份历史 / 差异对比 / 搜索 → [第五篇](zhihu-part5.md)
  - 合规审计 → [第六篇](zhihu-part6.md)

### 5. 容量与报表 (Capacity & Reports)
- 容量规划 → [第七篇](zhihu-part7.md#1-容量规划-capacity-planning)
- 报表中心 → [第七篇](zhihu-part7.md#2-报表中心-report-center)

### 6. 平台管理 (Management)
- 审计日志 → [第八篇](zhihu-part8.md#1-审计日志-audit-logs)
- 平台配置 → [第八篇](zhihu-part8.md#2-平台配置-configuration)
- 用户管理 → [第八篇](zhihu-part8.md#3-用户管理-user-management)

---

## 截图说明

所有截图均来自项目内置的 Playwright 自动化测试脚本（`tests/poc_test_v3.py`），确保 UI 展示与真实版本完全一致。

截图目录：`tests/poc_screenshots/`
