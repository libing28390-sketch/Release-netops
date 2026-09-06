@echo off
chcp 65001 >nul
title Nexora 启动助手

echo 正在启动 Nexora 部署与启动管理器...
if exist "%~dp0NetOps.exe" (
    start "" "%~dp0NetOps.exe"
) else if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop\launcher.py"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        start "" python "%~dp0desktop\launcher.py"
    ) else (
        echo [错误] 找不到 Nexora 启动器（NetOps.exe）且未检测到 Python 环境！
        echo 请先安装 Python，或在项目根目录下放置 Nexora 启动器。
        pause
    )
)
exit
