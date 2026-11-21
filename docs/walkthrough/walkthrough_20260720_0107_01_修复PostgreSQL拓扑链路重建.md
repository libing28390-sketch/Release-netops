# 修复 PostgreSQL 拓扑链路重建：执行记录

## 完成摘要

已确认 Docker 环境中 5 台设备均采集成功、11 条邻居已匹配，但拓扑重建任务失败并产生 0 条 `topology_links`。根因是生产基线 `interfaces` 表与接口领域模型不一致，缺少 `name_display` 等字段。

## 实际修改

- 在 `backend/database/schema.py` 为新旧数据库补齐接口身份、显示名称、三层属性、聚合兼容字段。
- 新增 `backend/database/migrations/m0023_interface_identity_fields.py`，面向 PostgreSQL 现有数据库幂等添加字段并从 `interface_name` 回填名称。

## 验证命令与结果

- `python -m py_compile backend/database/schema.py backend/database/migrations/m0023_interface_identity_fields.py backend/services/topology_service.py`：通过。
- `python -m pytest backend/tests/test_schema_migrations.py backend/tests/test_topology_service.py -q`：13 通过；1 个既有断言因当前拓扑自动刷新间隔已改为 86400 秒而失败，与本次迁移无关。

## 部署后验证

```bash
docker compose build --no-cache
docker compose up -d
curl -sk https://127.0.0.1/api/topology/generation-status
```

随后在拓扑页面执行一次手动发现，确认 `inventory.managed_links` 和 `latest_manual_run.total_links` 有值。

## 未验证项与风险

- 当前未直接连接用户的生产 PostgreSQL，需由部署环境重启时执行迁移。
- 若仍失败，应查看 `Discovery run ... crashed` 后的 SQL 堆栈；本次迁移不删除数据库和数据卷。
