# 2D/3D 同步验收

## 规则

```text
2D Rack Editor save
      ↓
POST/PUT /api/rack-devices
      ↓
rack_devices canonical placement + physical_assets projection
      ↓
GET /api/racks/{id}/layout
      ↓
2D / 3D render same placement
```

3D 不执行位置保存，不拥有独立 topology 或 placement 数据库。

## 验收场景

1. 打开 Rack A 的 2D 视图。
2. 把标准 U 设备从 U38 移到 U30 并保存。
3. 重新请求 layout。
4. 2D 显示 U30，3D 在同一个读模型中显示 U30。
5. 0U PDU / 落地 UPS 的 start_u 为空且不影响标准 U 可用容量。
6. full-depth 设备与前、后任一面板冲突时，API 返回冲突而不是由前端猜测。

## 数据质量验收

未知机柜、未知型号、缺少 U 高度、U 越界、重复 asset_id 和非法位置必须在 quality API 中可查询；回填命令默认 dry-run，只有 `--apply` 才写入。

