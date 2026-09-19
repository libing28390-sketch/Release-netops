# 修复记录：修复 Windows 发布 CI 由于 .gitignore 忽略 pgvector 资产导致打包失败

## 1. 问题现象
GitHub Actions 在运行 Windows 发布分支构建（`release.yml` 的 `release-windows` 作业）时，在步骤 `Commit sanitized Windows release tree` 失败：
```
Initialized empty Git repository in D:/a/netsops/netsops/.git/
[FAIL] Required Windows release path missing: third_party/pgvector/vector.v0.8.6-pg18.zip
Error: Process completed with exit code 1.
```
但在本地与源码树中，`third_party/pgvector/vector.v0.8.6-pg18.zip` 实际存在。

## 2. 根因分析
1. **工作流清洗逻辑**：在 `release.yml` 中，为了打包纯净的公共 Windows 分支，工作流执行了：
   ```bash
   rm -rf .git
   git init
   git add .
   ```
2. **.gitignore 通配规则**：项目的根目录 `.gitignore` 第 114 行定义了：
   ```gitignore
   # Large executables and installers
   postgresql-installer.exe
   diagnostic_report.zip
   vector*.zip
   ```
3. **Git 忽略判定行为**：
   在 Git 规范中，未包含路径分隔符 `/` 的通配规则（如 `vector*.zip`）会递归作用于仓库所有子目录下的同名文件。因此当重新 `git init` 并执行 `git add .` 时，Git 根据该规则自动将 `third_party/pgvector/vector.v0.8.6-pg18.zip` 排除在外，未将其纳入暂存区。
4. **校验断言失败**：
   后续脚本通过 `git ls-files -- "third_party/pgvector/vector.v0.8.6-pg18.zip"` 检查该文件是否在 Git 暂存区中，因未被暂存导致断言失败退出。

## 3. 解决方案与修改内容
1. **更新 `.gitignore` 白名单**：
   在 `.gitignore` 中的 `vector*.zip` 之后显式追加例外白名单：
   ```gitignore
   vector*.zip
   !third_party/pgvector/vector.v0.8.6-pg18.zip
   ```
2. **优化工作流发布暂存逻辑 (`.github/workflows/release.yml`)**：
   在 `release.yml` 的 `git add .` 之后，显式追加强制暂存命令：
   ```bash
   git add .
   git add -f third_party/pgvector/vector.v0.8.6-pg18.zip
   ```
   实现双重保险，避免未来任何规则调整误将关键资产剔除。

## 4. 实际修改文件
- `.gitignore`
- `.github/workflows/release.yml`
- `docs/plans/plan_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
- `docs/fixes/fix_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`
- `docs/walkthrough/walkthrough_20260919_1640_01_修复Windows发布CI由于gitignore忽略pgvector资产失败.md`

## 5. 验证命令与结果
1. **干净 Git 仓库初始化与暂存模拟测试**：
   - 编写沙盒测试模拟 `git init && git add .`；
   - 结果：`git ls-files` 准确列出 `third_party/pgvector/vector.v0.8.6-pg18.zip`。
2. **CI 门禁检查**：
   - 命令：`.venv\Scripts\python.exe scripts/knowledge_eval_ci_gate_check.py`；
   - 结果：`{"status": "PASS", "task_id": "EVAL-010"}`，全量门禁检查通过。

## 6. 风险与回滚方式
- **风险**：极低。仅针对 Windows 必要的 pgvector 预置发布包进行白名单与强制暂存保护。
- **回滚方式**：可通过本地 Git 提交进行回滚。未执行远程 push。
