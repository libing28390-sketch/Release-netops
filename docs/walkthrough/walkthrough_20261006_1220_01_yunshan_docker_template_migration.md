# YunShan Docker 模板迁移启动故障

## 完成摘要

修复数据库迁移 0275 在 Docker 部署中误从 `/app/data/textfsm_templates` 读取发布模板的问题。迁移现在优先使用镜像内只读目录 `/app/release-textfsm-templates`，并在开发源码目录回退；全部迁移模板会在任何数据库写入前完成校验。

## 实际修改文件

- `backend/database/migrations/m0275_huawei_yunshan_platform.py`
- `backend/tests/database/test_m0275_huawei_yunshan_platform.py`
- `docs/plans/plan_20261006_1220_01_yunshan_docker_template_migration.md`
- `docs/walkthrough/walkthrough_20261006_1220_01_yunshan_docker_template_migration.md`
- `docs/fixes/fix_20261006_1224_01_yunshan_docker_template_migration.md`

## 关键实现

- 检查镜像发布目录中的六个必需模板；只有目录完整时才使用它。
- 镜像目录不完整时，兼容使用开发源码 `data/textfsm_templates`，同样要求完整。
- 两处都不完整时，一次列出两个候选目录中的缺项，并在写入平台/模板记录之前终止迁移。
- 现有迁移执行器会回滚失败迁移的 PostgreSQL 事务；修复模板后可安全重试，不需要手工修改版本表或清空持久卷。

## 验证命令与结果

- `.venv\Scripts\python.exe -m pytest backend/tests/database/test_m0275_huawei_yunshan_platform.py backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py`：36 passed。
- `.venv\Scripts\python.exe -m compileall -q backend/database/migrations/m0275_huawei_yunshan_platform.py backend/tests/database/test_m0275_huawei_yunshan_platform.py`：通过。
- `python scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过。

## 未执行验证及原因

- 本工作站未安装 Docker CLI，因此未能本机执行镜像构建或检查容器文件系统。
- 未连接用户的远程 Linux 主机，未直接重建或重启其容器。

## 部署步骤

将包含此修复的版本同步到 Linux 上的 Compose 工作目录后执行：

```bash
docker compose build netops
docker compose up -d --no-deps --force-recreate netops
docker compose up -d
docker compose ps -a
docker logs --tail 200 nexora-netops
```

确认应用健康后，迁移 0275 应能完成；依赖应用健康状态的 nginx、vmagent 和 snmp-exporter 随后可启动。

## 剩余风险与建议

模板目录若在未来被重命名，需要同步修改 Dockerfile 和迁移路径契约。当前工作站未验证 Linux 镜像构建；应用新镜像前仍应确认远程主机采用包含此补丁的源码/发布包。
