# 平台识别与站点标识修复

## 变更

- `m0095_seed_core_platform_identification_rules.py` 为 Cisco、Arista、H3C、华为、Juniper 及既有国产平台补齐识别规则。
- `device_health_detail` 通过 physical asset/site 关联返回站点名称；前端归一化也会隐藏 `site-*` 内部标识。
- 资产创建、更新、导入继续使用 canonical site 解析，并拒绝历史 `site-default` 保底站点作为业务资产分配值。

## 验证重点

- Cisco `show version` 能命中 `cisco_ios`。
- 华为/H3C 使用 `display version`，锐捷、迪普、迈普、中兴使用 `show version`。
- R1 详情显示 `WH-DC-01`，不显示 `site-1f5056da0738`。
- 未进行 commit、push 或关机。
