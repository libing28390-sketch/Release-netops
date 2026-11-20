# 任务目标

将工作区中近期 IPAM、CMDB 接口采集/VRF、终端登记/筛选、IPAM 导航入口及登录粒子交互相关的应用代码、测试和交付文档提交并推送到 `main`，然后确认对应 SHA 的 GitHub Actions 全部成功。

## 现状

- 当前分支为 `main`，fetch 后本地 `main` 与 `origin/main` 同步；工作区有多项待提交源码修改和新增测试。
- 工作区还包含内部协作规则、`handoff.md`、生成构建目录、日志/输出、后端运行工件、现场审核 CSV 和历史视觉证据；这些不属于应用源码提交范围。
- 仓库要求每次提交同批附一份新的 `docs/fixes/fix_*.md`。推送 `main` 会触发 `release.yml` 中定义的 Actions 与发布同步任务。

## 提交范围

- 纳入当前已修改/新增的后端 IPAM/CMDB 服务与接口代码及相关测试。
- 纳入当前已修改/新增的前端 IPAM/CMDB、IPAM 工作台导航和登录粒子交互代码及相关测试。
- 纳入这些任务已有的计划/走查 Markdown，以及本任务新建的计划、走查和提交修复记录。
- 排除 `.agents/`、`handoff.md`、`dist/`、`.codex*`、`dist-*`、`backend/artifacts/`、`logs/`、`output/`、现场 CSV 与图片/PDF/JSON 等用户和生成工件。

## 实施步骤

1. 再核对候选 diff 和远端状态，只将上述应用源码、测试和文档显式暂存。
2. 运行受影响后端 pytest、前端 Vitest、TypeScript/build、PostgreSQL-only 扫描及差异检查；确保测试目标使用隔离测试数据库。
3. 创建一笔带新 `docs/fixes/fix_*.md` 记录的 `main` 提交并推送到 `origin/main`。
4. 记录精确 commit SHA，跟踪该 SHA 触发的全部 Actions；若失败，按日志修复并继续跟踪最新提交，直到成功。

## 验证计划

- 后端：IPAM 地址空间、接口快照候选、网关候选、终端发现、CMDB VRF/接口采集等受影响测试；运行 `python scripts/validate_postgresql_only.py`。本机未配置 `DATABASE_URL`，测试 fixture 会先对 source DB 执行 `database.init_db()`；没有证据证明本机 PostgreSQL 目标库可丢弃，因此本机 pytest 暂停，依赖 Actions 中明确隔离的 PostgreSQL 服务运行全量测试。
- 前端：相关 Vitest、`npm run lint` 和隔离输出目录的 `npm run build` 等价命令。
- 提交：`git diff --cached --check`、提交文件清单、`git status`、远端 SHA 对账。检查时发现前端旧断言仍假设直接生成、旧表头和旧网关提示；已调整到核对导入的新流程与当前列名后复测，10 个定向文件 96 项全部通过。
- 远端：GitHub Actions 对最终 SHA 全部完成并成功；不以本地结果代替 Actions。

## 风险与回滚

- 推送 `main` 会运行仓库的 `release.yml` 自动流程，其中包含发布同步步骤；这是此次主线推送所触发的既有工作流。
- 不使用 `reset --hard`、`git clean` 或强制推送；未暂存文件必须保留。
- 如需回退应用改动，在 `main` 提交 `git revert <commit>`；不回滚运行时数据库或其他现场状态。
