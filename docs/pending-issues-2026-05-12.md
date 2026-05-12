# 待解决问题记录 — 2026-05-12

## 问题一：执行历史详情页 Raw/Parsed 切换按钮未显示

### 现象
`/automation/history` 执行历史详情弹窗，点击设备后右侧面板只显示原始输出文本块，
右上角只有旧的"复制"和"下载"两个按钮，没有出现每条命令的 `Raw | Parsed` 切换控件。

### 已完成的代码改动
- `src/pages/AutomationHistoryTab.tsx` 已重构输出渲染逻辑：
  - `splitOutputByCommand()`：兼容新格式（`# cmd\n` 标记分割）和旧格式（无标记时按 commands 数组每条命令创建独立 block）
  - 每个命令 block 有独立的 `Raw | Parsed` 切换、复制、`.txt` 下载
  - 解析成功后出现绿色 `.csv` 导出按钮（UTF-8 BOM，Excel 可直接打开）
  - `downloadExcel()` 函数已实现
- `backend/api/playbooks.py` 新增 `POST /api/playbooks/{execution_id}/devices/{device_id}/parse` 接口
- `backend/services/automation_service.py` 修复多命令 join 问题（逐条 `send_command`）
- 前端已重新构建（`npm run build` 成功，`AutomationHistoryTab-CeVK9Xa8.js` 已生成）

### 根本原因（待确认）
代码和构建都没问题，但浏览器/服务端仍在使用旧版本。
**需要确认部署方式**：项目不使用 Docker，需要确认前端静态文件是如何服务的（uvicorn 直接 serve dist/？还是其他方式），以及如何让新构建的 `dist/` 生效。

### 明天排查步骤
1. 确认前端静态文件服务方式（查看 `main.py` 的 `StaticFiles` 挂载路径）
2. 确认 `dist/` 目录是否已更新到服务器
3. 强制刷新浏览器（Ctrl+Shift+R）或清除缓存后重试
4. 如果还不行，在浏览器 DevTools Network 里确认加载的 `AutomationHistoryTab-*.js` 的 hash 是否是新的

---

## 问题二：定时巡检执行历史输出为空（已修复，待验证）

### 现象
`/automation/history` 里定时作业（思科设备定时巡检）执行失败，详情页只显示命令列表，没有实际输出内容。

### 根本原因（已定位）
`AutomationService.execute_commands()` 在 command 模式下把多条命令 `"\n".join(commands)` 拼成一个字符串，
作为单条命令发给 `send_command()`，Netmiko 只执行第一条，后续命令输出全部丢失。

### 修复内容
`backend/services/automation_service.py`：command 模式改为逐条调用 `orchestrator.execute_single()`，
遇到连接级错误（timeout/auth）提前终止，避免重复报错。

同时 `backend/api/playbooks.py` 的 `_exec_commands()` 改为每条命令输出前加 `# {cmd}\n` 标记，
方便前端按命令分割显示。

### 状态
代码已修复，需要重启后端服务后触发一次定时巡检验证。

---

## 已完成的其他工作（2026-05-12）

- 定时作业执行从串行改为并行（10 并发，`asyncio.Semaphore(10)`）
- 清理 `data/change_order_attachments/` 目录下 132 个测试占位文件（全部为空壳，已删除）
- 生成代码统计报告 `docs/code-stats-2026-05-12.md`（总计约 102,000 行）
