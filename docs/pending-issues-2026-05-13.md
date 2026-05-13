# 待解决问题记录 — 2026-05-13

## ⚠️ 关键发现：部署在 Ubuntu 虚拟机上

实际使用的 `http://192.168.56.1:4350` **不是本地 Windows**，而是 VirtualBox/VMware 里的 Ubuntu 虚拟机，
通过 `deploy-ubuntu.sh` 脚本部署。本地 Windows 只负责写代码 + push 到 GitHub，
Ubuntu 虚拟机需要 `git pull` 后重新构建才能看到改动。

### 截图一直显示旧界面的根本原因
- 本地 Windows 改了代码并本地 build → `dist/` 更新
- 但本地 Windows 没跑服务，`http://192.168.56.1:4350` 指向的是 Ubuntu 虚拟机
- Ubuntu 虚拟机上的 `dist/` 是 push 之前的旧版本
- **必须到 Ubuntu 上重新 pull + build**

### 明天要做的事
1. 登录 Ubuntu 虚拟机（192.168.56.1）
2. 进入项目目录，`git pull origin main` 拉最新代码
3. 重新执行 `npm run build` 或 `deploy-ubuntu.sh`
4. 重启后端服务（让 `AutomationService.execute_commands` 的新逻辑生效）
5. 刷新浏览器（强制刷新 Ctrl+Shift+R），应能看到：
   - 执行历史详情的每条命令都有 `Raw | Parsed` 切换 + Copy + txt/xlsx/json 下载
   - 定时作业编辑弹窗的 IP 地址输入框紧跟在"设备范围"下拉框下面（不再在底部）

---

## 已在本地完成并 push 的改动清单（commits 在 origin/main）

| Commit | 内容 |
|--------|------|
| `2114691` | 定时作业编辑弹窗：IP 输入框移到"设备范围"下拉框旁 |
| `291b6ce` | 执行历史解析结果同时支持 JSON + Excel 下载 |
| `31110e2` | 修复 `pam_sessions` 缺失 `risk_level` / `risk_summary` 列 |
| `b65450e` | 定时作业并发（10）、修复多命令 join 输出丢失、清理 132 个测试附件 |

---

## Ubuntu 虚拟机上可能需要手动迁移

`pam_sessions` 表如果已经存在，需要补上 `risk_level` 和 `risk_summary` 列。
有两种方式：

**方式 A（推荐）**：重启后端服务即可，`database.py` 启动时会自动 `ALTER TABLE`（已在 commit `31110e2` 中加入）

**方式 B（手动）**：直接 SQL
```sql
ALTER TABLE pam_sessions ADD COLUMN risk_level TEXT DEFAULT 'low';
ALTER TABLE pam_sessions ADD COLUMN risk_summary TEXT DEFAULT '';
```

---

## 历史记录老数据说明

执行历史里 2026-05-13 之前的记录，其 `phases_json.execute.output` 是旧格式（单条混合文本，无 `# cmd\n` 标记），
前端新代码会走 fallback 分支：每条命令一个 block、共享整块 output，仍可独立解析。
**2026-05-13 之后触发的新执行**会有 `# cmd\n` 标记，每条命令有独立 output 片段。
