# GitHub Actions 发布门禁收敛计划

## 任务目标

将普通 `main` push 触发的四个独立工作流收敛为一个对外发布工作流，并确保前端和后端检查通过后，才同步公开仓库的 `main` 与 `windows` 分支。知识引擎评估不再参与普通 push。

## 现状 / 问题

- `release.yml`、前端检查、后端检查和知识引擎评估会被同一批提交分别触发。
- `release.yml` 已重复执行前端类型检查、测试和构建。
- 后端 pytest 与发布并行运行；后端检查失败时，发布仍可能成功并同步公开仓库。
- 知识引擎评估虽然有路径过滤，但普通 push 没有必要执行该专项评估。

## 影响范围

- GitHub Actions 的 `main` push、Pull Request、tag 和手动发布行为。
- 公开发布仓库 Ubuntu/Linux `main` 与 Windows `windows` 分支的同步门禁。
- 不改变应用业务代码、数据库、真实设备或线上配置。

## 拟修改文件

- `.github/workflows/release.yml`
- `.github/workflows/frontend-build-check.yml`
- `.github/workflows/backend-pytest-check.yml`
- `.github/workflows/knowledge-engine-eval.yml`
- `docs/walkthrough/walkthrough_20260908_0756_01_GitHubActions发布门禁收敛.md`

## 实施步骤

1. 让前端和后端独立检查仅用于 Pull Request，取消其普通 `main` push 触发。
2. 取消知识引擎评估的普通 `main` push 触发，仅保留 PR 和手动专项评估；正式 tag/manual 发布仍由 `release.yml` 执行完整知识门禁。
3. 在 Ubuntu 发布同步前安装后端依赖并执行完整 pytest；任一门禁失败均阻止 Ubuntu 和后续 Windows 同步。
4. 保留 tag/manual 的完整发布门禁、GitHub Release 和百度网盘行为。

## 验证计划

- 使用 PyYAML 解析所有修改后的 workflow 文件。
- 静态验证普通 main push 只剩 `release.yml` 入口，PR 工作流仍保留。
- 验证普通 `main` push 不再独立触发前端、后端或知识引擎工作流。
- 运行现有发布工作流契约检查脚本；检查 diff 中无凭据或无关改动。

## 风险与回滚思路

- 风险：普通 push 的发布耗时会增加完整后端 pytest 时间，但可以换取发布前门禁。
- 风险：知识模块的普通 main 提交不再获得专项评估；相关 PR、手动评估以及正式 tag 发布仍覆盖该门禁。
- 回滚：恢复三个工作流的 `push` 触发，并移除 release 中新增的后端 pytest 步骤。
