# Linux 巡检日志浅色样式

## 完成摘要

- Linux 服务器的 Playbook 巡检输出改为白底黑字，使用更易读的字号和行距；其他平台的终端颜色保持原样。
- Linux 输出的复制与 TXT 下载使用同一份浅色主题展示文本。
- 内置 `insp_linux_full` 汇总不再输出“综合健康评级”；保留错误/警告数量与具体指标。
- 对已保存的旧巡检日志，界面展示、复制和下载时会过滤掉旧的“综合健康评级”行。
- 没有添加或显示健康评分。

## 实际修改文件

- `src/pages/ExecutionSchedule/components/ExecutionDetail.tsx`
- `backend/database/seed.py`
- `docs/plans/plan_20261016_1522_01_Linux巡检日志浅色样式.md`
- `docs/walkthrough/walkthrough_20261016_1522_01_Linux巡检日志浅色样式.md`

## 关键实现

- `ExecutionDetail` 根据选中设备的平台/资产类型或任务名识别 Linux 输出，并将主题标志传给 Playbook 详情子视图。
- Linux 输出容器、阶段标题、折叠栏、命令标题及日志正文都使用白色/黑色样式；复制/下载工具切换为 light theme。
- Linux 输出展示前会去除历史记录中匹配“综合健康评级”的整行，原始错误、警告和指标内容不变。
- 内置 Linux 脚本不再计算或打印综合健康评级，错误和警告计数仍保留。

## 验证命令与结果

- `git diff --check`：通过。
- `.\.venv\Scripts\python.exe -m py_compile backend\database\seed.py`：通过。
- `npm run lint`：通过。
- `node .\node_modules\vite\bin\vite.js build --outDir "$env:TEMP\nexora-build-validation-linux-inspection-log-20261016"`：通过，4328 个模块完成构建。
- 浏览器中已看到白底黑字输出；后续刷新时本地 `192.168.96.1:5400` 拒绝连接，因此未能在最终代码状态下再次确认旧评分行过滤。未运行测试、未连接设备、未部署。

## 剩余风险与后续说明

- `backend/database/seed.py` 的内置脚本会在应用数据库初始化时同步；本轮未重启本地服务，所以脚本本体的修改尚未写入当前运行数据库。
- 浏览器服务当前不可达；应用恢复后刷新执行历史即可查看最终的浅色日志样式和无评级结果。
