# PostgreSQL 18 统一基线实施记录

## 完成摘要

- Nexora 的 Windows、后端启动、Docker、CI 和当前部署说明统一为 PostgreSQL 18；Windows 新装固定使用 PostgreSQL 18.6。
- 启动时在数据库 schema 写入及迁移前检查 `server_version_num`，非 PG18 会明确停止并提示 `pg_upgrade` 或 `pg_dump`/`pg_restore`。Windows 向导会在数据库扩展检查前拒绝非 PG18，pgvector Windows 安装资产目录只保留 PG18 映射。
- Windows 发布资产使用 `vector.v0.8.6-pg18.zip`，本地文件已放到安装器实际读取的 `third_party/pgvector/`。SHA-256 为 `bda17eb97d9e687e3da701adbf4b65a342943b3e0cdc81935ccf0b9833a1ed62`，与配置固定值一致。
- PyInstaller 发布依赖安装并显式收集 `psycopg2`，修复了 EXE 运行时在自身 PyInstaller 环境导入、但只在 `.venv` 安装依赖造成的解释器错位。
- 已定位并排除 QtCore 报错根因：PyInstaller 误将构建机 Codex/Poppler ICU 78 的 `icuuc.dll` 收到应用目录，抢先于 Windows 系统 ICU 加载。Windows 发布 workflow 固定 PyInstaller `6.22.1`、hooks-contrib `2026.6`、PySide6 `6.11.1`、psycopg2-binary `2.9.13`，并在构建后要求 smoke-test marker。
- 已配置的快速启动会先显示 PostgreSQL 18 连接目标并等待用户确认。首次/重新配置时要求输入两次非空数据库密码；不一致时不启动部署、不写入 `.env`。部署开始后向导会自动从 `.env.example` 创建 `.env`（若不存在），再写入所选数据库配置。
- PG17 到 PG18 是数据库主版本升级。现有 PG17 数据目录和 Docker volume 不能直接交给 PG18；部署文档要求先备份，再用 `pg_upgrade` 或逻辑备份恢复。

## 实际修改文件

- Windows 启动、确认和密码校验：`desktop/launcher.py`、`desktop/tests/test_launcher_start_confirmation.py`。
- PG18 运行时门禁：`backend/database/schema.py`、`backend/tests/database/test_postgres_version_contract.py`。
- Docker PG18 持久化：`docker-compose.yml` 将 `nexora-pgdata` 挂载到官方 PostgreSQL 18 的父数据目录 `/var/lib/postgresql`，发布契约禁止旧 `/var/lib/postgresql/data` 挂载点。
- pgvector 资产与 Windows 发布打包：`desktop/pgvector_windows.py`、`desktop/tests/test_pgvector_windows.py`、`third_party/pgvector/README.md`、`third_party/pgvector/vector.v0.8.6-pg18.zip`、`NetOps.spec`、`.github/workflows/release.yml`。
- Docker、静态发布合同与清单：`docker/postgres/Dockerfile`、`docker-compose.yml`、`scripts/knowledge_eval_ci_gate_check.py`、`docs/knowledge-engine/eval/eval-ci-gate-v1.manifest.json`。
- 当前部署材料：`README.md`、`DEPLOY.md`、`docs/README_gitee.md`、`docs/deploy/README.md`、`docs/deploy/windows.md`、`docs/deploy/windows_pgvector_guide.md`、`docs/deploy/docker.md`、`docs/deploy/docker-release-manual.md`、`docs/blog/netops_deployment_docs.md`、`docs/blog/nexora_docker_deployment_article.md`、`docs/blog/docker_deploy_guide.md`。
- `backend/services/collection_plan_service.py` 只更新了 PostgreSQL 基线注释。

## 验证命令与结果

- 定向单测：`python -m pytest --noconftest desktop/tests/test_launcher_start_confirmation.py desktop/tests/test_pgvector_windows.py backend/tests/database/test_postgres_version_contract.py -q -p no:cacheprovider`：`19 passed`。
- Windows 版本门禁加入最终硬拒绝后，重跑 `desktop/tests/test_launcher_start_confirmation.py desktop/tests/test_pgvector_windows.py`：`15 passed`；后端版本测试与该轮之间未改动，前一轮 18 项结果中已通过。
- 发布契约：`python scripts/knowledge_eval_ci_gate_check.py`：`PASS`，覆盖 PG18 Docker image/持久卷路径、Windows 18.6、PG18 pgvector 哈希和 psycopg2 打包标记。
- PostgreSQL-only 扫描：`python scripts/validate_postgresql_only.py`：`0 violation(s)`。
- `py_compile`：所有改动 Python 文件通过；使用隔离 `PYTHONPYCACHEPREFIX` 避开原 `.venv` 写入权限问题。
- YAML：`release.yml`、`docker-compose.yml` 与自定义 PostgreSQL action 均由 PyYAML 解析通过。
- `git diff --check`：通过。PG18 ZIP 实际 SHA-256 与预期一致。
- 根因 A/B 已确认：失败包的 `PKG-00.toc` 将 `C:\Users\NINGMEI\.cache\codex-runtimes\...\poppler\Library\bin\icuuc.dll` 打包成根目录 `icuuc.dll`；该 ICU 78 DLL 缺少 Qt6Core 需要的 20 个未版本化导出，导致 WinError 127。过滤 Poppler 路径下的 ICU DLL 后，包内不再包含 `icuuc.dll`/`icudt78.dll`，QtCore 改为加载 Windows System32 的 ICU。
- Windows PyInstaller `6.22.1` / hooks-contrib `2026.6` clean build：打包归档包含 `psycopg2`、`psycopg2._psycopg`、`libpq` 且无 Poppler ICU。新 EXE `--smoke-test` 退出码 `0`，日志包含 `SMOKE_TEST_OK`。
- 已验证隔离包：`artifacts/pg18-pyinstaller-6221/filtered-dist/NetOps.exe`，SHA-256 `aa33cb65fa2b1a57d20129f715b923785c007f0837ef753118cd5994e0a0bfb2`；归档包含 `psycopg2\_psycopg.cp311-win_amd64.pyd` 与 `libpq`，不含 `icuuc.dll`/`icudt78.dll`。

## 未执行及剩余风险

- 当前环境没有 Docker CLI，因此没有实际构建或启动 PostgreSQL 18 容器；镜像标签、数据卷路径、PG18 Windows asset URL 与 SHA-256 已静态校验。
- 未连接用户的真实 PostgreSQL 数据库，也未执行 PG17 到 PG18 的真实数据升级。
- 本机 Windows 10 的隔离新 EXE smoke test 已通过；未在干净 Windows 10/11 VM 验证系统 ICU 是否齐全。CI smoke gate 将阻止之后的打包回归。
- 未推送、打标签或发布。仓库原有 `NetOps.exe` 未覆盖；根目录已有的 PG17 ZIP 和 `handoff.md` 用户变更保留。
- 隔离打包诊断产物留在 `artifacts/pg18-pyinstaller-6221/` 供复查；其中只包含本次临时构建和对照 spec，不属于发布输入。
