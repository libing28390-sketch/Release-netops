# Windows 一键图形化部署

适合纯 Windows 环境，不需要预装 Docker、Python、Node.js 或数据库。双击一个程序，图形向导自动搞定。

## 入口文件（仓库根目录）

| 文件 | 作用 |
|------|------|
| `NetOps.exe` | 图形部署向导 + 启动器，**推荐双击它** |
| `start.bat` | 等价入口，内部就是去拉起 `NetOps.exe`（很多人不敢点 bat，直接点 exe 即可） |
| `desktop/` | Windows 桌面端全部源码与资产（托盘程序、图标、打包配置等） |

## 步骤

1. 克隆 **`windows` 分支**（含桌面托盘工具和一键启动器）：
   ```powershell
   git clone -b windows https://github.com/libing28390-sketch/Release-netops.git netops-automation
   ```
   国内网络用 Gitee：
   ```powershell
   git clone -b windows https://gitee.com/leerbon/netops.git netops-automation
   ```
2. 进入目录，双击根目录下的 **`NetOps.exe`**。
3. 首次运行弹出图形向导：选择数据库（默认 PostgreSQL，没装会自动静默安装 PG17）→ 自动创建虚拟环境、装前后端依赖、编译前端 → 完成后自动起托盘并打开浏览器。
4. 浏览器访问 `http://127.0.0.1:5010`，默认账号 `admin / admin`。
5. 日常使用：再次双击 `NetOps.exe`，环境已就绪会跳过向导直接进托盘。

## 桌面端目录结构（`desktop/`）

| 文件 | 说明 |
|------|------|
| `launcher.py` | 部署向导主程序，打包进 `NetOps.exe` |
| `desktop_tray.py` | 系统托盘控制面板 |
| `create_shortcut.py` | 生成桌面快捷方式 |
| `netops.ico` / `netops_logo.png` / `公众号.jpg` | 图标与展示资产 |
| `desktop_settings.ini` | 托盘偏好设置（语言、主题、开机自启等） |

> 重新打包 exe：在仓库根目录执行 `pyinstaller NetOps.spec`（`NetOps.spec` 已指向 `desktop/launcher.py`），产物在 `dist/NetOps.exe`，复制到根目录覆盖即可。
