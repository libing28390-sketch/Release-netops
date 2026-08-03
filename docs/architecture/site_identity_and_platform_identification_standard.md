# 站点标识与平台识别规范

## 1. 站点身份

- `sites.id` 是数据库关系键，只能用于关联、过滤、写入和审计，不能作为业务页面的站点名称回退值。
- 业务展示统一使用 `site_name`，缺失时使用 `site_code`；`site-*`、`site-default`、`DEFAULT_SITE` 等系统生成值不得直接展示给用户。
- 资产、设备、机柜、VLAN、前缀等资源写入站点时，必须通过 `resolve_canonical_site_id` 将站点 ID、编码或名称解析为真实 `sites.id`。解析失败必须拒绝写入，禁止保存自由文本或悬空 ID。
- `site-default` / `DEFAULT_SITE` 仅允许作为历史兼容或迁移数据存在，不得作为新业务资产的分配站点。站点选择器必须过滤该保底对象。
- 设备详情、健康详情、拓扑、采集状态等 API 必须同时提供可展示的站点标签与 canonical `site_id`；任何详情接口都不得直接把 `devices.site` 的内部 ID透传到 `site` 展示字段。

## 2. 平台识别

- SYSTEM 平台必须至少有一条启用的 `platform_identification_rules`，否则自动识别只能返回 `NO_MATCH`。
- 识别命令必须来自连接驱动契约，不能按厂商名称硬编码到页面或业务流程：
  - Cisco、Arista、Juniper：`show version`
  - 华为、H3C/Comware：`display version`
  - 锐捷、迪普、迈普、中兴：`show version`
- 规则应匹配厂商/产品锚点（如 `Cisco IOS Software`、`H3C Comware Software`、`Versatile Routing Platform Software`），不得使用 `Software`、`Version` 等跨厂商通用词造成误匹配。
- 已锁定的人工绑定不能被自动识别覆盖；自动识别只报告 `MATCHED`、`NO_MATCH` 或冲突状态，并保留识别命令用于诊断。
- 新增 SYSTEM 规则必须通过版本迁移落库，并提供至少一条正常输出和一次 `NO_MATCH`/命令契约回归测试；不得直接修改线上数据库或把规则写死在前端。

## 3. 评审清单

1. 是否只在关系字段使用 `site_id`，业务展示是否使用 `site_name`/`site_code`。
2. 是否过滤保底系统站点，是否拒绝未知站点和悬空站点 ID。
3. 识别命令是否与 `connection_driver` 一致，国产设备的 `show version` 与华为/H3C 的 `display version` 是否区分。
4. SYSTEM 平台是否有启用规则，规则是否使用唯一产品锚点并覆盖已有设备版本输出。
5. 详情 API、列表 API、健康 API、拓扑 API 是否遵守同一套站点展示契约。
