# 机柜管理并发控制与上架策略优化实施计划

为了解决多人并发操作设备上架时可能产生的 U 位冲突（Race Condition），并提供灵活的设备上架策略（如“底部优先”或“顶部优先”），我们将对 Nexora 平台的机架管理模块进行重构升级。

## 用户审查要求

> [!IMPORTANT]
> 1. 本实施计划遵循最新的归档规范，使用中文命名并保存在 `docs/plans/` 目录下。
> 2. 数据库迁移将引入 `placement_strategy` 字段，默认值为 `bottom_first`（底部优先）。
> 3. 后端校验逻辑将采用行级锁/事务锁，解决并发写入冲突。
> 4. 前端将新增上架策略配置项并重构空余 U 位推荐算法。

## 拟作出的变更

### 1. 数据库定义与迁移

#### [修改] [schema.py](file:///e:/data/netsops/backend/database/schema.py)
* 在 `racks` 表创建 SQL 中，为 PostgreSQL 和 SQLite 分别添加 `placement_strategy` 字段（`VARCHAR(20) DEFAULT 'bottom_first'` / `TEXT DEFAULT 'bottom_first'`)。
* 调用 `ensure_column` 函数，实现对已有数据库的自动字段迁移。

### 2. 后端数据结构与逻辑服务

#### [修改] [schemas.py](file:///e:/data/netsops/backend/schemas/schemas.py)
* 在 `RackCreate` 和 `RackUpdate` 结构中新增 `placement_strategy` 字段，并使用 `@field_validator` 校验其取值范围必须为 `('bottom_first', 'top_first')`。

#### [修改] [rack_service.py](file:///e:/data/netsops/backend/services/rack_service.py)
* **并发事务控制**：在 `_check_u_constraints` 校验函数中，增加事务锁逻辑：
  * 若为 PostgreSQL（`_USE_PG` 为 True），执行 `SELECT 1 FROM racks WHERE id = ? FOR UPDATE` 行级加锁。
  * 若为 SQLite（`_USE_PG` 为 False），通过执行 `BEGIN IMMEDIATE` 显式占有写锁，使并发事务排队。
* **增改接口更新**：更新 `create_rack` 和 `update_rack` 接口，支持 `placement_strategy` 的保存与更新。

### 3. 前端数据类型与上架算法重构

#### [修改] [types.ts](file:///e:/data/netsops/src/pages/RackManagement/types.ts)
* 在 `Rack` 接口类型中定义 `placement_strategy?: 'bottom_first' | 'top_first';` 属性。

#### [修改] [helpers.ts](file:///e:/data/netsops/src/pages/RackManagement/helpers.ts)
* 重构 `findFirstFreeStartU` 算法：根据传入的 `placement_strategy` 选择检索方向：
  * `bottom_first`：从 `1` 到 `totalU - uHeight + 1` 递增扫描。
  * `top_first`：从 `totalU - uHeight + 1` 到 `1` 递减扫描。
* 重构 `pickStartUForAsset`：传递并使用策略参数以优化首位推荐位置。

#### [修改] [index.tsx](file:///e:/data/netsops/src/pages/RackManagement/index.tsx)
* 在“创建/编辑机架”表单中，新增“上架策略 (Placement Strategy)”下拉选择框（选项包括：底部优先 / 顶部优先）。
* 更新前端在设备上架或资产关联时对 `resolveStartUForInstall` 的调用，传入当前的机架策略。

## 验证计划

### 手动与并发性验证
1. **策略切换验证**：新建一个机架，设定策略为“顶部优先 (Top First)”。尝试在前端拖拽/上架一个 2U 设备，验证系统默认推荐的起始 U 位是否为最顶部的空余位置（如 U41）。
2. **并发冲突测试**：通过多开浏览器窗口，模拟管理员 A 和管理员 B 同时将两台设备提交到同一个空闲 U 位，验证是否能成功阻止并发写入冲突，确保有且仅有一台设备能够成功安装，另一台弹出 400 校验错误提示。
