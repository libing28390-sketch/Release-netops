# CMDB 设备接口主骨架完成报告

## 完成摘要

已完成企业级整改路线图 `CMDB-000` 的第一段落地：将 `devices + interfaces` 纳入 CMDB 主入口，新增后端只读聚合 API，并在前端 CMDB 页面加入“设备骨架”和“接口骨架”两个只读视图。

本次未修改数据库结构，未开放设备/接口的 CMDB 写操作，避免影响现有资产、设备、接口管理流程。

## 修改文件

- `backend/services/cmdb_service.py`
- `backend/api/cmdb.py`
- `src/pages/CmdbManagementTab.tsx`
- `src/utils/routeContext.ts`
- `src/components/AppSidebar/navConfig.ts`
- `docs/plans/plan_CMDB设备接口主骨架.md`
- `docs/walkthrough/walkthrough_CMDB设备接口主骨架.md`

## 后端实现

新增只读 CMDB 聚合接口：

- `GET /api/cmdb/devices`
- `GET /api/cmdb/interfaces`

`/api/cmdb/devices` 返回设备作为 CMDB 网络节点的视图，包含：

- 设备基础字段：hostname、management IP、platform、role、status、site、lifecycle。
- 资产关联字段：asset tag、serial number、rack、management/business IP。
- 关系计数：interface count、IP count、topology link count。

`/api/cmdb/interfaces` 返回接口作为 CMDB 网络子资源的视图，包含：

- 接口基础字段：interface name、admin/oper status、MAC、speed、switchport、VLAN、VRF。
- 设备上下文：device hostname、device IP、platform、device status。
- 关系计数：IP count、topology link count。

## 前端实现

CMDB 页面新增两个 tab：

- 设备骨架 / Devices
- 接口骨架 / Interfaces

只读行为：

- 隐藏“新建记录”按钮。
- 隐藏编辑/删除操作列。
- 保留搜索、刷新、分页。
- 设备名称和接口所属设备可跳转到现有 `/assets/devices` 页面。

路由新增：

- `/cmdb/devices`
- `/cmdb/interfaces`

侧边栏 CMDB 分组新增：

- 设备骨架
- 接口骨架

## 验证结果

已通过：

```powershell
python -m py_compile backend\api\cmdb.py backend\services\cmdb_service.py
git diff --check -- backend\api\cmdb.py backend\services\cmdb_service.py src\pages\CmdbManagementTab.tsx src\utils\routeContext.ts src\components\AppSidebar\navConfig.ts docs\plans\plan_CMDB设备接口主骨架.md
```

浏览器只读验证已通过：

- `/cmdb/devices` 可渲染“设备骨架”入口和表头：设备名称、管理IP、平台、角色、状态、站点、资产标签、接口数、IP数、链路数。
- `/cmdb/interfaces` 可渲染“接口骨架”入口和表头：接口名称、所属设备、设备IP、运行状态、管理状态、MAC、交换模式、Access VLAN、VRF、IP数、链路数。
- 两个只读页面均未显示“新建记录”按钮。

`npm run lint` 已执行，但被既有无关 TypeScript 错误阻塞：

```text
src/pages/RackManagement/index.tsx(1163,21): error TS2322:
Type '(deviceId: string, newStartU: number) => void' is not assignable to type
'(deviceId: string, newStartU: number) => Promise<void>'.
```

本次没有修改 `src/pages/RackManagement/index.tsx`，该错误不属于本任务变更范围。

## 未执行验证

- 未执行 `npm run build`。

原因：`npm run lint` 已被既有 TypeScript 错误阻塞，build 预计会遇到同一类型检查问题。为避免扩大范围，本任务未修改无关 RackManagement 文件。

## 剩余风险

- 新增聚合 SQL 仍使用现有文本字段，例如 `devices.site`、`ip_addresses.interface_name`，后续仍需执行字段权威收敛。
- 当前设备/接口 CMDB 视图是只读入口，不替代资产管理和设备管理页面。
- 侧边栏 `Network` 图标在当前 AppSidebar 图标映射中已有历史使用，但该映射本身不完整，若页面显示空图标，后续可统一补齐图标映射。

## 下一步建议

建议下一段执行 `CMDB-002：资产、设备、接口关系重构` 的前置小任务：

1. 明确 `physical_assets` 与 `devices` 的字段权威边界。
2. 设计 `devices.site_id` 与 `sites.id` 的迁移路径。
3. 设计 `ip_addresses.interface_id` 逐步替代 `interface_name` 的迁移路径。
