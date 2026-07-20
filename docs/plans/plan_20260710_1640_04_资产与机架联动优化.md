# 资产与机架管理数据联动与冲突校验实施计划

为了解决资产管理录入设备时未进行机柜U位重叠校验，且机柜管理页面无法自动同步资产设备信息的问题，我们将建立“资产台账 ➔ 物理机架”的自动联动与物理空间约束逻辑。

## 用户审查要求

> [!IMPORTANT]
> 1. 本实施计划遵循工作区归档与中文命名规范，保存在 `docs/plans/` 目录下。
> 2. **机架物理空间强约束**：在录入/修改物理资产（服务器、网络设备）时，若指定了机柜名称和起始U位，系统将调用机柜服务的 `_check_u_constraints` 算法进行空间重叠（Interval Overlap）、机柜容量及边界检查。若冲突，直接拦截并报错。
> 3. **实时数据联动**：保存/修改资产时，自动在 `rack_devices` 表中同步创建/修改关联条目，机柜图形化页面实时呈现。删除资产时，自动级联移除对应的机架设备。
> 4. **数据库选用**：系统底层采用 PostgreSQL 作为数据库。

## 拟作出的变更

### 1. 资产 API 逻辑升级，增加 Rack 设备联动机制

#### [修改] [assets.py](file:///e:/data/netsops/backend/api/assets.py)
* 引入机柜管理服务组件 `from services import rack_service`。
* 实现 `_sync_rack_device_from_asset(conn, asset_id, obj)` 助手函数：
  1. 提取 `hostname`、`rack`（机柜名称）、`u_height`、`planned_start_u`、`serial_number` 等属性。
  2. 若 `rack` 或 `planned_start_u` 被置空，说明设备下架，若存在对应的 `rack_devices`，则自动将其删除。
  3. 若均有值，根据机柜名称检索对应机柜的 `rack_id`。若机柜不存在，抛出 `ValueError`。
  4. 解析/同步该资产对应的 `device_type_id`。
  5. 判断是否已存在绑定该 `asset_id` 的 `rack_devices` 记录：
     * 若已存在，则调用 `rack_service.update_rack_device` 进行属性更新与 U位冲突重算。
     * 若不存在，则调用 `rack_service.create_rack_device` 进行上架，并触发重叠空间碰撞算法。
* 升级 `create_asset` (POST `/api/assets`) 和 `update_asset` (PUT `/api/assets/{asset_id}`)：
  * 在事务提交前调用 `_sync_rack_device_from_asset`。
  * 使用 `try...except ValueError as e` 捕获 U位冲突和无效机柜错误，并转换为 `HTTPException(status_code=400, detail=str(e))` 返回给前端。
* 升级 `delete_asset` (DELETE `/api/assets/{asset_id}`)：
  * 删除资产时，增加 `conn.execute('DELETE FROM rack_devices WHERE asset_id = ?', (asset_id,))`，实现机架拓扑的级联自动清理。
* 升级批量导入 `import_assets` (POST `/api/assets/import`)：
  * 对导入的每一行资产进行 `_sync_rack_device_from_asset` 尝试，对冲突信息记录 warning 级别日志并不中断总体导入。

## 验证计划

### 自动化与数据库验证
1. **DB 清理及现状核对**：
   * 用 SQL 检查 `physical_assets` 和 `rack_devices` 确认当前的冲突资产。
2. **重叠校验拦截测试**：
   * 尝试在资产管理中录入资产 B，指定相同的机柜 `A-01`，高度为 2U，起始U位设为 1（与已在 U1 的资产 A 冲突）。验证 API 是否拦截并返回包含具体冲突原因（如 `overlaps with...`）的 400 错误。
3. **数据同步与机柜大屏联动走查**：
   * 新增或编辑一台非冲突位置的设备（如 A-01 的 U10 位），保存成功后：
     * 确认数据库 `rack_devices` 产生了对应的 `asset_id` 关联记录。
     * 打开**机柜管理 ➔ A-01机柜**的布局页面，确认大屏上自动在 U10-U11 绘制了该资产的卡片，点击能调出其对应的资产参数。
   * 修改资产名称或U位，确认大屏及数据库同步变化；删除该资产后，确认机柜图上对应卡片自动移除，数据库对应行级联删除。
