# 平台注册归属与平台 CRUD 验证记录

## 1. 变更目标

将平台注册作为自动化能力的一部分，入口统一为 `/automation/platforms`，并补齐平台档案的增删改查约束：

- 菜单名称统一为“平台注册”，使用平台图标，放在“自动化”菜单下，与 TextFSM 注册表、动作映射和 Release 生命周期保持同一工作流。
- 系统内置平台可查看、可绑定设备和执行已发布能力，但平台档案及 Release 配置只读。
- 自定义平台支持创建、编辑和删除；删除采用归档语义，保留历史 Release 与审计关联。
- 已绑定设备的平台禁止删除；绑定设备时平台身份字段（编码、连接驱动、解析平台）不可修改，但名称、厂商和说明仍可维护。
- 编辑、删除和设备绑定按平台档案行串行化，避免并发绑定绕过绑定设备保护。

## 2. 主要实现

- 前端菜单与路由：`src/components/AppSidebar/navConfig.ts`、`src/utils/routeContext.ts`、`src/App.tsx`
- 平台注册界面：`src/pages/PlatformRegistryTab.tsx`
- 创建/编辑向导中的厂商改为从平台注册目录下拉选择，编辑旧数据时仍保留当前厂商值。
- 资产录入厂商目录按“网络设备厂商 / 网络安全厂商”分组，补充 DCN、FiberHome、Nokia、Aruba、Extreme、Ruckus、MikroTik、Ubiquiti、D-Link、TP-Link、Hillstone、Sangfor、Check Point、Sophos、SonicWall、WatchGuard、F5、A10、Barracuda、Venustech、NSFOCUS、Topsec、Qi An Xin 等常见品牌；厂商目录不等同于已实现的自动化驱动能力。
- 资产导入模板同步扩展网络/安全厂商与平台字段：`public/templates/asset_import_template.xlsx` 的网络设备下拉改为引用“下拉选项”工作表，突破 Excel 内联列表长度限制；“参数可选值参考”同时列出标准值、别名和归一化结果。浏览器兜底模板生成器也复用同一目录，并继续兼容中英文导入值。
- 设备录入平台选择与绑定：`src/components/DeviceFormModal.tsx`、`backend/api/devices.py`
- 平台 CRUD API：`backend/api/platform_registry.py`
- 平台 CRUD、归档和 Release 只读边界：`backend/services/platform_registry_service.py`
- 系统平台绑定仍可用、归档平台禁止绑定：`backend/services/platform_identification_service.py`
- 平台 `update/delete` 权限动作：`backend/core/rbac.py`

## 3. API 行为

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/api/platform-registry/profiles` | 返回当前权限范围内的平台及绑定设备数量 |
| POST | `/api/platform-registry/profiles` | 创建自定义平台 |
| PUT | `/api/platform-registry/profiles/{profile_id}` | 更新自定义平台；绑定设备时锁定身份字段 |
| DELETE | `/api/platform-registry/profiles/{profile_id}` | 无绑定设备时将自定义平台归档；系统平台或有绑定设备时拒绝 |

错误码包括 `SYSTEM_PROFILE_READ_ONLY`、`PLATFORM_BOUND_DEVICES`、`PLATFORM_IDENTITY_LOCKED` 和 `PROFILE_ARCHIVED`。

## 4. PostgreSQL 兼容修复

- `prefixes.prefix_cidr` 是现有非空字段；修正 vendor audit 测试夹具，写入完整 CIDR，不放宽 schema 约束。
- `interfaces.is_l3` 是现有整数标志；在 VLAN、接口采集、调度器、库存仓储和 IPAM 查询边界统一使用 `1/0`，避免 PostgreSQL 拒绝 Python/SQL boolean。
- 不新增迁移、不回填数据；修复的是现有 schema 契约与代码/测试夹具的一致性。

## 5. 验证结果

- `python -m py_compile ...`：通过
- `.venv/Scripts/python.exe -m pytest -q backend/tests/platform_registry/test_platform_registry.py backend/tests/platform_registry/test_platform_registry_api.py backend/tests/platform_registry/test_platform_identification.py`：48 passed
- `npm run test:frontend -- --run src/pages/PlatformRegistryTab.test.tsx src/components/DeviceFormModal.test.tsx src/pages/ParserRegistryTab.test.tsx`：24 passed
- `npm run lint`：通过
- `npm run build`：通过；仅保留既有的大 chunk warning
- `npm run test:frontend -- --run --testTimeout=15000 src/pages/AssetManagement/constants.test.ts src/pages/PlatformRegistryTab.test.tsx src/components/DeviceFormModal.test.tsx src/pages/ParserRegistryTab.test.tsx`：26 passed
- `.venv/Scripts/python.exe -m pytest -q backend/tests`：551 passed，25 subtests passed，1 个 Starlette/httpx 弃用 warning
