# Docker 默认管理员密码恢复执行记录

## 完成摘要

已恢复默认管理员凭据 `admin / admin`。全新数据库会创建 bcrypt 格式的默认密码；若管理员账号不存在，启动也会补建。已有有效 bcrypt 密码会保留，只有密码缺失或格式无效时才修复为默认密码。数据库恢复出厂流程不再要求 `INITIAL_ADMIN_PASSWORD`。

## 实际修改文件

- `backend/database/schema.py`
- `backend/database/reset.py`
- `backend/tests/security/test_audit_regressions.py`
- `backend/tests/conftest.py`
- `desktop/desktop_tray.py`
- `.env.example`
- `README.md`
- `docs/deploy/docker.md`
- `DEPLOY.md`

`.env.example` 与 `docs/deploy/docker.md` 原本包含未提交的 Redis 配置调整；本次保留这些既有内容，只删除过时初始密码变量并补充默认登录说明。

## 关键实现

- Bootstrap 现在按 username 查询管理员；缺少时以 bcrypt 创建 `admin`。普通用户已存在时也会补建管理员。
- 已有格式有效的 bcrypt 密码不会因启动或升级而改变。无效密码会重置为默认密码。
- 测试夹具不再设置 `INITIAL_ADMIN_PASSWORD`，避免测试依赖已移除的环境变量。
- Docker/统一部署文档和 Windows 数据库重置提示统一写明默认账号密码，并提醒首次登录后立即改密。

## 验证命令与结果

- `pytest backend/tests/security/test_audit_regressions.py -k "bootstrap or database_reset" -q`：4 passed，17 deselected，78.42 秒。通过独立 `nexora_pytest_*` 临时 PostgreSQL 数据库执行，测试后已清理临时 source DB。
- bcrypt 登录校验器冒烟测试：默认密码通过，错误密码拒绝。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：通过，0 项违规。
- `.venv/Scripts/python.exe -m py_compile backend/database/schema.py backend/database/reset.py backend/tests/security/test_audit_regressions.py backend/tests/conftest.py desktop/desktop_tray.py`：通过。
- `git diff --check`：通过。

## 未执行验证

- 完整 `pytest backend/tests` 未运行；本次影响仅限管理员 bootstrap/reset 回归用例。
- Docker Compose 配置校验与容器重建未执行：当前环境没有 Docker CLI；本次没有请求对部署环境执行更新。

## 剩余风险与建议

`admin / admin` 是公开默认口令，首次登录后应立即修改。此前已用其他密码成功初始化的数据库保留其有效密码；发布本次代码不会自动把这类现有账号改回 `admin`。旧 `.env` 中残留的 `INITIAL_ADMIN_PASSWORD` 不再参与初始化。

回滚应用代码不会改变现有用户数据。本次没有直接修改任何部署数据库。
