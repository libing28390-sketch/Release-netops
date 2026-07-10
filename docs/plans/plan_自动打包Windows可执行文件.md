# 自动打包 Windows 可执行文件 实施计划

本计划旨在对 GitHub Actions 持续集成流程进行升级，实现提交代码时在云端自动编译打包 `NetOps.exe` 并发布，免去在本地手动打包并向 Git 仓库提交大体积二进制文件的繁琐过程。

## 目标与改动概述

目前，Windows 分支的同步流 [.github/workflows/release.yml](file:///d:/netops/netsops-main/.github/workflows/release.yml) 在 Linux 环境下运行，仅做简单的文件清理和推送，本身无法自动编译生成 `.exe` 可执行文件。这导致如果我们在本地开发修改了代码，必须在本地 Windows 环境手动运行 PyInstaller 打包，再将生成后的 `NetOps.exe` 二进制文件提交推送到 Git 仓库。

为了实现全自动编译和发布，我们将：
1. 将 `release-windows` 的运行环境由 `ubuntu-latest` 变更为 `windows-latest`。
2. 在该工作流中加入 Python 环境配置与打包依赖（`pyinstaller`、`PySide6`、`pillow`、`pystray`、`certifi`）的安装步骤。
3. 执行 `pyinstaller NetOps.spec` 动态编译生成最新的 `NetOps.exe`，并覆盖项目根目录下的旧文件。
4. 后续清理敏感文件与推送至对外发布仓库 `Release-netops` 的 `windows` 分支依然保持，但通过显式指定 `shell: bash` 确保与现有 shell 命令完美兼容。

---

## 方案设计

### 1. 修改 `release.yml` 的 `release-windows` 作业

我们计划将 `release-windows` 修改为如下结构：

```yaml
  release-windows:
    name: Release Windows (windows branch)
    needs: release-ubuntu
    runs-on: windows-latest  # 使用 Windows 环境以支持打包 exe
    steps:
      - name: 1. 拉取开发库代码
        uses: actions/checkout@v4

      - name: 1.5. 安装 Python 3.11 环境
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: 1.6. 安装 PyInstaller 及打包依赖
        run: |
          python -m pip install --upgrade pip
          pip install pyinstaller PySide6 pillow pystray certifi
        shell: bash

      - name: 1.7. 执行 PyInstaller 编译 NetOps.exe
        run: |
          pyinstaller NetOps.spec
          # 将生成的 NetOps.exe 复制到根目录覆盖旧的
          cp dist/NetOps.exe ./NetOps.exe
          # 清除打包临时目录以保证后续提交的干净度
          rm -rf build/ dist/
        shell: bash

      - name: 2. 彻底清理敏感文件、开发源码与 Linux/Docker 专属文件
        run: |
          # ── 开发者专用工具 ──
          rm -rf tools/

          # ── 编译脚本及 Windows 客户端工具（客户不需要）──
          rm -rf scripts/

          # ── 开发者内部文档 / 笔记 ──
          rm -f bug_fix_memory.md
          rm -f PAM_Audit_Restoration_Report.md
          rm -rf docs/
          rm -rf brain/
          rm -rf skills/
          rm -rf .github/skills/
          rm -rf .agents/

          # ── 测试 / 调试脚本与自动化单元测试用例（商用脱敏，不暴露给客户） ──
          rm -rf scratch/
          rm -rf backend/scratch/
          rm -rf backend/tests/
          rm -f pytest.ini
          rm -f backend/_check_audit.py
          rm -f backend/check_executions.py
          rm -f backend/check_results.py
          rm -f backend/debug_device.py
          rm -f backend/find_target.py
          rm -f _purge_bogus_backups.py
          # 任何在仓库根目录残留 of _xxx.py 临时排障脚本一律剔除
          find . -maxdepth 2 -type f -name '_*.py' -not -path './.git/*' -delete || true

          # ── 临时部署补丁 / 排障脚本（开发期使用，正式发布不需要） ──
          rm -f patch-vmware.sh
          rm -f patch-*.sh
          rm -f hotfix-*.sh

          # ── 历史任务进度 / 开发期 todo（绝对不能发给客户） ──
          rm -f task.md task_progress.md
          rm -f task-*.md task_*.md
          rm -f implementation_plan.md walkthrough.md
          rm -f refactor.cjs refactor2.cjs

          # ── 本地数据库文件（客户应使用自己的 PostgreSQL）──
          rm -f netops.db backend/netops.db backend/netsops.db

          # ── AI 助手 / IDE 残留文件 ──
          rm -rf .codex/ .cursor/ .playwright-mcp/ .vscode/
          rm -f .clinerules .cursorrules .geminirules mcp-config.json
          rm -f -- "--version"

          # ── Linux/Docker 专属文件清理（只发给 Windows 用户） ──
          rm -f deploy-ubuntu.sh deploy-ubuntu.gitee.sh Dockerfile docker-compose.yml .dockerignore
          rm -rf nginx/

          # ── GitHub Actions 配置（发布仓库不需要 CI）──
          rm -rf .github/
        shell: bash

      - name: 3. 将处理后的安全代码推送到对外发布仓库 windows 分支
        run: |
          # 配置自动化机器人的 Git 身份
          git config --global user.name "GitHub Action Bot"
          git config --global user.email "action@github.com"
          
          # 抹除之前在开发库里的所有 Commit 历史记录（防止客户从历史里翻到源码）
          rm -rf .git
          git init
          git add .
          git commit -m "🚀 Release build: Production ready stable Windows release"
          
          # 推送到客户专门用的发布库 Release-netops 的 windows 分支
          git branch -M windows
          git remote add origin https://${{ secrets.RELEASE_REPO_TOKEN }}@github.com/libing28390-sketch/Release-netops.git
          git push -u origin windows --force
          
          # 针对 Windows 分支的提交创建独特的 Tag 并强制推送 (仅在推送版本标签时执行)
          if [[ "${{ github.ref }}" == refs/tags/* ]]; then
            git tag "${{ github.ref_name }}-windows"
            git push origin "${{ github.ref_name }}-windows" --force
          fi
        shell: bash
```

---

## 细节考量与潜在挑战

1. **构建时间与资源限制**：
   `windows-latest` 的启动和包安装比 `ubuntu-latest` 稍慢一些。然而，因为打包所需的依赖非常精简（仅限客户端的 GUI 相关依赖如 `PySide6` 等，而不必安装庞大的后端数据库驱动、AI 依赖等），所以打包过程预计在 2~3 分钟内即可完成，完全在合理范围内。
2. **Bash 脚本兼容性**：
   在 `windows-latest` 上，GitHub Actions 的原生 `shell: bash` 运行在 Git Bash 环境中，能完美运行诸如 `rm -rf`、`cp`、`find` 等 Linux 命令。我们只需给相关步骤显式加上 `shell: bash` 属性即可。
3. **敏感文件清理安全性**：
   我们保留了原先的脱敏指令，因此发布到 Gitee/Github 发布仓库的代码安全性依然有 100% 的保障，且客户端拿到的 `NetOps.exe` 必定是由当前提交的 `desktop/launcher.py` 代码当场编译生成的。

---

## 验证计划

1. **YAML 语法检查**：
   使用 linter 或检查器验证修改后的 `release.yml` 语法。
2. **模拟触发验证**：
   提交更新后，在 GitHub 上触发该 Actions，检查 `Release Windows` 任务是否执行成功。
   - 验证 Python 是否成功安装。
   - 验证 PyInstaller 打包是否有异常报错。
   - 验证最终推送到发布仓库的 `windows` 分支中的 `NetOps.exe` 文件大小及生成时间是否更新。
