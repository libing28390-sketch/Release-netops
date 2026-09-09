# GitHub Actions 发布门禁收敛走查

## 完成摘要

- 普通 `main` push 现在只触发 `Build and Sync to Release Repo`。
- 前端、后端独立 workflow 仅保留 Pull Request 检查，避免与 release 重复运行。
- 知识引擎评估不再由普通 `main` push 触发，仅保留 Pull Request 和手动执行。
- release 的 Ubuntu job 在公开仓库同步前安装后端依赖、执行隔离配置检查、PostgreSQL-only 检查和完整 pytest。
- Windows job 继续依赖 Ubuntu job，因此后端门禁失败时，两个公开分支都不会同步。
- tag/manual 的完整知识评估、百度网盘上传和 GitHub Release 条件保持不变。

## 实际修改文件

- `.github/workflows/release.yml`
- `.github/workflows/frontend-build-check.yml`
- `.github/workflows/backend-pytest-check.yml`
- `.github/workflows/knowledge-engine-eval.yml`
- `docs/plans/plan_20260908_0756_01_GitHubActions发布门禁收敛.md`
- `docs/walkthrough/walkthrough_20260908_0756_01_GitHubActions发布门禁收敛.md`

## 关键实现说明

1. 从三个专项 workflow 中移除 `push` 入口，但保留原有 PR 路径过滤。
2. `knowledge-engine-eval.yml` 继续支持手动专项评估；正式 tag/manual 的完整知识门禁仍位于 `release.yml`。
3. `release.yml` 的测试环境补齐 Redis、AI mock、合成数据和 fixture 凭据来源配置。
4. Ubuntu 发布在清理、提交和强制推送公开仓库之前执行完整 pytest；失败会直接终止 job。
5. Windows 发布的 `needs: release-ubuntu` 未改变，继续继承 Ubuntu 门禁结果。

## 验证命令与结果

- PyYAML 解析 `.github/workflows/*.yml`：`YAML PASS: 5 workflows`。
- 以 `os.devnull` 替代报告输出运行 `scripts/knowledge_eval_ci_gate_check.py::validate_ci_gate()`：`RELEASE CONTRACT: PASS`，未改写评估 manifest。
- 自定义触发/顺序断言：`TRIGGER/GATE MATRIX: PASS`；确认普通 main push 仅 release 有入口、三个专项 workflow 均无 push、pytest 位于公开同步之前。
- `git diff --check --`：退出码 0；仅显示现有 Git 行尾转换提示，无空白错误。
- 独立 verification worker 复核 YAML、触发矩阵、Ubuntu/Windows 门禁继承、tag/manual 与百度网盘条件：PASS。

## 未执行验证及原因

- 未执行全量应用 pytest、前端构建或真实 GitHub Actions：本次仅修改 workflow 编排，依据质量门禁规则采用配置解析和发布契约验证；真实 Actions 需在用户授权提交并 push 后才能执行。
- 未运行 `actionlint` / `yamllint`：当前环境未安装；已由 PyYAML 和项目契约检查覆盖语法及关键行为。

## 剩余风险 / 后续建议

- 普通 push 的单个 release workflow 会比原 release 多出完整后端 pytest 时间，但不会再并行产生后端失败而公开发布成功的状态。
- 知识模块的 main 直推不再执行专项评估；应通过 PR、手动运行或正式 tag 发布完成专项门禁。
- 当前 `git push origin main --tags` 仍可能分别产生 main 与 tag 两个 release 事件；本次按用户要求只收敛普通无 tag push，后续可单独优化版本发布的重复事件。
