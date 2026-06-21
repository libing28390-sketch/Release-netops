@echo off
chcp 65001 >nul
title NetOps 一键启动助手

echo ===================================================
echo           NetOps 自动化运维平台一键启动助手
echo ===================================================
echo.

:: 1. 检查环境变量配置文件 .env
if not exist ".env" (
    echo [提示] 未检测到 .env 配置文件，正在从模板生成...
    copy .env.example .env >nul
    echo [OK] 已生成默认 .env 文件，采用 SQLite 默认配置。
)

:: 2. 检查 Python 虚拟环境
if not exist ".venv" (
    echo [错误] 未检测到 .venv 文件夹！
    echo 请先在终端执行以下命令创建虚拟环境并安装依赖：
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install -r backend/requirements.txt
    echo.
    pause
    exit /b
)

:: 3. 检查前端静态编译资源 dist
if not exist "dist" (
    echo [警告] 未检测到前端静态编译目录 "dist" ！
    echo 后端将无法托管 Web 界面。
    echo.
    set /p build_choice="是否现在自动执行前端编译 (Y/N)？ "
    if /i "%build_choice%"=="Y" (
        echo 正在运行 npm install 与 npm run build，请稍候...
        call npm install
        call npm run build
        if exist "dist" (
            echo [OK] 前端编译成功！
        ) else (
            echo [错误] 前端编译失败，请手动运行 npm run build 排查问题。
            pause
            exit /b
        )
    ) else (
        echo [提示] 您选择了跳过。如果网页无法访问，请记得手动执行 npm run build。
    )
)

:menu
cls
echo ===================================================
echo           NetOps 自动化运维平台一键启动助手
echo ===================================================
echo.
echo   请选择操作：
echo   [1] 启动 NetOps (在前台控制台运行)
echo   [2] 创建桌面快捷方式 (后台无窗口运行)
echo   [3] 退出
echo.
echo ===================================================
set /p choice="请输入选项号码 [1, 2, 3]: "

if "%choice%"=="1" goto launch_foreground
if "%choice%"=="2" goto create_shortcut
if "%choice%"=="3" goto end
echo [提示] 输入错误，请重新选择！
pause
goto menu

:launch_foreground
echo.
echo [提示] 正在激活 Python 虚拟环境...
call .venv\Scripts\activate.bat
echo [提示] 正在启动系统，并在浏览器中打开 http://127.0.0.1:5010...
start "" "http://127.0.0.1:5010"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 5010
pause
goto menu

:create_shortcut
echo.
echo [提示] 正在检测/安装桌面客户端所需的依赖 (pystray, pillow)...
.venv\Scripts\pip install pystray pillow >nul 2>&1
echo [提示] 正在运行快捷方式生成器...
.venv\Scripts\python create_shortcut.py
echo.
pause
goto menu

:end
exit /b
