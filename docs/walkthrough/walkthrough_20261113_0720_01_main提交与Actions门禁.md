# main 提交与 Actions 门禁走查

## 提交范围

把近期 IPAM/CMDB 服务与 API、终端角色筛选/重复观察处理、IPAM 导航默认页、接口导入预览和登录粒子交互的代码及其测试纳入同一提交。计划与走查文档也纳入。排除本机 `.agents/`、`handoff.md`、`dist/`、`.codex*`、`dist-*`、后端运行工件、日志、输出目录、现场审核 CSV 和截图/PDF/JSON。

## 发现并处理的验证问题

- 终端表格与 CSV 已使用“IPAM 主机名”“采集设备”，详情来源名称统一为“来源”；旧测试仍断言之前字段名，已同步断言。
- 接口生成现在先调用只读导入预览，再由用户在“核对导入结果”确认；旧集成测试只模拟了直接生成。已补充预览响应和最终确认步骤，保留导入流程验证。
- 网关无匹配时根据已填写网关 IP 显示“没有接口与填写的网关 IP 匹配；已保留人工设备选择。”，测试断言按当前精确提示更新。

## 验证状态

- `python scripts/validate_postgresql_only.py`：通过，0 项违规。
- 本机 pytest 未运行。本机没有 `DATABASE_URL`；测试 fixture 会初始化 source DB，且无法证明本机 PostgreSQL 目标可丢弃。后端全量测试由 `release.yml` 提供的隔离 PostgreSQL 服务运行。
- 前端 focused Vitest：10 个文件、96 项测试全部通过。
- `npm run lint`：通过（`tsc --noEmit`）。
- `npm run build`：通过，Vite 转换 4364 个模块，15.96 秒。
- `python scripts/validate_postgresql_only.py`：通过，0 项违规。
- 本机 pytest 未运行。本机没有 `DATABASE_URL`；测试 fixture 会初始化 source DB，且无法证明本机 PostgreSQL 目标可丢弃。后端全量测试由 `release.yml` 提供的隔离 PostgreSQL 服务运行。
- 该 push 对应的 Actions 状态以 GitHub 上精确 commit SHA 为准，并在任务交付中报告。

## Actions 流程

推送 `main` 会触发 `.github/workflows/release.yml` 的后端 pytest、PostgreSQL-only 检查、前端 lint/test/build、部署输入检查和发布同步。跟踪推送提交的全部 job；若失败，读取失败步骤日志、修复并推送新提交，直到最终 SHA 的所有必需检查成功。
