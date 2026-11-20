# Huawei YunShan 平台与 Windows 开发端口

## 现象与目的
- 资产导入、设备平台绑定、驱动及 TextFSM 目录缺少独立 Huawei YunShan OS 支持，可能将它误归到 VRP。
- Windows 开发默认端口 5310 落在系统排除端口范围内，后端无法启动。

## 根因与方案
分别贯通 `huawei_yunshan` 平台键、Huawei 传输适配、识别/Profile 迁移、资产导入/设备 UI 与六个只读 TextFSM 模板；保留 VRP 身份，不自动改绑旧设备。将 Windows 默认后端端口设为 15310，Linux 仍用 5310，保留环境变量覆盖。

## 实际修改文件
完整清单见配对 walkthrough。涉及 `backend/api`、`backend/core`、`backend/drivers`、`backend/engine/drivers`、`backend/services`、PostgreSQL migration m0275 与对应测试、`data/textfsm_templates/huawei_yunshan_*`、资产及设备前端/类型/平台目录与聚焦测试、`public/templates/asset_import_template.xlsx`、`scripts/dev-backend.mjs`、`scripts/dev-internal.mjs`、`package.json` 和 `vite.config.ts`，以及对应计划、walkthrough。

## 验证
- YunShan 后端兼容集成 204 项通过；最终平台链路复查 56 项通过，均在隔离 PostgreSQL 上执行并清理测试库。
- 前端 7 个相关测试文件 39 项通过；`NODE_OPTIONS=--max-old-space-size=8192 npm run lint` 及隔离目录生产构建通过。
- 两个启动脚本 `node --check`、Vite 配置默认值/代理及环境变量覆盖检查通过；后端 15310 和前端代理健康检查均 200。
- PostgreSQL-only 策略扫描 0 violations。

## 未验证、风险与回滚
没有实机 YunShan 设备输出；版本模板目前共用 common，平台支持范围详见 walkthrough。回滚代码与 m0275 需按对应迁移说明处理，不删除已有设备绑定。开发端口仍可用 `BACKEND_PORT`、`VITE_API_TARGET` 覆盖。
