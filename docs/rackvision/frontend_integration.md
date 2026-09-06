# RackVision 前端联调约定

## 读取接口

- `/api/racks/{rack_id}/layout`：2D 和 3D 的布局唯一来源。
- `/api/racks/{rack_id}/quality-issues`：机柜范围质量问题。
- `/api/rack-data-quality/issues`：跨机柜质量问题查询。
- `/api/rack-assets/catalog`：只读视觉资产 registry。
- `/api/rack-assets/resolve`：单型号解析 exact/family/vendor/generic 级别。

所有接口使用现有 token helper；3D 资产目录不携带敏感资产字段。

## 视图规则

- 只有 `mount_kind=u_mount` 且位置合法的设备进入 U 位 2D/3D renderer。
- full-depth 设备同时占用前后面板。
- 0U、侧挂、落地和 unknown 设备出现在列表、Inspector 和数据质量面板，但不消费 `usedU`，也不被合成 U1。
- 3D 初版只读；移动设备必须通过 2D 保存后刷新 3D。

## 兼容性

后端健康 overview 使用 `{success,data,message,meta}`；前端保留对旧的顶层 `items` 形状的兼容读取，以便渐进升级。

