# 实施计划：修复 Windows 发布 CI 由于 .gitignore 忽略 pgvector 资产导致打包失败

## 1. 任务背景与问题现象
- **问题现象**：
  在 GitHub Actions 运行 release-windows 工作流时，在步骤 `Commit sanitized Windows release tree` 处报错失败：
  ```
  Initialized empty Git repository in D:/a/netsops/netsops/.git/
  [FAIL] Required Windows release path missing: third_party/pgvector/vector.v0.8.6-pg18.zip
  Error: Process completed with exit code 1.
  ```
- **用户疑惑**：
  本地明明存在 `third_party/pgvector/vector.v0.8.6-pg18.zip`，为什么 Actions 会报该路径缺失？
- **根因分析**：
  1. 在 `.github/workflows/release.yml` 的发布步骤中，为了生成干净的 Windows 发布分支，执行了 `rm -rf .git && git init && git add .`；
  2. 根目录的 `.gitignore` 第 114 行写有规则 `vector*.zip`；
  3. Git 规则规定：不带路径分隔符的通配模式将递归作用于所有子目录下的同名文件；
  4. 因此，当 Actions 执行 `git init` 重新初始化仓库并执行 `git add .` 时，Git 根据 `.gitignore` 规则**直接忽略并跳过了** `third_party/pgvector/vector.v0.8.6-pg18.zip`；
  5. 随后在执行 `git ls-files -- "third_party/pgvector/vector.v0.8.6-pg18.zip"` 断言检查时，因其未被暂存而触发 `[FAIL]` 退出。

## 2. 拟修改文件清单
1. `.gitignore`：
   - 增加例外白名单：`!third_party/pgvector/vector.v0.8.6-pg18.zip`。
2. `.github/workflows/release.yml`：
   - 在 `Commit sanitized Windows release tree` 步骤的 `git add .` 之后，显式追加 `git add -f third_party/pgvector/vector.v0.8.6-pg18.zip`，提供双重保险。
3. `docs/plans/plan_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
4. `docs/fixes/fix_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
5. `docs/walkthrough/walkthrough_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`

## 3. 实施与验证步骤
1. 修改 `.gitignore` 并在本地测试验证 `git add .` 行为；
2. 在 `release.yml` 中显式强制包含该资产；
3. 运行 `knowledge_eval_ci_gate_check.py` 验证 CI 门禁通过；
4. 本地提交 Git commit（绝对不 push，等待用户确认）。
