# Windows 客户端 Codex 风格重构实施记录

- **编号**：`20260713_1505_01`
- **实施时间**：2026-07-13 15:05–16:16（Asia/Shanghai）
- **对应计划**：`docs/plans/plan_20260713_1505_01_Windows客户端Codex风格重构.md`
- **实施范围**：Windows NetOps Agent Manager 主窗口、启动向导、主题、公共反馈、高 DPI 适配与发布产物
- **实施状态**：代码与 EXE 已完成，待 Windows 11/无开发环境机器做外部终验

## 实施结果

Windows 客户端已从传统高对比管理面板重构为更接近 Codex 的中性、紧凑、低噪音桌面工作台。主窗口五个页面、启动配置向导、业务弹窗和全局反馈已纳入同一设计体系。服务启停、日志读取、设置保存、托盘最小化和数据库清理安全链路均已通过自动化回归。

## 主要改动

### 设计系统

- 新增 `desktop/ui/tokens.py`，集中管理深色/明亮模式的背景、表面、边框、文字、状态和焦点令牌。
- 新增 `desktop/ui/theme.py`，用单一主题生成器统一导航、卡片、按钮、输入、日志、滚动条和状态样式。
- 新增 `desktop/ui/launcher_theme.py`，启动向导改用同源中性暗色视觉。
- 删除主窗口重复的旧 `DARK_STYLE`/`LIGHT_STYLE` 和大量静态内联样式，实时状态改用 Qt dynamic property。

### 窗口与导航

- 侧栏展开宽度收紧为 `188px`，窗口低于 `1040px` 时自动折叠为 `64px`。
- 导航图标改为统一线性自绘图标，并补齐 Tooltip、accessibleName 和键盘焦点。
- 侧栏底部新增平台连接状态与版本信息。
- 保留 Windows 原生标题栏并同步深浅颜色，避免自定义无边框标题栏破坏 Snap Layout、DPI、窗口拖拽与辅助功能。

### 页面与交互

- 仪表盘统一状态卡层级，新增近期事件区域。
- 服务管理页收口按钮和运行信息层级，去除英文模式中的表情符号干扰。
- 日志页新增可见行数、文件大小和修改时间状态。
- 设置页改为单列滚动分组，系统信息可折叠，并增加“已保存”反馈。
- 处理器信息行改为可横向伸展、按换行内容自适应高度，避免长 CPU 型号被行高裁切。
- 关于页统一品牌、版本、链接和二维码区域的文字与容器层级。
- 明亮/深色、中文/英文、默认/最小窗口已完成视觉矩阵检查。

### 全局反馈与安全

- 新增 `desktop/ui/feedback.py`，统一信息、警告、错误、确认弹窗和 Toast。
- 危险确认的默认按钮固定为“取消”，数据库清理必须精确输入目标数据库名才能继续。
- 数据库清理弹窗显示 `.env` 配置来源、实际连接参数和备份目录。
- 数据库重置前在 GUI 线程停止后端，避免工作线程操作 UI。
- 服务启停、连通测试、诊断、复制和外部链接均提供统一成功/失败反馈。

### 启动向导

- 取消固定窗口，改为最小 `700×520`、默认 `760×560` 的可缩放窗口。
- 数据库字段改为中文单语言标签，密码字段默认隐藏明文。
- 数据库端口限定为 `1–65535` 的整数。
- 写入 `DATABASE_URL` 时对用户名、密码和数据库名进行 URL 编码，避免 `@`、`/`、空格等字符破坏连接串。

### 版本更新说明

- Windows 客户端版本统一提升为 `v1.0.2`，构建编号更新为 `20260713.1721`。
- 部署后首次启动显示一次“本次更新”弹窗，内容覆盖界面重构、启动修复、数据库安全、常用操作和多厂商命令联动。
- 用户确认后写入 `last_seen_release_notes_version`，同一版本不重复弹出；切换到下一版本后自动再次展示。
- 更新说明支持中文和英文，并复用统一主题弹窗，明亮/深色模式保持一致。

## 修改文件

- `desktop/desktop_tray.py`
- `desktop/launcher.py`
- `desktop/__init__.py`
- `desktop/release_notes.py`
- `desktop/ui/__init__.py`
- `desktop/ui/tokens.py`
- `desktop/ui/theme.py`
- `desktop/ui/launcher_theme.py`
- `desktop/ui/feedback.py`
- `desktop/tests/__init__.py`
- `desktop/tests/test_desktop_ui.py`
- `NetOps.exe`

## 验证结果

- `pytest desktop/tests/test_desktop_ui.py -q`：`15 passed`。
- `pytest backend/tests -q`：`375 passed, 1 warning`，警告为 Starlette/httpx 既有弃用提示。
- `npm run lint`：通过。
- `npm run build`：通过，仅有既有的大分块体积提示。
- `python -m compileall -q desktop`：通过。
- `git diff --check`：通过，仅有 Git 对 Windows 工作区的 LF/CRLF 转换提示。
- DPI 冒烟：`100%`、`125%`、`150%`、`175%` 全部通过，`920×640` 下侧栏正确折叠。
- 视觉矩阵：中文明亮仪表盘、中文深色设置、中文明亮紧凑设置、英文深色服务、英文明亮关于、深色启动向导通过。
- `python -m PyInstaller --noconfirm --clean NetOps.spec`：通过。
- `dist/NetOps.exe --smoke-test`：打包后独立启动、创建 Qt 窗口并自动退出，日志写出 `SMOKE_TEST_OK`。
- 根目录与 `dist` 产物 SHA-256 一致。

## 发布产物

- **路径**：`NetOps.exe`
- **大小**：`45,909,235 bytes`（约 `43.78 MB`）
- **SHA-256**：`634486CA2223794E37B1FC3311D8AAE14F6909AF432E8E1A86FE4B126A145D7E`

## 尚待外部终验

- 在 Windows 11 实机验证 Snap Layout、标题栏颜色和多显示器缩放。
- 在未安装 Python/Node.js 的机器验证启动、托盘、后台服务和 `.env` 读取。
- 在真实旧版本覆盖升级场景中确认 `v1.0.2` 更新说明首次显示且后续不重复。

## 说明

- 本轮同时修复资产厂商与平台联动，避免 Huawei/H3C 资产残留 `cisco_ios` 并错误选择 Cisco 命令；未修改 PostgreSQL 表结构。
- 若旧托盘进程仍在运行，需先从托盘完全退出，再启动新版 `NetOps.exe`，否则单实例机制会唤醒旧进程。
- 本次 Git 提交记录见 `docs/fixes/fix_20260713_1730_01_Windows客户端与多厂商命令联动.md`。
