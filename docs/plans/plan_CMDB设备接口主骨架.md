# CMDB 设备接口主骨架实施计划

## 任务目标

执行企业级整改路线图中的 `CMDB-000`，将 `devices + interfaces` 明确纳入 CMDB 主入口，形成网络 CMDB 的只读主骨架视图。

本阶段不修改数据库结构，不开放设备/接口的 CMDB CRUD，只新增只读聚合 API 和前端入口，降低风险。

## 现状与问题

当前底层数据模型已经具备：

- `devices`：网络可管理对象主表。
- `interfaces`：接口主表，并通过 `device_id` 归属设备。
- `topology_links`、`ip_addresses`、监控/巡检/配置等模块均依赖 device/interface。

但当前 `/api/cmdb/*` 和 CMDB 页面主要覆盖 credentials、sites、racks、VRFs、VLANs、tenants，尚未把设备与接口作为 CMDB 主资源呈现。

## 影响范围

- `backend/api/cmdb.py`
- `src/pages/CmdbManagementTab.tsx`
- `src/utils/routeContext.ts`
- `src/components/AppSidebar/navConfig.ts`
- `docs/walkthrough/walkthrough_CMDB设备接口主骨架.md`

## 拟修改内容

### 后端

新增只读接口：

- `GET /api/cmdb/devices`
- `GET /api/cmdb/interfaces`

接口目标：

- 以 CMDB 视角展示设备、资产、站点、接口数量、IP 数量、链路数量等关系。
- 以 CMDB 视角展示接口、所属设备、接口状态、MAC、VLAN、VRF、绑定 IP 数量、链路数量。

### 前端

在 CMDB 页面新增两个 tab：

- 设备骨架
- 接口骨架

只读行为：

- 隐藏“新建记录”按钮。
- 隐藏编辑/删除操作列。
- 保留搜索、分页、刷新。
- 设备行可跳转到现有 `/assets/devices` 页面。

### 路由/导航

新增路径识别：

- `/cmdb/devices`
- `/cmdb/interfaces`

在侧边栏 CMDB 分组中加入入口。

## 验证计划

- 后端：运行与 CMDB API 相关的测试，若无专用测试则至少执行 Python 编译检查。
- 前端：运行 `npm run lint`。
- 构建：运行 `npm run build`，确认新增 tab 不破坏路由和懒加载。
- 手工：浏览器访问 `/cmdb/devices`、`/cmdb/interfaces`，确认表格、搜索、分页、刷新可用，且没有写操作入口。

## 风险与回滚

风险：

- 聚合 SQL 可能受历史数据空值影响。
- 只读 tab 复用现有 CRUD 表格组件，可能误露写操作。
- 侧边栏新增入口可能影响导航分组显示。

回滚：

- 移除新增 `/api/cmdb/devices`、`/api/cmdb/interfaces`。
- 移除前端 `devices/interfaces` tab 和路由识别。
- 移除侧边栏入口。
