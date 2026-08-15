# SNMP MIB/ZIP 上传与数据库迁移说明

## 这次问题的根因

当时运行中的数据库记录只到迁移版本 115，而代码已经包含 116–136 的迁移。`snmp_mibs` 表因此没有 `is_active` 等新字段；页面轮询 LibreNMS 同步状态时首先触发了 `column "is_active" does not exist`，后续请求又复用了 PostgreSQL 已经失败的事务，于是出现大量 `InFailedSqlTransaction`。

随后启动又暴露出一个历史兼容点：旧安装把第 6 号迁移记录为 `interface_telemetry_and_history`，当前代码的第 6 号迁移名称是 `asset_legacy_takeover_exemption`。代码现在只接受这个明确登记的旧名称，不会放行任意未知的迁移名称漂移。

这不是 ZIP 文件本身导致的首个错误，而是数据库结构与当前代码版本不一致。

## 已实现的行为

- MIB 管理页面增加“上传 MIB / ZIP”按钮。
- 支持单文件 `.mib`、`.my`、`.txt`、`.asn`，以及包含这些文件的 `.zip`。
- ZIP 不落盘解压；单个成员使用 savepoint 保存。某个 MIB 解析失败时会记录失败文件并继续导入其他有效文件。
- 默认限制：上传文件 50 MiB、ZIP 成员 1000 个、支持文件解压后合计 250 MiB；可通过环境变量调整。
- 上传接口仍由后端强制要求 `Operator` 或更高权限，不能依赖前端按钮隐藏来做权限控制。
- 上传异常会主动回滚数据库事务，避免下一次请求继续收到 `InFailedSqlTransaction`。

## 为什么仍然需要迁移

数据库是持久化状态，代码升级不会自动改变已经存在的表。只改代码而不迁移，代码查询新字段时必然报错；只手工增加某一个字段，又可能遗漏索引、约束、数据回填和后续版本，留下更隐蔽的不一致。

因此迁移不是要求用户手工维护数据库，而是部署流程的一部分：

1. 新机器启动时创建基线表。
2. 启动程序按顺序执行尚未应用的迁移，直到当前代码的最新版本。
3. 校验迁移历史完整、无冲突且没有待执行版本。
4. 校验通过后才启动服务；失败则直接失败并打印第一条迁移错误，不再让服务带着半套表结构运行。

当前实现不会执行“只补 `is_active`”这种临时 SQL。现有机器部署新代码后重启后端即可触发标准迁移；在生产环境仍应先备份 PostgreSQL。本次兼容修复没有直接改写迁移历史记录；后续只读检查已确认该库的迁移版本为 136 且 `is_active` 已存在。

## 部署后检查

1. 部署代码并重启后端服务；前端重新构建或刷新对应静态资源。
2. 查看启动日志，确认迁移执行完成且没有 `pending versions` 或 `unsafe history`。
3. 用数据库检查迁移版本和 MIB 字段：

   ```sql
   SELECT MAX(version) FROM schema_migrations;
   SELECT column_name
   FROM information_schema.columns
   WHERE table_name = 'snmp_mibs'
   ORDER BY ordinal_position;
   ```

4. 用 Operator 账号打开 `/management/snmp-metric-templates`，上传一个 ZIP；页面会显示成功数量和失败文件。

## 验证结果

- MIB/数据库相关后端测试：25 passed。
- MIB 仓储与上传测试：9 passed。
- 前端上传组件测试：4 passed。
- `npm run lint`：通过。
- `npm run build`：通过；仅保留已有的大 chunk 提示。
- 全量后端测试：1499 passed，另有 6 个与本次无关的既有失败，以及 75 个依赖本地 PostgreSQL 验收环境的错误，未将其用放宽迁移检查的方式掩盖。
