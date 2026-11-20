# 接口采集刷新与历史投影清理

## 现象

- CMDB 接口页在设备删除后仍显示 `Unknown device` 分组。
- 立即采集完成后页面仍停留在采集前的数据。
- 网络监控页的设备诊断接口查询不存在的 `devices.port` 列并报错。

## 修复

1. 诊断服务统一读取现有的 `devices.management_port` 字段。
2. 接口采集成功后按当前快照 reconcile：保留接口行 ID 以避免拓扑外键失效，但对本次快照中已消失的接口清空 IP、前缀、L3/启用标记和状态。
3. CMDB 接口读取过滤并清理已删除设备留下的孤立 `ip_inventory` 投影；设备删除接口也同步删除对应投影。
4. 新增 `m0038_purge_orphan_ip_inventory`，清理已有历史孤立数据。
5. 前端任务进入终态时等待一次 `load()` 完成后再提示，且同一个任务只处理一次终态，避免刷新竞态和重复刷新。

## 验证

- PostgreSQL 迁移已应用：`m0038_purge_orphan_ip_inventory`。
- 现有数据库清理前孤立 `ip_inventory` 30 条，清理后 0 条。
- 当前 CMDB 接口读取：50 条，`Unknown device` 0 组。
- 新增诊断字段兼容和接口快照清理回归测试。
