# Nexora 模块与子功能文档总览

本文档按当前实际侧栏 `src/components/AppSidebar/navConfig.ts` 建立，不使用旧编号或假设菜单。

- 一级模块：11
- 子功能：62
- 模块 README：11
- 子功能文档：124（每项包含功能介绍与使用指南）
- 总文档数：136
- 数据库：PostgreSQL

逐页面路由、功能介绍、使用指南和真实截图的对应关系见
[`../MODULES_OVERVIEW.md`](../MODULES_OVERVIEW.md)；浏览器验收过程见
[`../BROWSER_VALIDATION.md`](../BROWSER_VALIDATION.md)。

| 模块 | 子功能数 | 文档 |
|---|---:|---|
| 实时监控 | 6 | [模块说明](./realtime/README.md) |
| 终端接入 | 2 | [模块说明](./terminal-access/README.md) |
| 告警处置 | 4 | [模块说明](./alerts/README.md) |
| 资产与配置 | 7 | [模块说明](./assets-config/README.md) |
| CMDB基础数据 | 10 | [模块说明](./cmdb-group/README.md) |
| IPAM | 7 | [模块说明](./ipam-group/README.md) |
| 配置管理 | 5 | [模块说明](./config-mgmt/README.md) |
| 自动化 | 9 | [模块说明](./automation/README.md) |
| 工单管理 | 7 | [模块说明](./tickets/README.md) |
| 容量与报表 | 2 | [模块说明](./capacity/README.md) |
| 平台管理 | 3 | [模块说明](./management/README.md) |

## 维护规则

导航新增、删除或改名时，必须同步更新对应模块 README、功能介绍、使用指南、真实页面截图和验收记录。文档不得描述尚未存在的按钮或伪造测试结果。
