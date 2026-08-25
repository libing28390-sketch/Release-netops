# 2026-08-25 SNMP 显式模板绑定 walkthrough

## 目标

SNMP 模板不再依赖 `sysObjectID`、厂商或型号规则自动套用。用户从官方内置模板或自定义模板进入“绑定设备”，明确选择要采集的设备；同型号的其他设备不会被隐式影响。

## 用户流程

1. 在 SNMP 模板管理页选择官方模板或点击“新建自定义模板”。新建保存成功后会直接进入绑定弹窗。
2. 在弹窗中搜索并多选设备；已有绑定会回显，支持“一键全选”“选择当前结果”“清除当前”。
3. 测试只针对一台测试样例设备执行，不会对全选设备逐台发起 SNMP 测试或返回全部采集结果；服务端继续从资产管理解析 SNMP 凭据，前端不会读取或提交 community/password。
4. 确认后只写入所选设备的模板引用；取消勾选的原绑定设备会同步解绑。
5. 官方预置列表只显示“候选设备数”，表示按厂商/型号找到的资产，不表示已绑定；实际“已绑定 N 台”只显示在已保存模板记录中。设备详情展示当前模板名称、模板 ID 和来源（官方/自定义/旧数据）。未绑定时明确显示“未应用模板指标”。
6. 模板删除前必须先解绑全部设备；官方模板只读，用户需要复制为自定义模板后再编辑。

未匹配官方模板的型号不再在列表顶部弹出提醒，用户按需使用“新建自定义模板”即可。

## 数据与接口

- `devices.snmp_metric_profile_id` 是设备当前模板的显式引用，空值表示未应用模板。
- `snmp_metric_profiles` 增加 `template_name`、`source`、`official_preset_id`，允许同厂商/型号存在多个独立模板。
- `m0181_explicit_snmp_template_bindings` 迁移会保留旧的有效厂商/型号匹配结果作为设备绑定，避免升级后突然停止采集；之后的解析以设备引用为准。
- `GET/POST /api/platform-registry/snmp-metric-profiles/{profile_id}/bindings` 管理绑定和回显，`POST .../bindings/unbind` 执行显式解绑。
- 应用官方预置只创建或复用官方模板，不自动绑定整批同型号设备。

## 验证记录

- SNMP 语义回归：31 passed。
- m0181 迁移与显式绑定测试：2 passed。
- 前端模板管理测试：10 passed；绑定弹窗测试：2 passed。
- `npm run lint`：通过。
- `npm run build`：通过；仅保留既有 chunk 体积提示。
- 全量后端测试已执行：`1382 passed`，另有工作区原有的跨模块/环境问题导致 `60 failed、62 errors`，主要涉及缺失 `make_user` fixture、PostgreSQL/SQLite 测试适配和缺失知识库文档，并非本次 SNMP 聚焦测试失败。
- 全量前端测试已执行：`131 passed`，1 个既有 AI Provider 测试超时（`ProviderManagementTab.test.tsx`），不属于本次 SNMP 改动范围；本次模板管理/绑定聚焦测试为 `13 passed`。
