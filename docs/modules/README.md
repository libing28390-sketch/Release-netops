# Nexora 模块与导航索引

本目录按当前侧栏配置维护：`src/components/AppSidebar/navConfig.ts`。下表数量按各模块的末级菜单入口计数，包含角色受限的入口，不计“监控报表”“IPAM 工作台”“地址空间”“操作管理”“对象存储”等仅用于分组的父菜单。

- 一级模块：12
- 末级菜单入口：83
- 模块 README：12
- 生产数据库：PostgreSQL

| 模块 | 末级菜单入口数 | 模块说明 |
|---|---:|---|
| 实时监控 | 9 | [模块说明](./realtime/README.md) |
| 终端接入 | 4 | [模块说明](./terminal-access/README.md) |
| 告警处置 | 4 | [模块说明](./alerts/README.md) |
| 资产与配置 | 6 | [模块说明](./assets-config/README.md) |
| CMDB 基础数据 | 10 | [模块说明](./cmdb-group/README.md) |
| IPAM | 7 | [模块说明](./ipam-group/README.md) |
| 配置管理 | 5 | [模块说明](./config-mgmt/README.md) |
| 自动化 | 10 | [模块说明](./automation/README.md) |
| 工单管理 | 8 | [模块说明](./tickets/README.md) |
| 容量与报表 | 2 | [模块说明](./capacity/README.md) |
| AI 中心 | 12 | [模块说明](./ai-center-group/README.md) |
| 平台管理 | 6 | [模块说明](./management/README.md) |

各模块 README 列出当前末级导航名称和路由。菜单可见性还受 `navConfig.ts` 中的角色要求约束；这里的数量是配置总数，不代表任一账号都能看到全部入口。

## 维护规则

导航或路由变更后，先对照 `navConfig.ts` 和页面路由处理代码再更新本索引及对应模块 README。只链接已存在且主题相符的子文档；没有对应文档时留空。具体路由以本索引和当前源码为准。源码或文档核对不等同于浏览器验收，只有存在可复核的浏览器记录时才能报告浏览器验收完成。
