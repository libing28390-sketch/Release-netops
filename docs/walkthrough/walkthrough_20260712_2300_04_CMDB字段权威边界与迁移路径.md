# CMDB 字段权威边界与迁移路径完成记录

## 完成摘要

完成 CMDB-002 的字段权威边界梳理，明确当前项目应采用四层模型：

```text
physical_assets -> devices -> interfaces -> ip_addresses
```

结论是：`devices + interfaces` 作为 CMDB 主骨架是正确的，但企业级场景下必须同时明确资产层和 IPAM 地址层的权威边界。

本轮未修改数据库结构，也未改变 API 行为，属于后续迁移前的架构基线整理。

## 实际修改文件

1. `docs/plans/plan_CMDB字段权威边界与迁移路径.md`
   - 记录本轮任务目标、现状问题、影响范围、实施步骤和验证计划。

2. `docs/architecture/cmdb_field_authority_migration.md`
   - 新增字段权威边界和迁移路径文档。
   - 明确 `physical_assets`、`devices`、`interfaces`、`ip_addresses` 的权威职责。
   - 明确 `site -> site_id` 和 `interface_name -> interface_id` 两条关键迁移路径。
   - 拆分后续 CMDB-002A 到 CMDB-002F 的可执行任务。

## 关键结论

### 四层权威模型

| 层级 | 权威对象 | 主要职责 |
|---|---|---|
| 资产层 | `physical_assets` | 资产标签、序列号、采购、质保、机柜/U 位、物理生命周期 |
| 设备层 | `devices` | 运维设备身份、连接信息、平台、状态、角色、站点、资产引用 |
| 接口层 | `interfaces` | 接口身份、状态、MAC、速率、VRF、VLAN、父子接口 |
| 地址层 | `ip_addresses` | IP 地址、Prefix、VRF、接口绑定、地址角色、占用状态 |

### 两条优先迁移路径

1. `devices.site` 收敛到 `devices.site_id`
   - `site_id` 作为权威。
   - `site` 仅作为展示缓存或 legacy 字段。

2. `interface_name` 收敛到 `interface_id`
   - `ip_addresses.interface_id` 作为 IP 绑定接口权威。
   - `topology_links.source_interface_id/target_interface_id` 作为链路端点权威。
   - 端口名称字符串作为展示快照和发现证据保留。

## 验证命令与结果

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

### 文档关键内容检查

```powershell
rg -n "CMDB 字段权威|字段权威|CMDB-002|site_id|interface_id|physical_assets  ->  devices" docs\plans\plan_CMDB字段权威边界与迁移路径.md docs\architecture\cmdb_field_authority_migration.md
```

结果：通过，关键章节和迁移路径均存在。

## 未执行验证及原因

- 未运行后端单元测试：本轮只新增架构文档，不改运行时代码。
- 未运行 `npm run lint`：本轮没有新增前端代码；上一段“机柜拖拽类型错误修复”已恢复 lint 通过。
- 未执行数据库迁移：本轮目标是迁移前的权威边界定义。

## 剩余风险

1. 当前运行时代码仍存在字段重复，这是后续任务要逐步修复的问题。
2. 真正执行 `site_id/interface_id` 收敛前，需要先做数据质量审计接口。
3. 删除 legacy 字段前必须经历兼容读取、双写、回填校验和只读冻结阶段。

## 后续建议

下一步建议执行 CMDB-002A：新增字段权威只读审计接口。

建议接口：

```text
GET /api/cmdb/data-quality/field-authority
```

建议输出：

- 设备总数。
- `site_id` 为空数量。
- `site` 与 `site_id` 不一致数量。
- `ip_addresses.interface_id` 缺失数量。
- `topology_links.source_interface_id/target_interface_id` 缺失数量。
- 资产与设备管理 IP 不一致数量。
