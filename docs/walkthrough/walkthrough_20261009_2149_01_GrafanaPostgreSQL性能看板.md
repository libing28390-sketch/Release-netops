# Grafana PostgreSQL 性能看板 Walkthrough

## 完成内容

- 增加独立 PostgreSQL Grafana dashboard，并加入 Grafana V2 registry 和生成器。
- Compose 增加 postgres_exporter v0.20.1，启用 `pg_stat_statements` collector，每次最多导出 100 条 statement 指标。
- 新建受限 `pg_monitor` 用户；新数据卷通过初始化脚本创建，部署脚本对已有数据卷幂等创建扩展并同步该用户。
- 本地 collector 编译结果新增 `platform_postgres_exporter` 抓取目标，不直接改写运行时生成的采集文件。
- Top SQL 以 Query ID 排名，不把 SQL 文本写入时间序列标签。Cache Hit 指标按 PostgreSQL 数据库统计展示，不能解释为单条 SQL 命中率。

## 验证

- Grafana dashboard 定向生成成功；V2 registry 和 13 个 dashboard JSON 解析通过。
- Grafana 查询 / 生成相关测试：63 passed；变更后的 PostgreSQL 专项 dashboard 断言：1 passed。
- monitoring compiler 测试：24 passed。
- Docker deployment contract 测试：10 passed；Bash `-n` 与 Compose YAML 解析通过。
- `git diff --check` 通过。

## 未完成的线上验证

- 本地没有运行中的 Grafana/PostgreSQL 18 实例与 Docker Compose CLI，因此未验证容器启动、真实 `/metrics` 或面板视觉效果。
- 生产 PostgreSQL 需重启以加载 `pg_stat_statements`；部署脚本会在启动后创建扩展并配置监控账号。之后需在 Grafana 确认 `platform_postgres_exporter` 与 `stat_statements` 状态正常并出现样本。

## 边界

- 不新增 Nexora 页面、API 或告警中心。
- postgres_exporter v0.20.1 的 statements collector 不暴露每条 statement 的 shared block hit/read；看板不显示单 SQL Cache Hit。
- SQL 文本 collector 默认关闭；Dashboard 只显示 Query ID。
