# 修复 PostgreSQL 迁移中断：执行记录

## 结果摘要

确认 `schema_migrations` 只到 18 的原因是 `m0019_site_timestamps` 在 PostgreSQL 中发生 TEXT/TIMESTAMP 类型冲突，导致 m0020～m0023 未执行。

## 实际修改

- 更新 `backend/database/migrations/m0019_site_timestamps.py`。
- PostgreSQL 回填统一使用 `CURRENT_TIMESTAMP::text`。
- 新增字段定义与既有基线保持 TEXT 一致。

## 验证命令

- `python -m py_compile backend/database/migrations/m0019_site_timestamps.py`：通过。
- `python -m pytest backend/tests/test_schema_migrations.py -q`：5 通过。

## 部署后验证

```bash
docker compose build netops
docker compose up -d netops
docker compose logs --since=5m netops | grep -Ei "m0019|m0020|m0021|m0022|m0023|migration"
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version, name FROM schema_migrations ORDER BY version;"'
```

完成后，在拓扑页面执行一次手动发现。

## 未验证项

尚未直接连接用户生产 PostgreSQL；部署命令和迁移版本查询需在目标服务器执行。
