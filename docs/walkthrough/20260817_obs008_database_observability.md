# OBS-008 PostgreSQL 数据库观测验证记录

## 原始任务

第 16 节“API、会话、任务与可观测性”的 `OBS-008`：建立索引膨胀、慢查询、缓存命中和数据库容量监控。

## 落地范围

- `/api/ai/metrics` 在现有权限 `ai.audit.view` 下增加 `database` 聚合对象。
- PostgreSQL 只读目录查询覆盖知识库关系的 dead/live tuple、关系/索引字节数、缓存命中率和当前数据库大小。
- 慢查询优先读取 `pg_stat_statements` 的 query id 与耗时聚合；未安装/未预加载时安全回退到 `pg_stat_activity` 当前活跃查询时长，不返回 SQL 文本。
- Usage Dashboard 增加 PostgreSQL 观测卡片，显示缓存、慢查询、容量和膨胀状态。
- SQLite 明确返回 `NOT_APPLICABLE`，不作为生产容量证据。

## PostgreSQL 实测

执行：

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_obs008_pg_probe.py
```

实测输出为有界摘要：

```json
{"cache_hit_rate": 0.994742, "capacity_status": "PASS", "redacted": true, "relation_stats_status": "WARN", "slow_query_count": 0, "slow_query_source": "pg_stat_activity", "slow_query_status": "PASS", "status": "WARN"}
```

`WARN` 来自现有 PostgreSQL 关系 dead/live tuple 超过 20% 的运维信号，不是探针失败；未执行 VACUUM、ANALYZE、DDL 或数据写入。`pg_stat_statements` 当前未安装，因此使用 `pg_stat_activity` fallback，并在响应中标明扩展状态。

## 重启后浏览器验证

重启实际服务后，已登录浏览器验证：

- `/ai/providers` 正常返回 Provider 管理页，不再出现“服务内部异常”；Provider 总数 1、已启用 1、密钥状态 1/1。
- `/ai/usage` 正常显示“PostgreSQL 数据库观测”卡片：状态 `WARN`、缓存命中率 `99%`、慢查询样本 `0`、数据库容量 `838.05 MiB`、预算占用 `0%`。
- 页面显示只读目录指标边界；浏览器控制台无 error/warn。

## 回滚

删除 API/UI 观测字段或回退本地 commit 即可；没有新增表、列、索引或持久化数据。
