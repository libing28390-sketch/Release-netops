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

:: 1.5 检查是否需要并安装 PostgreSQL 数据库
findstr /i "postgresql://" .env >nul 2>&1
if %errorlevel% equ 0 (
    set NEED_PG=1
) else (
    findstr /i "postgres://" .env >nul 2>&1
    if %errorlevel% equ 0 (
        set NEED_PG=1
    ) else (
        set NEED_PG=0
    )
)

if "%NEED_PG%"=="1" (
    powershell -Command "$t = New-Object System.Net.Sockets.TcpClient; $t.Connect('127.0.0.1', 5432); $t.Close()" >nul 2>&1
    if %errorlevel% neq 0 (
        echo [提示] 检测到配置了 PostgreSQL，但本地 5432 端口未开启！
        set /p install_pg="是否现在自动下载并安装 PostgreSQL 16 (Y/N)？ "
        if /i "%install_pg%"=="Y" (
            echo 正在下载 PostgreSQL 16 安装包，请稍候...
            powershell -Command "Invoke-WebRequest -Uri 'https://get.enterprisedb.com/postgresql/postgresql-16.3-1-windows-x64.exe' -OutFile 'postgresql-installer.exe'"
            if exist "postgresql-installer.exe" (
                echo 正在静默安装 PostgreSQL (这可能需要几分钟，将自动请求管理员权限)...
                echo 请在随后弹出的用户账户控制(UAC)窗口中允许运行。
                powershell -Command "Start-Process 'postgresql-installer.exe' -ArgumentList '--mode unattended --unattendedmodeui none --superpassword netops --serverport 5432' -Verb RunAs -Wait"
                del postgresql-installer.exe
                echo [OK] PostgreSQL 安装完成，服务已启动！
            ) else (
                echo [错误] 下载 PostgreSQL 安装包失败，请检查网络！
                pause
                exit /b
            )
        ) else (
            echo [警告] 跳过 PostgreSQL 安装，如果数据库未在外部启动，系统可能无法正常工作。
            pause
        )
    )
)

:: 2. 检查 Python 运行环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 未检测到系统 Python 环境！
    set /p install_py="是否现在自动下载并安装 Python 3.11 (Y/N)？ "
    if /i "%install_py%"=="Y" (
        echo 正在下载 Python 3.11 安装包，请稍候...
        powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile 'python-installer.exe'"
        if exist "python-installer.exe" (
            echo 正在静默安装 Python (安装至当前用户，自动添加环境变量)...
            python-installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_doc=0
            del python-installer.exe
            echo [OK] Python 安装完成！正在刷新环境变量...
            for /f "tokens=*" %%i in ('powershell -Command "[System.Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'Machine')"') do set PATH=%%i
        ) else (
            echo [错误] 下载 Python 安装包失败，请检查网络！
            pause
            exit /b
        )
    ) else (
        echo [错误] 缺少 Python 环境，无法继续。
        pause
        exit /b
    )
)

:: 3. 检查/创建 Python 虚拟环境 (.venv)
if not exist ".venv" (
    echo [提示] 未检测到 .venv 虚拟环境，正在创建...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败，请确保 python 可正常运行。
        pause
        exit /b
    )
    echo [提示] 正在安装后台 Python 依赖，请稍候...
    .venv\Scripts\pip install -r backend/requirements.txt
    .venv\Scripts\pip install pystray pillow
)

:: 4. 检查前端静态编译资源 dist
if not exist "dist" (
    echo [警告] 未检测到前端静态编译目录 "dist" ！
    echo 后端将无法托管 Web 界面。
    echo.
    set /p build_choice="是否现在自动执行前端编译 (Y/N)？ "
    if /i "%build_choice%"=="Y" (
        npm --version >nul 2>&1
        if %errorlevel% neq 0 (
            echo [提示] 未检测到系统 Node.js/npm 环境！
            set /p install_node="是否自动下载便携版 Node.js (免安装) 进行前端编译 (Y/N)？ "
            if /i "%install_node%"=="Y" (
                echo 正在下载便携版 Node.js (v20)，请稍候...
                if not exist "tools" mkdir tools
                powershell -Command "Invoke-WebRequest -Uri 'https://nodejs.org/dist/v20.12.2/node-v20.12.2-win-x64.zip' -OutFile 'node.zip'"
                if exist "node.zip" (
                    echo 正在解压 Node.js...
                    powershell -Command "Expand-Archive -Path 'node.zip' -DestinationPath 'tools' -Force"
                    del node.zip
                    if exist "tools\node" rmdir /s /q "tools\node"
                    powershell -Command "Get-ChildItem tools | Where-Object { $_.Name -like 'node-v*' } | Rename-Item -NewName 'node'"
                    echo [OK] Node.js 便携版准备就绪！
                ) else (
                    echo [错误] 下载 Node.js 失败，请检查网络！
                    pause
                    exit /b
                )
            ) else (
                echo [提示] 跳过 Node.js 下载，编译终止。
                goto after_build
            )
        )
        
        echo 正在运行 npm install 与 npm run build，这可能需要几分钟，请稍候...
        if exist "tools\node\npm.cmd" (
            call tools\node\npm.cmd install
            call tools\node\npm.cmd run build
        ) else (
            call npm install
            call npm run build
        )
        
        if exist "dist" (
            echo [OK] 前端编译成功！
        ) else (
            echo [错误] 前端编译失败，请检查编译输出。
            pause
            exit /b
        )
    )
)
:after_build

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
echo [提示] 正在启动系统，等待服务就绪后自动打开浏览器...
start /b python scripts\open_browser.py http://127.0.0.1:5010 127.0.0.1 5010
python -m uvicorn backend.main:app --host 0.0.0.0 --port 5010
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
