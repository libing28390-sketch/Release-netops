# CMDB 资产目录整改记录

## 目标

将资产管理的权威分类固定为：

`CMDB 站点 → 资产类型 → 产品分类 → physical_assets.device_role → 资产表格`

其中站点使用 `physical_assets.site_id → sites.id`，设备角色只使用
`physical_assets.device_role`。`devices.role` 不参与资产目录树的构建。

## 已完成

1. 增加 `m0012_cmdb_asset_site`：为 `physical_assets` 增加 `site_id`，并按旧数据中心文本匹配站点 ID。
2. 增加 `m0013_remove_asset_datacenter`：删除 `physical_assets.datacenter` 列。
3. 更新资产创建、更新、批量导入、资产列表、汇总、设备反向关联和 CMDB 设备骨架查询，停止读写物理资产的旧数据中心列。
4. 增加 `/api/cmdb/assets/tree` 和 `/api/cmdb/assets`，分别提供树聚合和叶子表格数据。
5. 增加 CMDB「资产目录」导航和 `/cmdb/assets` 路由。
6. 新增分层资产目录页面：左侧可展开树，右侧搜索、在线状态筛选、标签筛选、分页和资产字段表格。
7. 标签支持同一设备多标签；只有 `Administrator` 能执行标签定义和设备标签变更，普通用户只读。
8. 批量标签改为独立多选弹窗，支持搜索、分类分组、全选结果确认和一次应用多个标签。
9. 资产表增加列配置、浏览器持久化和按当前筛选结果导出 Excel；导出会按分页拉取最多 100 页数据。
10. 页面内容区改为自适应视口高度，减少大面积空白，表格在大屏和窄屏均可滚动。

## 验证结果

- PostgreSQL 迁移已应用到版本 13。
- 当前 `physical_assets` 已无 `datacenter` 列。
- 现有 4 条资产均成功回填到站点 `BJ-DC1`。
- CMDB 树返回 4 条角色分支，角色来源为 `physical_assets.device_role`。
- `backend/tests/test_asset_platform_catalog.py -q`：4 passed。
- `python -m compileall -q backend`：通过。
- `npm run lint`：通过。
- `npm run build`：通过；仅保留既有大包体积提示。
- `git diff --check`：通过。

## 上线顺序

1. 重启后端，使迁移和新 API 路由加载。
2. 浏览器打开 `/cmdb/assets`，验证树、表格、站点筛选和管理员标签编辑。
3. 用 Viewer 账号验证只能查看，不能看到编辑标签和标签定义修改入口。
4. 生产数据库备份后再执行迁移；若环境不是当前 PostgreSQL，先在同版本数据库副本执行迁移演练。

## 后续优化

- 将资产导入模板的站点字段改为站点选择/站点编码，并在导入结果中明确提示未知站点。
- 资产表格增加列配置、批量导出、保存筛选视图和站点级权限。
- 站点与机柜统一使用 `site_id`，逐步移除机柜模块中的自由文本机房字段。
- 为 CMDB 资产树增加 API 集成测试、权限拒绝测试和空数据测试。
