# Walkthrough：CMDB 资源检索

## 目标

在 CMDB 中增加“资源检索”入口，用于跨站点查询全部设备。该模块是只读检索视图，不新增一套设备主数据，也不替代资产管理或资产目录。

## 已实现能力

- 路由：`/cmdb/resources`。
- 服务端分页，默认每页 20 条，支持 10/20/50/100 条切换。
- 关键词模糊查询和精确查询。
- 可选择查询字段：设备名称、资产编号、序列号/SN、管理 IP、业务 IP、厂商、型号、平台。
- 标签筛选支持“全部匹配”和“任一匹配”。
- 站点、资产类型、设备分类、厂商、平台、在线状态、生命周期筛选。
- 结果展示设备名称、SN、资产编号、管理 IP、业务 IP、厂商、型号、平台、标签、站点、状态、接口数和拓扑关系数。
- 只返回非敏感资源信息，不返回密码、凭据或 SNMP community。
- 侧边栏和命令面板均增加“资源检索”入口。

## 数据边界

资源检索以 `devices` 为查询主体，优先使用 `physical_assets` 中的权威资产字段；不会复制或维护设备数据。资产新增、编辑和删除仍通过资产管理完成，资产目录继续负责层级浏览。

## 接口

`GET /api/cmdb/resources`

主要参数：

- `q`：查询关键词。
- `search_field`：`all`、`hostname`、`asset_tag`、`serial_number`、`ip`、`management_ip`、`business_ip`、`vendor`、`model`、`platform`。
- `search_mode`：`fuzzy` 或 `exact`。
- `tag_ids`：逗号分隔的标签 ID。
- `tag_match_all`：标签全部匹配或任一匹配。
- `page`、`page_size`：分页参数。

## 验证记录

- 资源检索专项测试：`2 passed`。
- 后端全量测试：`141 passed, 25 subtests passed`。
- `npm run lint`：通过。
- `npm run build`：通过；保留项目既有的大 chunk 体积提示，不影响构建成功。
