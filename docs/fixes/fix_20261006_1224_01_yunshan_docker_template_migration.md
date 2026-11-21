# YunShan Docker 模板迁移启动故障

## 问题现象

- Docker 部署启动时，FastAPI 数据库初始化失败。
- 数据库迁移 0275 报告缺少 `huawei_yunshan_display_version.textfsm`，导致 netops 容器退出，依赖容器无法启动。

## 根因

Dockerfile 将只读发布模板复制到 `/app/release-textfsm-templates`，而 `/app/data` 被持久卷覆盖。迁移 0275 却只从 `/app/data/textfsm_templates` 读取模板，因此把空的用户数据卷当成了系统模板目录。

## 解决方案

- 迁移优先选用镜像只读发布目录，开发环境回退到源码模板目录。
- 在写数据库前校验所需的完整模板集合；两处均不完整时列出缺项并停止迁移。
- 保留迁移事务回滚和重试路径，不要求人工修改 `schema_migrations` 或删除数据库卷。
- 添加 Docker 空数据卷布局及开发源码回退的回归测试。

## 实际修改文件

- `backend/database/migrations/m0275_huawei_yunshan_platform.py`
- `backend/tests/database/test_m0275_huawei_yunshan_platform.py`
- `docs/plans/plan_20261006_1220_01_yunshan_docker_template_migration.md`
- `docs/walkthrough/walkthrough_20261006_1220_01_yunshan_docker_template_migration.md`
- `docs/fixes/fix_20261006_1224_01_yunshan_docker_template_migration.md`

## 验证命令与结果

- `.venv\Scripts\python.exe -m pytest backend/tests/database/test_m0275_huawei_yunshan_platform.py backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py`：36 passed。
- `.venv\Scripts\python.exe -m compileall -q backend/database/migrations/m0275_huawei_yunshan_platform.py backend/tests/database/test_m0275_huawei_yunshan_platform.py`：通过。
- `python scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过。

## 未验证项

- Docker CLI 未安装，未本机验证镜像构建。
- 未连接远程 Linux 主机，尚未在该主机重建/重启容器。

## 风险与回滚方式

失败迁移在 PostgreSQL 事务内回滚；不需要删除数据卷。若新镜像启动仍异常，可回到先前应用镜像并保留数据库卷，再检查新的容器日志。
