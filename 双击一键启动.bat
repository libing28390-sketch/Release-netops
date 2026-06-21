@echo off
chcp 936 >nul
title NetOps 一键启动与自动初始化工具

echo ===================================================
echo           NetOps 自动化运维平台一键启动器
echo ===================================================
echo.

:: 1. 检查环境变量配置文件
echo [1/4] 检查环境变量配置文件...
if not exist ".env" (
    echo [提示] 未检测到 .env 配置文件，正在从模版自动生成...
    copy .env.example .env >nul
    echo [OK] 已生成默认 .env 配置文件。
) else (
    echo [OK] 配置文件已存在。
)
echo.

:: 2. 检查 Python 虚拟环境与依赖
echo [2/4] 检查 Python 虚拟环境及依赖...
if not exist ".venv" (
    echo [提示] 未检测到虚拟环境，正在为您创建并安装依赖（首次安装可能需要几分钟，请耐心等待）...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [错误] 创建虚拟环境失败！
        echo 请确保您的 Windows 系统已安装 Python 3.10+，且已将 python.exe 添加到系统 Path 环境变量中。
        echo.
        pause
        exit /b
    )
    echo 正在升级 pip 并安装后端依赖包...
    .venv\Scripts\python -m pip install --upgrade pip >nul 2>&1
    .venv\Scripts\pip install -r backend/requirements.txt
    .venv\Scripts\pip install pystray pillow
    echo [OK] Python 虚拟环境及依赖安装完成。
) else (
    echo [OK] Python 虚拟环境已就绪。
)
echo.

:: 3. 检查前端编译资源
echo [3/4] 检查前端编译资源...
if not exist "dist" (
    echo [提示] 未检测到前端静态编译目录，正在自动为您构建...
    echo 正在安装前端依赖包（由于首次安装，可能需要 1-2 分钟）...
    call npm install
    if errorlevel 1 (
        echo.
        echo [错误] 安装前端依赖包失败！
        echo 请确保您的 Windows 系统已安装 Node.js 和 npm，且已添加到 Path 环境变量中。
        echo.
        pause
        exit /b
    )
    echo 正在执行前端打包编译...
    call npm run build
    if exist "dist" (
        echo [OK] 前端静态资源编译打包成功。
    ) else (
        echo [错误] 前端编译失败，请在控制台手动运行 npm run build 查看报错。
        pause
        exit /b
    )
) else (
    echo [OK] 前端编译目录已存在。
)
echo.

:: 4. 检查桌面快捷方式与图标
echo [4/4] 检查桌面快捷方式与图标...
if not exist "netops.ico" (
    echo [提示] 正在生成图标文件并创建桌面快捷方式...
    .venv\Scripts\python create_shortcut.py
) else (
    rem 强制运行一次快捷方式生成以确保桌面上有完美命名的快捷方式
    .venv\Scripts\python create_shortcut.py >nul 2>&1
    echo [OK] 图标与桌面快捷方式配置完成。
)
echo.

echo ===================================================
echo [OK] 初始化全部完成！正在启动系统托盘服务...
echo ===================================================
echo.

:: 后台无窗口启动托盘程序
start "" ".venv\Scripts\pythonw.exe" "desktop_tray.py"

exit /b
