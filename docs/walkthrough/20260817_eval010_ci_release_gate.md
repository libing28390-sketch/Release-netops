# EVAL-010 CI / 发布门禁验证

## 验证目标

确认 PR/main push 使用小型固定评测集，发布 Ubuntu job 使用完整评测集，并确认所有 CI 数据库 URL 均为 PostgreSQL。

## 操作路径

1. 查看 `.github/workflows/knowledge-engine-v2-eval.yml` 的 `small-fixed-set` job。
2. 查看 `.github/workflows/release.yml` 中清理发布树之前的完整评测步骤。
3. 运行 `scripts/knowledge_engine_v2_eval_ci_gate_check.py`，检查 profile、PostgreSQL service、URL scheme 以及 SQLite 引用数。
4. 运行 offline runner 的 `--profile small --strict` 和 `--profile full --strict`。
5. 运行 EVAL-001/003/005/007/009/010 聚焦回归测试。

## 预期结果

- 小集为 4 个固定组件，完整集为 8 个组件。
- 两个工作流均使用 PostgreSQL 16 service 与 `postgresql://` URL。
- SQLite 引用数为 0；离线 runner 只报告 `database=none` / `sqlite=not_used`，不把离线结果当作数据库证据。
- 严格模式通过时返回 0，任何组件失败时返回非零。

## 实际结果

PASS：validator PASS；小集 4/4 PASS；完整集 8/8 PASS；聚焦回归 7 passed；py_compile 和 diff check PASS。
