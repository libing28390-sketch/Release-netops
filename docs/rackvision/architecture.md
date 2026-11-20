# RackVision 实施架构

## 目标

把 CMDB 机柜位置作为唯一事实源，让 2D 编辑、3D 只读视图、统计、健康和拓扑消费同一份布局读模型。3D 资产解析属于展示层，不得复制位置写入。

## 组件边界

```text
Rack API / Asset API
        ↓
RackPlacementService  ── PostgreSQL row/advisory locks
        ↓
RackService read model ── placement + occupancy + power
        ├─ Rack 2D UI
        ├─ Rack 3D UI ── AssetResolver ── GLB or procedural fallback
        ├─ Health overlay
        └─ Quality API / backfill report
```

### 写入边界

所有安装、移动、更新和卸载都进入 `rack_placement_service`：

- 标准 `u_mount` 必须有 `start_u`、有效高度和合法面板；
- `full_depth` 同时占用前后两面；
- `zero_u`、`side_mount`、`floor`、`unknown` 不消费标准 U；
- asset identity 通过锁和唯一索引避免跨机柜重复安装；
- 安装成功后同步 `physical_assets` 投影并增加 `layout_revision`。

### 读取边界

`RackService` 将旧字段转换成兼容读模型，但不把未知值变成有效值。每个设备携带 placement 状态、数据质量和 3D visual asset resolution metadata。

## 事务和缓存

- PostgreSQL 对目标机柜行加锁；跨机柜移动按排序后的 rack id 加锁，降低死锁概率。
- 资产安装使用 PostgreSQL advisory lock 和非空 asset_id 唯一索引双重保护。
- 布局修改使机柜读缓存失效；多 worker 的最终缓存一致性依赖现有缓存失效机制，不新增进程内位置写缓存。
- 回填不在应用启动执行，由独立 CLI 控制备份、审批和 commit。

## 错误处理约定

当前位置服务以 `ValueError` 兼容旧路由，后续可以按项目统一异常层逐步映射为 409/422；新数据质量 API 已保持稳定 envelope。禁止把 SQL、traceback、文件路径或凭据写入用户响应。

