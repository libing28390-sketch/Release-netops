# 执行走查报告：修复 Windows 发布 CI 由于 .gitignore 忽略 pgvector 资产导致打包失败

## 1. 任务完成摘要
定位并彻底修复了 GitHub Actions Windows 分支发布时 `[FAIL] Required Windows release path missing: third_party/pgvector/vector.v0.8.6-pg18.zip` 的根因：
1. **定位根因**：`.gitignore` 中配置了全局匹配的 `vector*.zip`，而 release 工作流构建纯净 Windows 发布分支时通过 `git init && git add .` 重新构建索引，导致 `third_party/pgvector/vector.v0.8.6-pg18.zip` 被 Git 默认忽略未被暂存，导致后续 `git ls-files` 判定缺失；
2. **落地修复**：
   - 在 `.gitignore` 中针对 `third_party/pgvector/vector.v0.8.6-pg18.zip` 增加了例外白名单 `!third_party/pgvector/vector.v0.8.6-pg18.zip`；
   - 在 `.github/workflows/release.yml` 的 `Commit sanitized Windows release tree` 步骤中增加 `git add -f third_party/pgvector/vector.v0.8.6-pg18.zip` 显式强制包含，构成双保险机制；
3. **完成验证**：
   - 模拟干净目录的 `git init && git add .`，确认 `vector.v0.8.6-pg18.zip` 成功被索引；
   - 运行 `knowledge_eval_ci_gate_check.py` 确保 CI 门禁一致性校验通过。

## 2. 实际修改文件
- `.gitignore`
- `.github/workflows/release.yml`
- `docs/plans/plan_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
- `docs/fixes/fix_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
- `docs/walkthrough/walkthrough_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`

## 3. 约束执行
- 本次改动仅在本地验证并提交，**绝未执行 `git push`**。
