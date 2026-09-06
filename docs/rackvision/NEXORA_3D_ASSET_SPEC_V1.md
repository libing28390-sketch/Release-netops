# Nexora 3D Asset Specification v1.0

## 1. 单位和坐标

- Blender scene 使用 Metric。
- 1 Blender unit = 1 meter。
- `1U = 0.04445 m`。
- `X`：左右，正方向向右。
- `Y`：前后，正方向指向机柜前方。
- `Z`：垂直，正方向向上。
- 设备原点：机箱 X 中心、前部插入参考平面、设备底部。
- 机柜原点：机柜内框 X 中心、前部安装参考面、U1 底部。

导出前必须验证前方向为 `+Y`，并将 transforms 应用为 scale 1/1/1。

## 2. 命名

基础对象：`BODY`、`FRONT_PANEL`、`REAR_PANEL`、`LOGO_VENDOR`、`LCD_MAIN`。  
指示灯：`LED_POWER`、`LED_SYSTEM`、`LED_ALARM`。  
电源和风扇：`PSU_01`、`PSU_02`、`FAN_01`、`FAN_02`。  
端口：`PORT_GE_01`、`PORT_SFP_01`、`PORT_QSFP_01`、`PORT_MGMT_01`、`PORT_CONSOLE_01`。

端口序号必须从 01 开始，并保持与目录的端口布局一致；不能以图片比例推断数量。

## 3. 材质

固定材质名：`MAT_CHASSIS`、`MAT_FRONT_PANEL`、`MAT_PORT`、`MAT_GLASS`、`MAT_LED`、`MAT_LABEL`、`MAT_LOGO`。

当前自动化模板使用低多边形基础材质；正式厂商纹理必须有可追溯授权或只保存来源链接，不把未经授权的营销图复制进仓库。

## 4. 几何预算和 LOD

建议初始预算：

- generic 1U：不超过 10k triangles；
- family：不超过 30k triangles；
- showcase：不超过 50k triangles；
- 机柜重复部件优先实例化，禁止逐个建模通风孔。

LOD：

- LOD0：边界盒/低细节兜底；
- LOD1：机柜远景简化模型；
- LOD2：正常产品视图；
- LOD3：可选近景面板。

## 5. 元数据和发布

每个 registry entry 至少包含 `asset_key`、vendor、family、exact_models、device_type、height_u、尺寸、`glb_path`、`source_blend`、source_refs、data_confidence、version、status。

状态：`draft`、`review`、`approved`、`deprecated`。只有 `approved` 且通过 GLB 验证的文件才能进入发布目录。没有官方尺寸时保留 `null` 与 `pending_verification`，不能通过缩放照片补齐。

