# -*- coding: utf-8 -*-
"""
desktop_tray.py - Enterprise PySide6 Agent Control Panel & System Tray utility.
Implements a 900x620 Left-Right layout, Fluent Design styles, automated background status polling,
one-click diagnostic suite generating zip reports, live log filtering, and Windows boot registry autostart.
"""

import sys
import os
import time
import socket
import threading
import webbrowser
import subprocess
import atexit
import ctypes
import platform
import shutil
import zipfile
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_ROOT, "desktop_tray.log")

# Stream redirector to log stdout/stderr to file
class LogFileWriter:
    def __init__(self, filename, prefix):
        self.filename = filename
        self.prefix = prefix
        self.buffer = ""

    def write(self, data):
        self.buffer += data
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                try:
                    with open(self.filename, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{self.prefix}] {line.rstrip()}\n")
                except Exception:
                    pass
        return len(data)

    def flush(self):
        if self.buffer.strip():
            try:
                with open(self.filename, "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{self.prefix}] {self.buffer.rstrip()}\n")
            except Exception:
                pass
            self.buffer = ""

    def isatty(self):
        return False

sys.stdout = LogFileWriter(LOG_FILE, "STDOUT")
sys.stderr = LogFileWriter(LOG_FILE, "STDERR")

import logging
logger = logging.getLogger("desktop_tray")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Configure High DPI scaling environment
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

# Try importing PySide6
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QLabel, QPushButton, QComboBox, QFrame, QGraphicsDropShadowEffect, 
        QSystemTrayIcon, QMenu, QCheckBox, QStackedWidget, QLineEdit, 
        QPlainTextEdit, QFileDialog, QMessageBox, QGridLayout, QScrollArea
    )
    from PySide6.QtCore import Qt, QSize, Signal, Slot, QTimer, QSettings, QPoint
    from PySide6.QtGui import QIcon, QFont, QColor, QAction, QCursor, QPainter, QBrush, QPen, QPixmap, QPolygon
except ImportError as e:
    error_msg = f"Failed to import PySide6: {e}\n\nPlease run 'NetOps.exe' to verify and repair the installation environment."
    print(error_msg)
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"程序启动失败：由于移到新电脑或环境损坏，缺少运行所需的依赖项。\n\n具体报错：{e}\n\n请双击运行根目录下的 'NetOps.exe' 自动修复运行环境。",
            "NetOps 启动错误",
            0x10 | 0x0
        )
    except Exception:
        pass
    sys.exit(1)

APP_URL = "http://127.0.0.1:5010"
backend_process = None
process_lock = threading.Lock()

# IMMERSIVE DARK MODE FOR WINDOWS 10/11
def set_dark_title_bar(window_handle, enabled):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window_handle)
        value = ctypes.c_int(1 if enabled else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception as e:
        logger.error("Failed to set dark title bar: %s", e)

# Helper function to generate clean colored dot icons in memory
def create_status_icon(color_name):
    # Load netops.ico if it exists, otherwise fallback to empty transparent pixmap
    ico_path = os.path.join(PROJECT_ROOT, "netops.ico")
    if os.path.exists(ico_path):
        pixmap = QIcon(ico_path).pixmap(32, 32)
    else:
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # Draw status dot in the bottom right corner
    if color_name == "green":
        # Green dot
        painter.setBrush(QBrush(QColor("#10B981")))
    elif color_name == "red":
        # Red dot
        painter.setBrush(QBrush(QColor("#EF4444")))
    elif color_name == "yellow":
        # Yellow dot for warning/error
        painter.setBrush(QBrush(QColor("#F59E0B")))
    elif color_name == "blue":
        # Blue dot for starting
        painter.setBrush(QBrush(QColor("#3B82F6")))
    else:
        # Grey dot for unknown
        painter.setBrush(QBrush(QColor("#64748B")))
        
    # Draw status dot at (19, 19) with size 11x11, and a dark outline for high visibility
    painter.setPen(QPen(QColor("#0B0F19"), 1.5))
    painter.drawEllipse(19, 19, 11, 11)
    
    painter.end()
    return QIcon(pixmap)

# Translation resources
TRANSLATIONS = {
    "zh": {
        "title": "NetOps Agent",
        "subtitle": "企业版 Enterprise",
        "nav_dashboard": " 📊  仪表盘 (Dashboard)",
        "nav_service": " ⚙️  服务管理 (Service)",
        "nav_logs": " 📝  实时日志 (Logs)",
        "nav_settings": " 🛠️  偏好设置 (Settings)",
        "nav_about": " ℹ️  关于我们 (About)",
        
        "agent_title": "NetOps Agent Enterprise",
        "agent_ver": "版本: v1.0.1",
        "agent_license": "许可: 商业授权版",
        
        "status_card_title": "后台服务状态 (Service Status)",
        "status_running": "🟢 运行中 (RUNNING)",
        "status_stopped": "🔴 已停止 (STOPPED)",
        "status_starting": "🟡 正在启动 (STARTING)",
        "status_unknown": "⚪ 未知 (UNKNOWN)",
        "health_healthy": "正常 (Healthy)",
        "health_unhealthy": "异常 (Unhealthy)",
        
        "conn_card_title": "平台连接状态 (Platform Connection)",
        "conn_connected": "🟢 已连接 (Connected)",
        "conn_disconnected": "🔴 已断开 (Disconnected)",
        "conn_controller": "控制器地址:",
        "conn_sync": "上次同步:",
        
        "diag_card_title": "一键诊断 (Run Diagnostics)",
        "diag_desc": "对本地 Agent 的运行状态、控制器连接性、DNS、NTP 及磁盘空间进行完整性检测。",
        "diag_btn": "运行诊断",
        "diag_running": "正在诊断...",
        "diag_done": "诊断完成！报告保存于 %s",
        "diag_failed": "诊断失败: %s",
        
        "control_card_title": "服务生命周期控制 (Service Controls)",
        "btn_start": "启动服务 (Start)",
        "btn_stop": "停止服务 (Stop)",
        "btn_restart": "重启服务 (Restart)",
        
        "meta_card_title": "运行环境变量 (Service Metadata)",
        "meta_addr": "监听地址",
        "meta_port": "服务端口",
        "meta_dir": "工作目录",
        "meta_cfg": "配置文件",
        "meta_log": "日志文件",
        
        "logs_card_title": "实时日志流监控 (Live Logs)",
        "log_select_label": "日志源:",
        "log_search_placeholder": "输入关键词进行过滤...",
        "chk_pause_scroll": "暂停滚动",
        "btn_clear": "清空视图",
        "btn_export": "导出日志",
        
        "settings_card_title": "基础参数配置 (General Settings)",
        "chk_boot_start": "开机自动运行 Agent 管理器",
        "chk_minimize_close": "点击关闭按钮时最小化到系统托盘",
        "chk_auto_update": "自动检查更新 (Auto Updates)",
        "lbl_lang": "语言 (Language):",
        "lbl_theme": "界面主题 (Theme):",
        "lbl_ctrl_ip": "控制器 IP (Controller IP):",
        
        "sys_card_title": "本机系统硬件信息 (System Specifications)",
        "sys_hostname": "主机名称 (Hostname)",
        "sys_os": "操作系统 (OS)",
        "sys_cpu": "处理器 (CPU)",
        "sys_mem": "内存容量 (RAM)",
        "sys_ip": "网络地址 (IP Address)",
        
        "about_name": "NetOps 智能自动化网络运维平台",
        "about_desc": "NetOps Agent Enterprise 是一款轻量级、企业级的网络设备监测与自动化管理客户端，支持后台自愈和多端同步调度。",
        "about_build": "构建编号: 20260622.1082",
        "about_site": "官方网站: ",
        "about_support": "技术支持: ",
        
        "tray_show": "显示控制面板 (Open Panel)",
        "tray_web": "打开网页系统 (Open Web)",
        "tray_restart": "重启服务 (Restart Service)",
        "tray_stop": "停止服务 (Stop Service)",
        "tray_logs": "查看运行日志 (View Logs)",
        "tray_settings": "偏好设置 (Settings)",
        "tray_exit": "完全退出 (Exit)",
        
        "notify_minimized": "NetOps 控制面板已最小化至系统托盘。",
        "notify_started": "NetOps 后端服务启动成功。",
        "notify_stopped": "NetOps 后端服务已停止。",
        "notify_title": "NetOps 运维助手"
    },
    "en": {
        "title": "NetOps Agent",
        "subtitle": "Enterprise",
        "nav_dashboard": " 📊  Dashboard",
        "nav_service": " ⚙️  Service",
        "nav_logs": " 📝  Logs",
        "nav_settings": " 🛠️  Settings",
        "nav_about": " ℹ️  About",
        
        "agent_title": "NetOps Agent Enterprise",
        "agent_ver": "Version: v1.0.1",
        "agent_license": "License: Commercial Enterprise",
        
        "status_card_title": "Backend Service Status",
        "status_running": "🟢 RUNNING",
        "status_stopped": "🔴 STOPPED",
        "status_starting": "🟡 STARTING",
        "status_unknown": "⚪ UNKNOWN",
        "health_healthy": "Healthy",
        "health_unhealthy": "Unhealthy",
        
        "conn_card_title": "Platform Connection",
        "conn_connected": "🟢 Connected",
        "conn_disconnected": "🔴 Disconnected",
        "conn_controller": "Controller IP:",
        "conn_sync": "Last Sync:",
        
        "diag_card_title": "Run Diagnostics",
        "diag_desc": "Performs checks on local Agent process, controller connectivity, DNS, NTP, and local storage limits.",
        "diag_btn": "Run Diagnostics",
        "diag_running": "Running audit...",
        "diag_done": "Audit successful! Saved to %s",
        "diag_failed": "Diagnostics failed: %s",
        
        "control_card_title": "Service Controls",
        "btn_start": "Start Service",
        "btn_stop": "Stop Service",
        "btn_restart": "Restart Service",
        
        "meta_card_title": "Service Metadata",
        "meta_addr": "Listen Address",
        "meta_port": "Service Port",
        "meta_dir": "Working Directory",
        "meta_cfg": "Configuration File",
        "meta_log": "Logging Path",
        
        "logs_card_title": "Live Logs",
        "log_select_label": "Log Source:",
        "log_search_placeholder": "Type keyword to filter logs...",
        "chk_pause_scroll": "Pause Scroll",
        "btn_clear": "Clear View",
        "btn_export": "Export Logs",
        
        "settings_card_title": "General Settings",
        "chk_boot_start": "Start Agent Manager on Windows boot",
        "chk_minimize_close": "Minimize to system tray on window close",
        "chk_auto_update": "Auto-check updates",
        "lbl_lang": "Language:",
        "lbl_theme": "Theme:",
        "lbl_ctrl_ip": "Controller IP:",
        
        "sys_card_title": "System Specifications",
        "sys_hostname": "Hostname",
        "sys_os": "Operating System (OS)",
        "sys_cpu": "Processor (CPU)",
        "sys_mem": "Physical Memory (RAM)",
        "sys_ip": "Local IP Address",
        
        "about_name": "NetOps Intelligent Network Automation Platform",
        "about_desc": "NetOps Agent Enterprise is a lightweight, industrial-grade device monitoring and orchestration client, supporting background healing and central remote scheduling.",
        "about_build": "Build Number: 20260622.1082",
        "about_site": "Official Website: ",
        "about_support": "Technical Support: ",
        
        "tray_show": "Open Panel",
        "tray_web": "Open Web GUI",
        "tray_restart": "Restart Service",
        "tray_stop": "Stop Service",
        "tray_logs": "View Live Logs",
        "tray_settings": "Settings",
        "tray_exit": "Exit",
        
        "notify_minimized": "NetOps Control Panel minimized to system tray.",
        "notify_started": "NetOps backend server started.",
        "notify_stopped": "NetOps backend server stopped.",
        "notify_title": "NetOps Agent"
    }
}

# Fluent QSS Styling
DARK_STYLE = """
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei UI";
    color: #F3F4F6;
    font-size: 12px;
}
QMainWindow {
    background-color: #0B0F19;
}
/* Sidebar Container */
QWidget#sidebar_container {
    background-color: #0F172A;
    border-right: 1px solid #1E293B;
}
QLabel#lbl_sidebar_title {
    font-size: 15px;
    font-weight: bold;
    color: #FFFFFF;
}
QLabel#lbl_sidebar_ver {
    font-size: 11px;
    color: #64748B;
}
QPushButton.nav_btn {
    text-align: left;
    padding: 10px 16px;
    font-size: 12px;
    font-weight: bold;
    color: #94A3B8;
    background-color: transparent;
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0px;
}
QPushButton.nav_btn:hover {
    color: #F8FAFC;
    background-color: #1E293B;
}
QPushButton.nav_btn:checked {
    color: #FFFFFF;
    background-color: #0B0F19;
    border-left: 4px solid #3B82F6;
}
/* Right content areas */
QStackedWidget#content_pane {
    background-color: #0B0F19;
}
QFrame.card {
    background-color: #0F172A;
    border: 1px solid #1E293B;
    border-radius: 10px;
}
QLabel#lbl_card_title {
    font-size: 11px;
    font-weight: bold;
    color: #64748B;
    text-transform: uppercase;
}
QLabel#lbl_status_large {
    font-size: 24px;
    font-weight: bold;
}
QLabel#lbl_field_name {
    color: #64748B;
}
QLabel#lbl_field_val {
    color: #F3F4F6;
    font-weight: bold;
}
/* Buttons styles */
QPushButton#btn_primary {
    background-color: #2563EB;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: none;
}
QPushButton#btn_primary:hover {
    background-color: #1D4ED8;
}
QPushButton#btn_primary:pressed {
    background-color: #1E40AF;
}
QPushButton#btn_primary:disabled {
    background-color: #1E293B;
    color: #475569;
}

QPushButton#btn_danger {
    background-color: #EF4444;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: none;
}
QPushButton#btn_danger:hover {
    background-color: #DC2626;
}
QPushButton#btn_danger:pressed {
    background-color: #B91C1C;
}
QPushButton#btn_danger:disabled {
    background-color: #1E293B;
    color: #475569;
}

QPushButton#btn_secondary {
    background-color: #1E293B;
    color: #F3F4F6;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: 1px solid #334155;
}
QPushButton#btn_secondary:hover {
    background-color: #334155;
}
QPushButton#btn_secondary:pressed {
    background-color: #0F172A;
}

QPushButton#btn_copy {
    background-color: #1E293B;
    color: #94A3B8;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
}
QPushButton#btn_copy:hover {
    background-color: #334155;
    color: #FFFFFF;
}

/* Inputs and terminals */
QComboBox, QLineEdit {
    background-color: #0F172A;
    border: 1px solid #1E293B;
    border-radius: 5px;
    padding: 5px 10px;
    color: #F3F4F6;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 0px;
}
QComboBox QAbstractItemView {
    background-color: #0F172A;
    border: 1px solid #1E293B;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
}

QPlainTextEdit#log_viewer {
    background-color: #030712;
    border: 1px solid #1E293B;
    border-radius: 8px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    color: #10B981;
}

QCheckBox {
    color: #94A3B8;
}
QCheckBox:hover {
    color: #F3F4F6;
}
"""

LIGHT_STYLE = """
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei UI";
    color: #0F172A;
    font-size: 12px;
}
QMainWindow {
    background-color: #F3F4F6;
}
/* Sidebar Container */
QWidget#sidebar_container {
    background-color: #FFFFFF;
    border-right: 1px solid #E5E7EB;
}
QLabel#lbl_sidebar_title {
    font-size: 15px;
    font-weight: bold;
    color: #0F172A;
}
QLabel#lbl_sidebar_ver {
    font-size: 11px;
    color: #64748B;
}
QPushButton.nav_btn {
    text-align: left;
    padding: 10px 16px;
    font-size: 12px;
    font-weight: bold;
    color: #4B5563;
    background-color: transparent;
    border: none;
    border-left: 4px solid transparent;
    border-radius: 0px;
}
QPushButton.nav_btn:hover {
    color: #111827;
    background-color: #F3F4F6;
}
QPushButton.nav_btn:checked {
    color: #2563EB;
    background-color: #F3F4F6;
    border-left: 4px solid #2563EB;
}
/* Right content areas */
QStackedWidget#content_pane {
    background-color: #F3F4F6;
}
QFrame.card {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
}
QLabel#lbl_card_title {
    font-size: 11px;
    font-weight: bold;
    color: #64748B;
    text-transform: uppercase;
}
QLabel#lbl_status_large {
    font-size: 24px;
    font-weight: bold;
}
QLabel#lbl_field_name {
    color: #64748B;
}
QLabel#lbl_field_val {
    color: #0F172A;
    font-weight: bold;
}
/* Buttons styles */
QPushButton#btn_primary {
    background-color: #2563EB;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: none;
}
QPushButton#btn_primary:hover {
    background-color: #1D4ED8;
}
QPushButton#btn_primary:pressed {
    background-color: #1E40AF;
}
QPushButton#btn_primary:disabled {
    background-color: #E5E7EB;
    color: #94A3B8;
}

QPushButton#btn_danger {
    background-color: #EF4444;
    color: #FFFFFF;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: none;
}
QPushButton#btn_danger:hover {
    background-color: #DC2626;
}
QPushButton#btn_danger:pressed {
    background-color: #B91C1C;
}
QPushButton#btn_danger:disabled {
    background-color: #E5E7EB;
    color: #94A3B8;
}

QPushButton#btn_secondary {
    background-color: #FFFFFF;
    color: #0F172A;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: bold;
    border: 1px solid #CBD5E1;
}
QPushButton#btn_secondary:hover {
    background-color: #F1F5F9;
}
QPushButton#btn_secondary:pressed {
    background-color: #E2E8F0;
}

QPushButton#btn_copy {
    background-color: #F8FAFC;
    color: #64748B;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
}
QPushButton#btn_copy:hover {
    background-color: #E2E8F0;
    color: #0F172A;
}

/* Inputs and terminals */
QComboBox, QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 5px;
    padding: 5px 10px;
    color: #0F172A;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left-width: 0px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
}

QPlainTextEdit#log_viewer {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
    color: #0F172A;
}

QCheckBox {
    color: #64748B;
}
QCheckBox:hover {
    color: #0F172A;
}
"""

def get_python_executable():
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-9] + "python.exe"
    return exe

_instance_socket = None

def check_single_instance(gui_trigger_signal):
    global _instance_socket
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1.0)
        test_sock.connect(("127.0.0.1", 5019))
        test_sock.sendall("SHOW_GUI".encode("utf-8"))
        test_sock.close()
        return False
    except socket.error:
        pass

    try:
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _instance_socket.bind(("127.0.0.1", 5019))
        _instance_socket.listen(5)
        
        def listen_loop():
            while True:
                try:
                    conn, addr = _instance_socket.accept()
                    data = conn.recv(1024).decode("utf-8")
                    conn.close()
                    if data == "SHOW_GUI":
                        gui_trigger_signal.emit()
                except Exception:
                    break
        threading.Thread(target=listen_loop, daemon=True).start()
    except socket.error as e:
        logger.error("Failed to bind instance socket: %s", e)
        _instance_socket = None
    return True

def get_pid_occupying_port(port):
    if sys.platform != 'win32':
        return None
    try:
        r = subprocess.run(
            f"netstat -ano | findstr LISTENING | findstr :{port}",
            shell=True,
            capture_output=True,
            text=True,
            creationflags=0x08000000
        )
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                local_addr = parts[1]
                if local_addr.endswith(f":{port}"):
                    try:
                        return int(parts[-1])
                    except ValueError:
                        pass
    except Exception:
        pass
    return None

def set_autostart_registry(enabled):
    if sys.platform != 'win32':
        return
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "NetOpsAgent"
    
    if getattr(sys, 'frozen', False):
        app_path = f'"{sys.executable}"'
    else:
        launcher_path = os.path.join(PROJECT_ROOT, "launcher.py")
        venv_pythonw = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "pythonw.exe")
        if os.path.exists(venv_pythonw) and os.path.exists(launcher_path):
            app_path = f'"{venv_pythonw}" "{launcher_path}"'
        else:
            app_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, app_path)
            logger.info("Auto-start registry key created: %s", app_path)
        else:
            try:
                winreg.DeleteValue(key, app_name)
                logger.info("Auto-start registry key removed.")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        logger.error("Failed to update auto-start registry key: %s", e)

class NetOpsAgentUI(QMainWindow):
    show_window_signal = Signal()
    diagnostic_log_signal = Signal(str)
    diagnostics_finished_signal = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.lang = "zh"
        self.dark_mode = True
        self.start_time = None
        
        # Connection status fields
        self.backend_active = False
        self.backend_pid = None
        self.controller_connected = False
        self.last_sync_time = "-"
        
        # Load persistent configurations
        self.load_settings()
        
        # Connect single instance and diagnostics signals
        self.show_window_signal.connect(self.show_window)
        self.diagnostic_log_signal.connect(self.append_diagnose_log)
        self.diagnostics_finished_signal.connect(self.on_diagnostics_finished)
        
        # Main Window configuration
        self.setWindowTitle("NetOps Agent Enterprise Manager")
        self.setFixedSize(900, 620)
        
        # Setup modern shadows
        self.shadow_status = QGraphicsDropShadowEffect(self)
        self.shadow_status.setBlurRadius(12)
        self.shadow_status.setColor(QColor(0, 0, 0, 30))
        self.shadow_status.setOffset(0, 3)
        
        self.shadow_conn = QGraphicsDropShadowEffect(self)
        self.shadow_conn.setBlurRadius(12)
        self.shadow_conn.setColor(QColor(0, 0, 0, 30))
        self.shadow_conn.setOffset(0, 3)
        
        self.shadow_diag = QGraphicsDropShadowEffect(self)
        self.shadow_diag.setBlurRadius(12)
        self.shadow_diag.setColor(QColor(0, 0, 0, 30))
        self.shadow_diag.setOffset(0, 3)
        
        self.setup_ui()
        self.apply_theme()
        
        # Start background polling thread
        self.poller_running = True
        self.status_thread = threading.Thread(target=self._status_polling_loop, daemon=True)
        self.status_thread.start()
        
        # Start logs polling timer (runs when logs page is visible)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.poll_logs)
        self.log_timer.start(1000)
        self.last_log_size = 0
        
        # Timer to poll backend status updates
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.update_runtime_state)
        self.poll_timer.start(1000)
        
        # Auto-launch backend on startup if configured
        if self.auto_start_service:
            QTimer.singleShot(500, self.start_backend_server)

    def load_settings(self):
        settings_path = os.path.join(PROJECT_ROOT, "desktop_settings.ini")
        self.settings = QSettings(settings_path, QSettings.IniFormat)
        self.auto_start_service = self.settings.value("auto_start_service", False, type=bool)
        self.minimize_to_tray = self.settings.value("minimize_to_tray", True, type=bool)
        self.boot_start = self.settings.value("boot_start", False, type=bool)
        self.auto_updates = self.settings.value("auto_updates", True, type=bool)
        self.lang = self.settings.value("lang", "zh", type=str)
        self.dark_mode = self.settings.value("dark_mode", True, type=bool)
        self.controller_ip = self.settings.value("controller_ip", "10.1.1.10", type=str)

    def save_settings(self):
        self.auto_start_service = self.chk_auto_start.isChecked()
        self.minimize_to_tray = self.chk_minimize_close.isChecked()
        self.boot_start = self.chk_boot_start.isChecked()
        self.auto_updates = self.chk_auto_update.isChecked()
        self.lang = "zh" if self.combo_lang_settings.currentIndex() == 0 else "en"
        self.dark_mode = (self.combo_theme.currentIndex() == 0)
        self.controller_ip = self.txt_controller_ip.text().strip()
        
        self.settings.setValue("auto_start_service", self.auto_start_service)
        self.settings.setValue("minimize_to_tray", self.minimize_to_tray)
        self.settings.setValue("boot_start", self.boot_start)
        self.settings.setValue("auto_updates", self.auto_updates)
        self.settings.setValue("lang", self.lang)
        self.settings.setValue("dark_mode", self.dark_mode)
        self.settings.setValue("controller_ip", self.controller_ip)
        self.settings.sync()
        
        # Registry integration
        set_autostart_registry(self.boot_start)

    def setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        
        # Left-Right main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. Left Sidebar
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("sidebar_container")
        self.sidebar.setFixedWidth(220)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 24, 0, 20)
        sidebar_layout.setSpacing(8)
        
        # Sidebar branding
        brand_layout = QHBoxLayout()
        brand_layout.setContentsMargins(20, 0, 20, 10)
        
        self.brand_icon = QLabel("📡", self)
        self.brand_icon.setStyleSheet("font-size: 24px;")
        brand_text_vbox = QVBoxLayout()
        
        self.lbl_sidebar_title = QLabel("NetOps Agent", self)
        self.lbl_sidebar_title.setObjectName("lbl_sidebar_title")
        self.lbl_sidebar_ver = QLabel("Enterprise Edition", self)
        self.lbl_sidebar_ver.setObjectName("lbl_sidebar_ver")
        
        brand_text_vbox.addWidget(self.lbl_sidebar_title)
        brand_text_vbox.addWidget(self.lbl_sidebar_ver)
        brand_layout.addWidget(self.brand_icon)
        brand_layout.addLayout(brand_text_vbox)
        sidebar_layout.addLayout(brand_layout)
        
        # Sidebar Navigation buttons
        self.nav_group = []
        self.nav_items = [
            ("Dashboard", "nav_dashboard"),
            ("Service", "nav_service"),
            ("Logs", "nav_logs"),
            ("Settings", "nav_settings"),
            ("About", "nav_about")
        ]
        
        for name, key in self.nav_items:
            btn = QPushButton(name, self)
            btn.setObjectName("nav_btn_" + name.lower())
            btn.setProperty("class", "nav_btn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self.on_nav_clicked)
            sidebar_layout.addWidget(btn)
            self.nav_group.append(btn)
            
        self.nav_group[0].setChecked(True)
        sidebar_layout.addStretch()
        
        # 2. Right Content Pane
        self.content_pane = QStackedWidget(self)
        self.content_pane.setObjectName("content_pane")
        
        # Initialize stacked pages
        self.init_dashboard_page()
        self.init_service_page()
        self.init_logs_page()
        self.init_settings_page()
        self.init_about_page()
        
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_pane)
        
        # Set default active title
        self.update_translations()

    def on_nav_clicked(self):
        sender = self.sender()
        if sender == self.nav_group[0]:
            self.content_pane.setCurrentIndex(0)
        elif sender == self.nav_group[1]:
            self.content_pane.setCurrentIndex(1)
        elif sender == self.nav_group[2]:
            self.content_pane.setCurrentIndex(2)
        elif sender == self.nav_group[3]:
            self.content_pane.setCurrentIndex(3)
        elif sender == self.nav_group[4]:
            self.content_pane.setCurrentIndex(4)

    # PAGE 1: Dashboard
    def init_dashboard_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        
        # Title Greeting Banner
        greeting_layout = QVBoxLayout()
        self.lbl_greet_title = QLabel("NetOps Agent Enterprise", self)
        self.lbl_greet_title.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.lbl_greet_desc = QLabel("Version v1.0.1 | License: Enterprise Commercial", self)
        self.lbl_greet_desc.setStyleSheet("color: #64748B; font-size: 11px;")
        greeting_layout.addWidget(self.lbl_greet_title)
        greeting_layout.addWidget(self.lbl_greet_desc)
        layout.addLayout(greeting_layout)
        
        # Middle Cards Layout (Service Status & Platform Connection)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(16)
        
        # Card 1: Service Status
        self.card_status = QFrame(self)
        self.card_status.setProperty("class", "card")
        self.card_status.setGraphicsEffect(self.shadow_status)
        card_status_layout = QVBoxLayout(self.card_status)
        card_status_layout.setContentsMargins(18, 14, 18, 14)
        card_status_layout.setSpacing(8)
        
        self.lbl_card_status_title = QLabel("服务状态 (Service Status)", self)
        self.lbl_card_status_title.setObjectName("lbl_card_title")
        self.lbl_status_large = QLabel("STOPPED", self)
        self.lbl_status_large.setObjectName("lbl_status_large")
        self.lbl_status_large.setStyleSheet("color: #EF4444;")
        
        card_status_layout.addWidget(self.lbl_card_status_title)
        card_status_layout.addWidget(self.lbl_status_large)
        
        status_grid = QGridLayout()
        status_grid.setSpacing(6)
        
        self.lbl_dash_pid_name = QLabel("PID:", self)
        self.lbl_dash_pid_name.setObjectName("lbl_field_name")
        self.lbl_dash_pid_val = QLabel("-", self)
        self.lbl_dash_pid_val.setObjectName("lbl_field_val")
        
        self.lbl_dash_uptime_name = QLabel("Uptime:", self)
        self.lbl_dash_uptime_name.setObjectName("lbl_field_name")
        self.lbl_dash_uptime_val = QLabel("0s", self)
        self.lbl_dash_uptime_val.setObjectName("lbl_field_val")
        
        self.lbl_dash_port_name = QLabel("Port:", self)
        self.lbl_dash_port_name.setObjectName("lbl_field_name")
        self.lbl_dash_port_val = QLabel("5010", self)
        self.lbl_dash_port_val.setObjectName("lbl_field_val")
        
        self.lbl_dash_health_name = QLabel("Health:", self)
        self.lbl_dash_health_name.setObjectName("lbl_field_name")
        self.lbl_dash_health_val = QLabel("Unhealthy", self)
        self.lbl_dash_health_val.setObjectName("lbl_field_val")
        
        status_grid.addWidget(self.lbl_dash_pid_name, 0, 0)
        status_grid.addWidget(self.lbl_dash_pid_val, 0, 1)
        status_grid.addWidget(self.lbl_dash_uptime_name, 1, 0)
        status_grid.addWidget(self.lbl_dash_uptime_val, 1, 1)
        status_grid.addWidget(self.lbl_dash_port_name, 2, 0)
        status_grid.addWidget(self.lbl_dash_port_val, 2, 1)
        status_grid.addWidget(self.lbl_dash_health_name, 3, 0)
        status_grid.addWidget(self.lbl_dash_health_val, 3, 1)
        card_status_layout.addLayout(status_grid)
        cards_layout.addWidget(self.card_status)
        
        # Card 2: Platform Connection
        self.card_conn = QFrame(self)
        self.card_conn.setProperty("class", "card")
        self.card_conn.setGraphicsEffect(self.shadow_conn)
        card_conn_layout = QVBoxLayout(self.card_conn)
        card_conn_layout.setContentsMargins(18, 14, 18, 14)
        card_conn_layout.setSpacing(8)
        
        self.lbl_card_conn_title = QLabel("平台连接状态 (Platform Connection)", self)
        self.lbl_card_conn_title.setObjectName("lbl_card_title")
        self.lbl_conn_large = QLabel("DISCONNECTED", self)
        self.lbl_conn_large.setObjectName("lbl_status_large")
        self.lbl_conn_large.setStyleSheet("color: #64748B;")
        
        card_conn_layout.addWidget(self.lbl_card_conn_title)
        card_conn_layout.addWidget(self.lbl_conn_large)
        
        conn_grid = QGridLayout()
        conn_grid.setSpacing(6)
        
        self.lbl_dash_ctrl_name = QLabel("Controller:", self)
        self.lbl_dash_ctrl_name.setObjectName("lbl_field_name")
        self.lbl_dash_ctrl_val = QLabel("10.1.1.10", self)
        self.lbl_dash_ctrl_val.setObjectName("lbl_field_val")
        
        self.lbl_dash_sync_name = QLabel("Last Sync:", self)
        self.lbl_dash_sync_name.setObjectName("lbl_field_name")
        self.lbl_dash_sync_val = QLabel("-", self)
        self.lbl_dash_sync_val.setObjectName("lbl_field_val")
        
        conn_grid.addWidget(self.lbl_dash_ctrl_name, 0, 0)
        conn_grid.addWidget(self.lbl_dash_ctrl_val, 0, 1)
        conn_grid.addWidget(self.lbl_dash_sync_name, 1, 0)
        conn_grid.addWidget(self.lbl_dash_sync_val, 1, 1)
        conn_grid.setRowMinimumHeight(2, 40) # Spacing alignment
        card_conn_layout.addLayout(conn_grid)
        cards_layout.addWidget(self.card_conn)
        
        layout.addLayout(cards_layout)
        
        # Bottom: Diagnostics Card
        self.card_diag = QFrame(self)
        self.card_diag.setProperty("class", "card")
        self.card_diag.setGraphicsEffect(self.shadow_diag)
        card_diag_layout = QVBoxLayout(self.card_diag)
        card_diag_layout.setContentsMargins(18, 14, 18, 14)
        card_diag_layout.setSpacing(10)
        
        self.lbl_diag_title = QLabel("一键诊断 (Run Diagnostics)", self)
        self.lbl_diag_title.setObjectName("lbl_card_title")
        card_diag_layout.addWidget(self.lbl_diag_title)
        
        diag_desc_hbox = QHBoxLayout()
        self.lbl_diag_desc = QLabel("对本地 Agent 的运行状态、控制器连接性、DNS、NTP 及磁盘空间进行完整性检测。", self)
        self.lbl_diag_desc.setStyleSheet("color: #64748B; font-size: 11px;")
        self.btn_run_diagnose = QPushButton("运行诊断", self)
        self.btn_run_diagnose.setObjectName("btn_primary")
        self.btn_run_diagnose.setCursor(Qt.PointingHandCursor)
        self.btn_run_diagnose.clicked.connect(self.trigger_diagnostics)
        
        diag_desc_hbox.addWidget(self.lbl_diag_desc, 1)
        diag_desc_hbox.addWidget(self.btn_run_diagnose)
        card_diag_layout.addLayout(diag_desc_hbox)
        
        self.txt_diagnose_log = QPlainTextEdit(self)
        self.txt_diagnose_log.setObjectName("log_viewer")
        self.txt_diagnose_log.setReadOnly(True)
        self.txt_diagnose_log.setFixedHeight(120)
        card_diag_layout.addWidget(self.txt_diagnose_log)
        
        layout.addWidget(self.card_diag)
        self.content_pane.addWidget(page)

    # PAGE 2: Service controls & paths
    def init_service_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        
        # 1. Lifecycle Panel
        card_ctrl = QFrame(self)
        card_ctrl.setProperty("class", "card")
        ctrl_layout = QVBoxLayout(card_ctrl)
        ctrl_layout.setContentsMargins(20, 16, 20, 16)
        ctrl_layout.setSpacing(12)
        
        self.lbl_service_ctrl_title = QLabel("服务生命周期控制 (Service Controls)", self)
        self.lbl_service_ctrl_title.setObjectName("lbl_card_title")
        ctrl_layout.addWidget(self.lbl_service_ctrl_title)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_start = QPushButton("启动服务", self)
        self.btn_start.setObjectName("btn_primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_backend_server)
        
        self.btn_stop = QPushButton("停止服务", self)
        self.btn_stop.setObjectName("btn_danger")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.clicked.connect(self.stop_backend_server)
        
        self.btn_restart = QPushButton("重启服务", self)
        self.btn_restart.setObjectName("btn_secondary")
        self.btn_restart.setCursor(Qt.PointingHandCursor)
        self.btn_restart.clicked.connect(self.restart_backend_server)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_restart)
        btn_layout.addStretch()
        ctrl_layout.addLayout(btn_layout)
        layout.addWidget(card_ctrl)
        
        # 2. Metadata details
        card_meta = QFrame(self)
        card_meta.setProperty("class", "card")
        meta_layout = QVBoxLayout(card_meta)
        meta_layout.setContentsMargins(20, 16, 20, 16)
        meta_layout.setSpacing(12)
        
        self.lbl_service_meta_title = QLabel("运行环境变量 (Service Metadata)", self)
        self.lbl_service_meta_title.setObjectName("lbl_card_title")
        meta_layout.addWidget(self.lbl_service_meta_title)
        
        meta_grid = QGridLayout()
        meta_grid.setVerticalSpacing(10)
        meta_grid.setHorizontalSpacing(16)
        
        # Fields details
        self.meta_fields = [
            ("meta_addr", "127.0.0.1:5010"),
            ("meta_port", "5010"),
            ("meta_dir", PROJECT_ROOT),
            ("meta_cfg", os.path.join(PROJECT_ROOT, "desktop_settings.ini")),
            ("meta_log", os.path.join(PROJECT_ROOT, "backend_server.log"))
        ]
        
        self.meta_labels = {}
        for row, (key, value) in enumerate(self.meta_fields):
            lbl_name = QLabel(key, self)
            lbl_name.setObjectName("lbl_field_name")
            
            lbl_val = QLineEdit(value, self)
            lbl_val.setReadOnly(True)
            lbl_val.setStyleSheet("background-color: transparent; border: none; font-weight: bold; color: inherit; padding: 0px;")
            
            btn_copy = QPushButton("Copy", self)
            btn_copy.setObjectName("btn_copy")
            btn_copy.setCursor(Qt.PointingHandCursor)
            btn_copy.clicked.connect(lambda checked=False, v=value, b=btn_copy: self.copy_to_clipboard(v, b))
            
            meta_grid.addWidget(lbl_name, row, 0)
            meta_grid.addWidget(lbl_val, row, 1, 1, 3)
            meta_grid.addWidget(btn_copy, row, 4, Qt.AlignRight)
            self.meta_labels[key] = lbl_name
            
        meta_layout.addLayout(meta_grid)
        layout.addWidget(card_meta)
        layout.addStretch()
        
        self.content_pane.addWidget(page)

    def copy_to_clipboard(self, val, button):
        QApplication.clipboard().setText(val)
        orig_text = button.text()
        button.setText("Copied!")
        button.setEnabled(False)
        QTimer.singleShot(1500, lambda: [button.setText(orig_text), button.setEnabled(True)])

    # PAGE 3: Logs Streamer
    def init_logs_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        
        # Upper Filters
        filters_hbox = QHBoxLayout()
        filters_hbox.setSpacing(10)
        
        self.lbl_log_source = QLabel("日志源:", self)
        self.lbl_log_source.setObjectName("lbl_field_name")
        
        self.combo_log_source = QComboBox(self)
        self.combo_log_source.addItems(["FastAPI Server (backend_server.log)", "Tray Agent (desktop_tray.log)"])
        self.combo_log_source.currentIndexChanged.connect(self.on_log_source_changed)
        
        self.txt_log_search = QLineEdit(self)
        self.txt_log_search.setObjectName("txt_log_search")
        self.txt_log_search.textChanged.connect(self.trigger_log_filter)
        
        self.chk_pause_scroll = QCheckBox("暂停滚动", self)
        self.chk_pause_scroll.setObjectName("chk_pause_scroll")
        
        self.btn_clear_logs = QPushButton("清空视图", self)
        self.btn_clear_logs.setObjectName("btn_secondary")
        self.btn_clear_logs.setCursor(Qt.PointingHandCursor)
        self.btn_clear_logs.clicked.connect(self.clear_log_view)
        
        self.btn_export_logs = QPushButton("导出日志", self)
        self.btn_export_logs.setObjectName("btn_secondary")
        self.btn_export_logs.setCursor(Qt.PointingHandCursor)
        self.btn_export_logs.clicked.connect(self.export_logs_file)
        
        filters_hbox.addWidget(self.lbl_log_source)
        filters_hbox.addWidget(self.combo_log_source)
        filters_hbox.addWidget(self.txt_log_search, 1)
        filters_hbox.addWidget(self.chk_pause_scroll)
        filters_hbox.addWidget(self.btn_clear_logs)
        filters_hbox.addWidget(self.btn_export_logs)
        layout.addLayout(filters_hbox)
        
        # Real-time log monitor viewport
        self.txt_logs_terminal = QPlainTextEdit(self)
        self.txt_logs_terminal.setObjectName("log_viewer")
        self.txt_logs_terminal.setReadOnly(True)
        self.txt_logs_terminal.setMaximumBlockCount(2000)
        layout.addWidget(self.txt_logs_terminal)
        
        self.content_pane.addWidget(page)

    def get_selected_log_path(self):
        if self.combo_log_source.currentIndex() == 0:
            return os.path.join(PROJECT_ROOT, "backend_server.log")
        else:
            return os.path.join(PROJECT_ROOT, "desktop_tray.log")

    def on_log_source_changed(self):
        self.last_log_size = 0
        self.txt_logs_terminal.clear()
        self.poll_logs()

    def clear_log_view(self):
        self.txt_logs_terminal.clear()

    def trigger_log_filter(self):
        self.last_log_size = 0
        self.txt_logs_terminal.clear()
        self.poll_logs()

    def poll_logs(self):
        # Only poll if Logs page is visible
        if self.content_pane.currentIndex() != 2:
            return
        
        log_path = self.get_selected_log_path()
        if not os.path.exists(log_path):
            return
            
        try:
            current_size = os.path.getsize(log_path)
            if current_size < self.last_log_size:
                # File was truncated/cleared
                self.last_log_size = 0
                self.txt_logs_terminal.clear()
                
            if current_size > self.last_log_size:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    if self.last_log_size == 0:
                        # Load last 10000 bytes initially
                        seek_pos = max(0, current_size - 25000)
                        f.seek(seek_pos)
                        content = f.read()
                    else:
                        f.seek(self.last_log_size)
                        content = f.read()
                        
                self.last_log_size = current_size
                
                # Append content matching search terms
                keyword = self.txt_log_search.text().strip().lower()
                lines = content.splitlines()
                matching_lines = []
                for line in lines:
                    if not keyword or keyword in line.lower():
                        matching_lines.append(line)
                        
                if matching_lines:
                    # Save cursor position if scrolled up
                    scrollbar = self.txt_logs_terminal.verticalScrollBar()
                    at_bottom = scrollbar.value() == scrollbar.maximum()
                    
                    self.txt_logs_terminal.appendPlainText("\n".join(matching_lines))
                    
                    if at_bottom and not self.chk_pause_scroll.isChecked():
                        scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            logger.error("Failed to read log stream: %s", e)

    def export_logs_file(self):
        log_path = self.get_selected_log_path()
        if not os.path.exists(log_path):
            QMessageBox.warning(self, "Export logs", "Selected log file is empty or missing.")
            return
            
        dest_path, _ = QFileDialog.getSaveFileName(self, "Export Log File", "", "Log Files (*.log);;Text Files (*.txt)")
        if dest_path:
            try:
                shutil.copy(log_path, dest_path)
                QMessageBox.information(self, "Export logs", "Log file exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Export logs", f"Export failed: {e}")

    # PAGE 4: Settings & System info
    def init_settings_page(self):
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        
        # Left Column: General Preferences Card
        card_prefs = QFrame(self)
        card_prefs.setProperty("class", "card")
        prefs_layout = QVBoxLayout(card_prefs)
        prefs_layout.setContentsMargins(18, 16, 18, 16)
        prefs_layout.setSpacing(12)
        
        self.lbl_settings_card_title = QLabel("基础参数配置 (General Settings)", self)
        self.lbl_settings_card_title.setObjectName("lbl_card_title")
        prefs_layout.addWidget(self.lbl_settings_card_title)
        
        self.chk_boot_start = QCheckBox("开机自动运行 Agent 管理器", self)
        self.chk_boot_start.setChecked(self.boot_start)
        self.chk_boot_start.stateChanged.connect(self.save_settings)
        prefs_layout.addWidget(self.chk_boot_start)
        
        self.chk_minimize_close = QCheckBox("点击关闭按钮时最小化到系统托盘", self)
        self.chk_minimize_close.setChecked(self.minimize_to_tray)
        self.chk_minimize_close.stateChanged.connect(self.save_settings)
        prefs_layout.addWidget(self.chk_minimize_close)
        
        self.chk_auto_update = QCheckBox("自动检查更新 (Auto Updates)", self)
        self.chk_auto_update.setChecked(self.auto_updates)
        self.chk_auto_update.stateChanged.connect(self.save_settings)
        prefs_layout.addWidget(self.chk_auto_update)
        
        form_grid = QGridLayout()
        form_grid.setSpacing(10)
        
        self.lbl_lang_settings = QLabel("语言 (Language):", self)
        self.lbl_lang_settings.setObjectName("lbl_field_name")
        self.combo_lang_settings = QComboBox(self)
        self.combo_lang_settings.addItems(["中文 (Chinese)", "English"])
        self.combo_lang_settings.setCurrentIndex(0 if self.lang == "zh" else 1)
        self.combo_lang_settings.currentIndexChanged.connect(self.on_lang_settings_changed)
        
        self.lbl_theme_settings = QLabel("界面主题 (Theme):", self)
        self.lbl_theme_settings.setObjectName("lbl_field_name")
        self.combo_theme = QComboBox(self)
        self.combo_theme.addItems(["Dark Mode (暗色)", "Light Mode (明亮)"])
        self.combo_theme.setCurrentIndex(0 if self.dark_mode else 1)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_settings_changed)
        
        self.lbl_ctrl_ip_settings = QLabel("控制器 IP (Controller IP):", self)
        self.lbl_ctrl_ip_settings.setObjectName("lbl_field_name")
        self.txt_controller_ip = QLineEdit(self.controller_ip, self)
        self.txt_controller_ip.textChanged.connect(self.save_settings)
        
        form_grid.addWidget(self.lbl_lang_settings, 0, 0)
        form_grid.addWidget(self.combo_lang_settings, 0, 1)
        form_grid.addWidget(self.lbl_theme_settings, 1, 0)
        form_grid.addWidget(self.combo_theme, 1, 1)
        form_grid.addWidget(self.lbl_ctrl_ip_settings, 2, 0)
        form_grid.addWidget(self.txt_controller_ip, 2, 1)
        
        prefs_layout.addLayout(form_grid)
        prefs_layout.addStretch()
        layout.addWidget(card_prefs, 1)
        
        # Right Column: System Specs Card
        card_sys = QFrame(self)
        card_sys.setProperty("class", "card")
        sys_layout = QVBoxLayout(card_sys)
        sys_layout.setContentsMargins(18, 16, 18, 16)
        sys_layout.setSpacing(12)
        
        self.lbl_sys_card_title = QLabel("本机系统硬件信息 (System Specifications)", self)
        self.lbl_sys_card_title.setObjectName("lbl_card_title")
        sys_layout.addWidget(self.lbl_sys_card_title)
        
        sys_grid = QGridLayout()
        sys_grid.setSpacing(12)
        
        # Query local specs
        hostname = socket.gethostname()
        os_info = f"{platform.system()} {platform.release()}"
        cpu_info = platform.processor() or "AMD/Intel Processor"
        mem_info = self.get_total_memory()
        ip_info = self.get_local_ip_addresses()
        
        self.sys_specs = [
            ("sys_hostname", hostname),
            ("sys_os", os_info),
            ("sys_cpu", cpu_info),
            ("sys_mem", mem_info),
            ("sys_ip", ip_info)
        ]
        
        self.sys_labels = {}
        for row, (key, val) in enumerate(self.sys_specs):
            lbl_name = QLabel(key, self)
            lbl_name.setObjectName("lbl_field_name")
            
            lbl_val = QLabel(val, self)
            lbl_val.setObjectName("lbl_field_val")
            lbl_val.setWordWrap(True)
            
            sys_grid.addWidget(lbl_name, row, 0, Qt.AlignTop)
            sys_grid.addWidget(lbl_val, row, 1, Qt.AlignTop)
            self.sys_labels[key] = lbl_name
            
        sys_layout.addLayout(sys_grid)
        sys_layout.addStretch()
        layout.addWidget(card_sys, 1)
        
        self.content_pane.addWidget(page)

    def get_total_memory(self):
        if sys.platform != 'win32':
            return "Unknown Memory"
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return f"{stat.ullTotalPhys / (1024**3):.1f} GB"
        except Exception:
            return "Unknown"

    def get_local_ip_addresses(self):
        try:
            ips = []
            addrs = socket.getaddrinfo(socket.gethostname(), None)
            for item in addrs:
                ip = item[4][0]
                if ":" not in ip and not ip.startswith("127."): # Filter IPv4 only
                    if ip not in ips:
                        ips.append(ip)
            return ", ".join(ips) if ips else "127.0.0.1"
        except Exception:
            return "127.0.0.1"

    def on_lang_settings_changed(self, idx):
        self.lang = "zh" if idx == 0 else "en"
        self.update_translations()
        self.save_settings()

    def on_theme_settings_changed(self, idx):
        self.dark_mode = (idx == 0)
        self.apply_theme()
        self.save_settings()

    # PAGE 5: About us
    def init_about_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(20)
        
        card_about = QFrame(self)
        card_about.setProperty("class", "card")
        about_layout = QVBoxLayout(card_about)
        about_layout.setContentsMargins(30, 24, 30, 24)
        about_layout.setSpacing(14)
        
        self.lbl_about_logo = QLabel("📡", self)
        self.lbl_about_logo.setStyleSheet("font-size: 40px;")
        about_layout.addWidget(self.lbl_about_logo, 0, Qt.AlignCenter)
        
        self.lbl_about_name = QLabel("NetOps 智能自动化网络运维平台", self)
        self.lbl_about_name.setStyleSheet("font-size: 18px; font-weight: bold; color: #3B82F6;")
        about_layout.addWidget(self.lbl_about_name, 0, Qt.AlignCenter)
        
        self.lbl_about_desc = QLabel(self)
        self.lbl_about_desc.setStyleSheet("color: #64748B; font-size: 12px; line-height: 1.6;")
        self.lbl_about_desc.setWordWrap(True)
        self.lbl_about_desc.setAlignment(Qt.AlignCenter)
        about_layout.addWidget(self.lbl_about_desc)
        
        divider = QFrame(self)
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setStyleSheet("background-color: #1E293B;")
        about_layout.addWidget(divider)
        
        details_grid = QGridLayout()
        details_grid.setSpacing(10)
        
        self.lbl_about_ver_name = QLabel("Version:", self)
        self.lbl_about_ver_name.setObjectName("lbl_field_name")
        self.lbl_about_ver_val = QLabel("v1.0.1 Enterprise Edition", self)
        self.lbl_about_ver_val.setObjectName("lbl_field_val")
        
        self.lbl_about_build_name = QLabel("Build Number:", self)
        self.lbl_about_build_name.setObjectName("lbl_field_name")
        self.lbl_about_build_val = QLabel("20260622.1082", self)
        self.lbl_about_build_val.setObjectName("lbl_field_val")
        
        self.lbl_about_site_name = QLabel("Official Website:", self)
        self.lbl_about_site_name.setObjectName("lbl_field_name")
        self.lbl_about_site_val = QPushButton("https://netops.example.com", self)
        self.lbl_about_site_val.setCursor(Qt.PointingHandCursor)
        self.lbl_about_site_val.setStyleSheet("color: #3B82F6; border: none; background: transparent; text-align: left; font-weight: bold;")
        self.lbl_about_site_val.clicked.connect(lambda: webbrowser.open("https://netops.example.com"))
        
        self.lbl_about_support_name = QLabel("Technical Support:", self)
        self.lbl_about_support_name.setObjectName("lbl_field_name")
        self.lbl_about_support_val = QLabel("support@netops.example.com", self)
        self.lbl_about_support_val.setObjectName("lbl_field_val")
        
        details_grid.addWidget(self.lbl_about_ver_name, 0, 0)
        details_grid.addWidget(self.lbl_about_ver_val, 0, 1)
        details_grid.addWidget(self.lbl_about_build_name, 1, 0)
        details_grid.addWidget(self.lbl_about_build_val, 1, 1)
        details_grid.addWidget(self.lbl_about_site_name, 2, 0)
        details_grid.addWidget(self.lbl_about_site_val, 2, 1)
        details_grid.addWidget(self.lbl_about_support_name, 3, 0)
        details_grid.addWidget(self.lbl_about_support_val, 3, 1)
        
        about_layout.addLayout(details_grid)
        layout.addWidget(card_about)
        layout.addStretch()
        
        self.content_pane.addWidget(page)

    def closeEvent(self, event):
        if self.minimize_to_tray:
            event.ignore()
            self.hide()
            self.show_tray_notification(
                TRANSLATIONS[self.lang]["notify_minimized"],
                TRANSLATIONS[self.lang]["notify_title"]
            )
        else:
            self.poller_running = False
            self.stop_backend_server()
            if hasattr(self, 'tray_icon'):
                self.tray_icon.hide()
            event.accept()
            QApplication.quit()

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def apply_theme(self):
        if self.dark_mode:
            self.setStyleSheet(DARK_STYLE)
            set_dark_title_bar(self.winId(), True)
        else:
            self.setStyleSheet(LIGHT_STYLE)
            set_dark_title_bar(self.winId(), False)

    def update_translations(self):
        tr = TRANSLATIONS[self.lang]
        self.lbl_sidebar_title.setText(tr["title"])
        self.lbl_sidebar_ver.setText(tr["subtitle"])
        
        # Navigation
        self.nav_group[0].setText(tr["nav_dashboard"])
        self.nav_group[1].setText(tr["nav_service"])
        self.nav_group[2].setText(tr["nav_logs"])
        self.nav_group[3].setText(tr["nav_settings"])
        self.nav_group[4].setText(tr["nav_about"])
        
        # Page 1: Dashboard
        self.lbl_greet_title.setText(tr["agent_title"])
        self.lbl_greet_desc.setText(f"{tr['agent_ver']} | {tr['agent_license']}")
        self.lbl_card_status_title.setText(tr["status_card_title"])
        self.lbl_dash_pid_name.setText(tr["status_card_title"] if False else "PID:")
        self.lbl_dash_uptime_name.setText("Uptime:")
        self.lbl_dash_port_name.setText("Port:")
        self.lbl_dash_health_name.setText("Health:")
        
        self.lbl_card_conn_title.setText(tr["conn_card_title"])
        self.lbl_dash_ctrl_name.setText(tr["conn_controller"])
        self.lbl_dash_sync_name.setText(tr["conn_sync"])
        
        self.lbl_diag_title.setText(tr["diag_card_title"])
        self.lbl_diag_desc.setText(tr["diag_desc"])
        self.btn_run_diagnose.setText(tr["diag_btn"])
        
        # Page 2: Service controls
        self.lbl_service_ctrl_title.setText(tr["control_card_title"])
        self.btn_start.setText(tr["btn_start"])
        self.btn_stop.setText(tr["btn_stop"])
        self.btn_restart.setText(tr["btn_restart"])
        self.lbl_service_meta_title.setText(tr["meta_card_title"])
        
        self.meta_labels["meta_addr"].setText(tr["meta_addr"])
        self.meta_labels["meta_port"].setText(tr["meta_port"])
        self.meta_labels["meta_dir"].setText(tr["meta_dir"])
        self.meta_labels["meta_cfg"].setText(tr["meta_cfg"])
        self.meta_labels["meta_log"].setText(tr["meta_log"])
        
        # Page 3: Logs
        self.lbl_log_source.setText(tr["log_select_label"])
        self.txt_log_search.setPlaceholderText(tr["log_search_placeholder"])
        self.chk_pause_scroll.setText(tr["chk_pause_scroll"])
        self.btn_clear_logs.setText(tr["btn_clear"])
        self.btn_export_logs.setText(tr["btn_export"])
        
        # Page 4: Settings
        self.lbl_settings_card_title.setText(tr["settings_card_title"])
        self.chk_boot_start.setText(tr["chk_boot_start"])
        self.chk_minimize_close.setText(tr["chk_minimize_close"])
        self.chk_auto_update.setText(tr["chk_auto_update"])
        self.lbl_lang_settings.setText(tr["lbl_lang"])
        self.lbl_theme_settings.setText(tr["lbl_theme"])
        self.lbl_ctrl_ip_settings.setText(tr["lbl_ctrl_ip"])
        self.lbl_sys_card_title.setText(tr["sys_card_title"])
        
        self.sys_labels["sys_hostname"].setText(tr["sys_hostname"])
        self.sys_labels["sys_os"].setText(tr["sys_os"])
        self.sys_labels["sys_cpu"].setText(tr["sys_cpu"])
        self.sys_labels["sys_mem"].setText(tr["sys_mem"])
        self.sys_labels["sys_ip"].setText(tr["sys_ip"])
        
        # Page 5: About
        self.lbl_about_name.setText(tr["about_name"])
        self.lbl_about_desc.setText(tr["about_desc"])
        self.lbl_about_ver_name.setText(tr["agent_ver"] if False else "Version:")
        self.lbl_about_build_name.setText(tr["about_build"] if False else "Build Number:")
        self.lbl_about_site_name.setText(tr["about_site"] if False else "Official Website:")
        self.lbl_about_support_name.setText(tr["about_support"] if False else "Technical Support:")
        
        # System Tray Menu Actions
        if hasattr(self, 'tray_menu_actions'):
            self.tray_menu_actions["show"].setText(tr["tray_show"])
            self.tray_menu_actions["web"].setText(tr["tray_web"])
            self.tray_menu_actions["restart"].setText(tr["tray_restart"])
            self.tray_menu_actions["stop"].setText(tr["tray_stop"])
            self.tray_menu_actions["logs"].setText(tr["tray_logs"])
            self.tray_menu_actions["settings"].setText(tr["tray_settings"])
            self.tray_menu_actions["exit"].setText(tr["tray_exit"])
            
        self.update_runtime_state()

    def is_backend_active(self):
        return self.backend_active

    def start_backend_server(self):
        global backend_process
        with process_lock:
            existing_pid = get_pid_occupying_port(5010)
            if existing_pid is not None or (backend_process is not None and backend_process.poll() is None):
                logger.info("Backend is already running on port 5010.")
                self.update_runtime_state()
                return
            
            logger.info("Starting FastAPI server subprocess via PySide6 Agent...")
            try:
                python_exe = get_python_executable()
                cmd = [
                    python_exe, "-m", "uvicorn", "backend.main:app",
                    "--host", "127.0.0.1",
                    "--port", "5010",
                    "--log-level", "warning"
                ]
                env = os.environ.copy()
                env.pop("_MEIPASS", None)
                env.pop("PYTHONHOME", None)
                env.pop("PYTHONPATH", None)
                
                keys_to_pop = []
                for k, v in env.items():
                    if k.upper() == "PATH":
                        continue
                    if "_mei" in k.lower() or "_mei" in v.lower():
                        keys_to_pop.append(k)
                for k in keys_to_pop:
                    env.pop(k, None)
                    
                path = env.get("PATH", "")
                if path:
                    paths = path.split(os.pathsep)
                    cleaned_paths = [p for p in paths if "_mei" not in p.lower()]
                    env["PATH"] = os.pathsep.join(cleaned_paths)

                env["PYTHONUNBUFFERED"] = "1"
                backend_dir = os.path.join(PROJECT_ROOT, "backend")
                env["PYTHONPATH"] = backend_dir
                    
                creationflags = 0
                if sys.platform == 'win32':
                    creationflags = 0x08000000  # CREATE_NO_WINDOW
                
                backend_log_path = os.path.join(PROJECT_ROOT, "backend_server.log")
                try:
                    backend_log_file = open(backend_log_path, "a", encoding="utf-8")
                    backend_log_file.write(f"\n--- FastAPI Backend Server Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    backend_log_file.flush()
                except Exception as e:
                    logger.error("Failed to open backend log: %s", e)
                    backend_log_file = subprocess.DEVNULL
                    
                backend_process = subprocess.Popen(
                    cmd,
                    cwd=PROJECT_ROOT,
                    stdout=backend_log_file,
                    stderr=backend_log_file,
                    env=env,
                    close_fds=True,
                    creationflags=creationflags
                )
                
                if backend_log_file != subprocess.DEVNULL:
                    try:
                        backend_log_file.close()
                    except Exception:
                        pass
                
                self.start_time = time.time()
                logger.info("Backend process launched successfully with PID: %d", backend_process.pid)
                self.show_tray_notification(
                    TRANSLATIONS[self.lang]["notify_started"],
                    TRANSLATIONS[self.lang]["notify_title"]
                )
                QTimer.singleShot(1500, self.open_console_browser)
            except Exception as e:
                logger.exception("Failed to start FastAPI server:")
                
        self.update_runtime_state()

    def stop_backend_server(self):
        global backend_process
        with process_lock:
            pid = None
            if backend_process and backend_process.poll() is None:
                pid = backend_process.pid
            else:
                pid = get_pid_occupying_port(5010)
                
            if pid is None:
                logger.info("No active backend process detected on port 5010 to stop.")
                self.update_runtime_state()
                return
            
            logger.info("Stopping FastAPI server process (PID: %d)...", pid)
            try:
                if sys.platform == 'win32':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=0x08000000
                    )
                else:
                    if backend_process:
                        backend_process.terminate()
                        try:
                            backend_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            backend_process.kill()
                            backend_process.wait()
                    else:
                        try:
                            os.kill(pid, 15)
                        except Exception:
                            pass
                backend_process = None
                self.start_time = None
                logger.info("Backend process stopped.")
                self.show_tray_notification(
                    TRANSLATIONS[self.lang]["notify_stopped"],
                    TRANSLATIONS[self.lang]["notify_title"]
                )
            except Exception as e:
                logger.exception("Failed to stop backend server:")
                
        self.update_runtime_state()

    def restart_backend_server(self):
        self.stop_backend_server()
        QTimer.singleShot(1000, self.start_backend_server)

    def open_console_browser(self):
        logger.info("Opening console browser: %s", APP_URL)
        webbrowser.open(APP_URL)

    # 1-second interval GUI state update (main thread)
    def update_runtime_state(self):
        active = self.is_backend_active()
        tr = TRANSLATIONS[self.lang]
        
        # 1. Update service cards
        if active:
            self.lbl_status_large.setText(tr["status_running"])
            self.lbl_status_large.setStyleSheet("color: #10B981; font-weight: bold;")
            self.lbl_dash_pid_val.setText(str(self.backend_pid) if self.backend_pid else "-")
            
            # Format uptime
            if self.start_time:
                elapsed = int(time.time() - self.start_time)
                days, remainder = divmod(elapsed, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                if days > 0:
                    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
                elif hours > 0:
                    uptime_str = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    uptime_str = f"{minutes}m {seconds}s"
                else:
                    uptime_str = f"{seconds}s"
            else:
                uptime_str = "Active"
                
            self.lbl_dash_uptime_val.setText(uptime_str)
            self.lbl_dash_health_val.setText(tr["health_healthy"])
            self.lbl_dash_health_val.setStyleSheet("color: #10B981; font-weight: bold;")
            
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)
            
            # Set dynamic green tray icon
            if hasattr(self, 'tray_icon'):
                self.tray_icon.setIcon(create_status_icon("green"))
        else:
            self.lbl_status_large.setText(tr["status_stopped"])
            self.lbl_status_large.setStyleSheet("color: #EF4444; font-weight: bold;")
            self.lbl_dash_pid_val.setText("-")
            self.lbl_dash_uptime_val.setText("0s")
            self.lbl_dash_health_val.setText(tr["health_unhealthy"])
            self.lbl_dash_health_val.setStyleSheet("color: #EF4444; font-weight: bold;")
            
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_restart.setEnabled(False)
            
            # Set dynamic red tray icon
            if hasattr(self, 'tray_icon'):
                self.tray_icon.setIcon(create_status_icon("red"))
                
        # 2. Update platform cards
        if self.controller_connected:
            self.lbl_conn_large.setText(tr["conn_connected"])
            self.lbl_conn_large.setStyleSheet("color: #10B981; font-weight: bold;")
        else:
            self.lbl_conn_large.setText(tr["conn_disconnected"])
            self.lbl_conn_large.setStyleSheet("color: #EF4444; font-weight: bold;")
            
        self.lbl_dash_ctrl_val.setText(self.controller_ip)
        self.lbl_dash_sync_val.setText(self.last_sync_time)

    # Background Polling thread
    def is_port_occupied_fast(self, host, port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect((host, port))
                return True
        except Exception:
            return False

    def _status_polling_loop(self):
        while self.poller_running:
            # 1. Poll backend FastAPI status
            active = False
            pid = None
            global backend_process
            with process_lock:
                if backend_process is not None and backend_process.poll() is None:
                    active = True
                    pid = backend_process.pid
                    
            if not active:
                if self.is_port_occupied_fast("127.0.0.1", 5010):
                    active = True
                    pid = get_pid_occupying_port(5010)
                    
            self.backend_active = active
            self.backend_pid = pid
            
            # 2. Poll Controller connectivity status
            conn = False
            ctrl_ip = self.controller_ip
            if ctrl_ip:
                # Developer fallback: if controller ip is 127.0.0.1, respond True if backend is up
                if ctrl_ip in ("127.0.0.1", "localhost"):
                    conn = active
                else:
                    # Quick TCP check on ports 80, 443, 22 or 5010
                    for port in [80, 443, 22, 5010]:
                        if self.is_port_occupied_fast(ctrl_ip, port):
                            conn = True
                            break
            self.controller_connected = conn
            self.last_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            time.sleep(1.5)

    # One-click diagnostics engine
    def trigger_diagnostics(self):
        self.btn_run_diagnose.setEnabled(False)
        self.txt_diagnose_log.clear()
        self.append_diagnose_log("=========================================")
        self.append_diagnose_log(f"[{datetime.now().strftime('%H:%M:%S')}] NetOps Agent 一键诊断开启...")
        self.append_diagnose_log("=========================================")
        threading.Thread(target=self.diagnose_worker, daemon=True).start()

    def append_diagnose_log(self, text):
        self.txt_diagnose_log.appendPlainText(text)
        self.txt_diagnose_log.verticalScrollBar().setValue(self.txt_diagnose_log.verticalScrollBar().maximum())

    def diagnose_worker(self):
        time.sleep(0.5)
        
        # Step 1: Check service status
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 1. 正在检查本地 Agent 服务端口...")
        time.sleep(0.4)
        active = self.is_port_occupied_fast("127.0.0.1", 5010)
        self.diagnostic_log_signal.emit(f"   - 端口 5010 (uvicorn): {'🟢 正常 (ACTIVE)' if active else '🔴 未运行 (INACTIVE)'}")
        
        # Step 2: Controller connection check
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 2. 正在检查控制器连通性 ({self.controller_ip})...")
        time.sleep(0.4)
        conn = False
        if self.controller_ip in ("127.0.0.1", "localhost"):
            conn = active
        else:
            for port in [80, 443, 22, 5010]:
                if self.is_port_occupied_fast(self.controller_ip, port):
                    conn = True
                    break
        self.diagnostic_log_signal.emit(f"   - 连接测试: {'🟢 连通成功 (CONNECTED)' if conn else '🔴 连接失败 (DISCONNECTED)'}")
        
        # Step 3: DNS Check
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 3. 正在检查本地 DNS 解析功能...")
        time.sleep(0.4)
        dns_pass = False
        try:
            socket.gethostbyname("google.com")
            dns_pass = True
        except Exception:
            try:
                socket.gethostbyname("baidu.com")
                dns_pass = True
            except Exception:
                pass
        self.diagnostic_log_signal.emit(f"   - DNS 测试: {'🟢 正常' if dns_pass else '🔴 失败（无法解析公网域名）'}")
        
        # Step 4: NTP Check
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 4. 正在验证 NTP 时间服务器连通...")
        time.sleep(0.4)
        ntp_pass = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.8)
            sock.sendto(b'\x1b' + 47 * b'\0', ("time.windows.com", 123))
            data, address = sock.recvfrom(1024)
            ntp_pass = True
        except Exception:
            pass
        self.diagnostic_log_signal.emit(f"   - NTP 测试: {'🟢 正常 (time.windows.com:123)' if ntp_pass else '🔴 失败（NTP 服务无响应）'}")
        
        # Step 5: API Token Configuration check
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 5. 校验授权 API Token 配置文件...")
        time.sleep(0.3)
        token_found = False
        env_path = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("SECRET_KEY="):
                        val = line.split("=", 1)[1].strip()
                        if val and "your-secret-key" not in val:
                            token_found = True
        self.diagnostic_log_signal.emit(f"   - Token 校验: {'🟢 已配置且有效' if token_found else '🟡 使用默认测试密钥 (WARNING)'}")
        
        # Step 6: Disk space checks
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 6. 监测本地存储空间...")
        try:
            total, used, free = shutil.disk_usage(PROJECT_ROOT)
            free_gb = free / (1024**3)
            self.diagnostic_log_signal.emit(f"   - 剩余可用空间: {free_gb:.2f} GB ({'🟢 充足' if free_gb > 2 else '🔴 空间紧张'})")
        except Exception as e:
            self.diagnostic_log_signal.emit(f"   - 空间检查失败: {e}")
            
        # Step 7: Scanning log anomalies
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 7. 扫描日志异常关键字...")
        time.sleep(0.3)
        log_anomaly_count = 0
        log_path = os.path.join(PROJECT_ROOT, "backend_server.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    # scan last 300 lines
                    for line in lines[-300:]:
                        if "error" in line.lower() or "exception" in line.lower() or "critical" in line.lower():
                            log_anomaly_count += 1
            except Exception:
                pass
        self.diagnostic_log_signal.emit(f"   - 日志关键字检查: {'🟢 正常 (无错误标记)' if log_anomaly_count == 0 else f'🟡 扫描到 {log_anomaly_count} 个异常标记 (WARNING)'}")
        
        # Step 8: Generating Zip file
        self.diagnostic_log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 8. 正在生成打包诊断报告 (diagnostic_report.zip)...")
        time.sleep(0.5)
        
        zip_path = os.path.join(PROJECT_ROOT, "diagnostic_report.zip")
        try:
            # Generate temporary summary txt report
            summary_path = os.path.join(PROJECT_ROOT, "diagnose_summary.txt")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"==================================================\n")
                f.write(f"           NetOps Agent Audit Report              \n")
                f.write(f"==================================================\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Hostname: {socket.gethostname()}\n")
                f.write(f"Platform OS: {platform.system()} {platform.release()}\n")
                f.write(f"Agent Status: {'RUNNING' if active else 'STOPPED'}\n")
                f.write(f"Controller IP: {self.controller_ip} ({'Connected' if conn else 'Disconnected'})\n")
                f.write(f"DNS Resolution: {'PASS' if dns_pass else 'FAILED'}\n")
                f.write(f"NTP Time Synchronization: {'PASS' if ntp_pass else 'FAILED'}\n")
                f.write(f"License Key status: {'OK' if token_found else 'DEFAULT_WARNING'}\n")
                f.write(f"Free Disk Space: {free_gb:.2f} GB\n")
                f.write(f"Log Anomalies Found: {log_anomaly_count}\n")
                f.write(f"==================================================\n")
                
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(summary_path, "summary.txt")
                
                # Write settings configuration
                cfg_path = os.path.join(PROJECT_ROOT, "desktop_settings.ini")
                if os.path.exists(cfg_path):
                    zipf.write(cfg_path, "desktop_settings.ini")
                    
                # Write logs files
                for log_name in ["backend_server.log", "desktop_tray.log"]:
                    lp = os.path.join(PROJECT_ROOT, log_name)
                    if os.path.exists(lp):
                        zipf.write(lp, log_name)
                        
            try:
                os.remove(summary_path)
            except Exception:
                pass
            
            self.diagnostic_log_signal.emit(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🟢 一键诊断运行完成！报告成功打包输出。")
            self.diagnostics_finished_signal.emit(True, zip_path)
        except Exception as e:
            logger.error("Failed to generate diagnostics zip: %s", e)
            self.diagnostic_log_signal.emit(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔴 打包报告失败: {e}")
            self.diagnostics_finished_signal.emit(False, str(e))

    def on_diagnostics_finished(self, success, path_or_err):
        self.btn_run_diagnose.setEnabled(True)
        tr = TRANSLATIONS[self.lang]
        if success:
            QMessageBox.information(
                self, 
                tr["diag_card_title"], 
                tr["diag_done"] % path_or_err
            )
        else:
            QMessageBox.critical(
                self, 
                tr["diag_card_title"], 
                tr["diag_failed"] % path_or_err
            )

    # Tray notifications
    def show_tray_notification(self, message, title="NetOps"):
        # Disabled as requested by the user to avoid startup, stop, and minimization popups
        pass

@atexit.register
def cleanup():
    global backend_process
    if backend_process is not None and backend_process.poll() is None:
        try:
            if sys.platform == 'win32':
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(backend_process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000
                )
            else:
                backend_process.terminate()
                backend_process.wait(timeout=2)
        except Exception:
            try:
                backend_process.kill()
            except Exception:
                pass

def main():
    logger.info("Initializing Enterprise PySide6 NetOps Agent Manager GUI")
    
    # Add Qt library path to ensure image formats (like ICO) can be loaded
    from PySide6.QtCore import QCoreApplication
    plugins_path = os.path.join(PROJECT_ROOT, ".venv", "Lib", "site-packages", "PySide6", "plugins")
    if os.path.exists(plugins_path):
        QCoreApplication.addLibraryPath(plugins_path)
    
    if sys.platform == 'win32':
        try:
            myappid = 'netops.automation.platform.agent.v1'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    window = NetOpsAgentUI()
    
    if not check_single_instance(window.show_window_signal):
        logger.info("Another NetOps Agent instance is already running. Signals sent. Exiting...")
        sys.exit(0)
        
    # Setup System Tray Icon
    tray_icon = QSystemTrayIcon(window)
    window.tray_icon = tray_icon
    
    tray_icon.setIcon(create_status_icon("red"))
    ico_path = os.path.join(PROJECT_ROOT, "netops.ico")
    if os.path.exists(ico_path):
        window.setWindowIcon(QIcon(ico_path))
        
    # Tray Context Menu
    tray_menu = QMenu(window)
    window.tray_menu = tray_menu
    
    window.tray_menu_actions = {}
    
    action_show = QAction("显示控制面板 (Open Panel)", window)
    action_show.triggered.connect(window.show_window)
    tray_menu.addAction(action_show)
    window.tray_menu_actions["show"] = action_show
    
    action_open = QAction("打开网页系统 (Open Web)", window)
    action_open.triggered.connect(window.open_console_browser)
    tray_menu.addAction(action_open)
    window.tray_menu_actions["web"] = action_open
    
    tray_menu.addSeparator()
    
    action_start = QAction("启动服务 (Start)", window)
    action_start.triggered.connect(window.start_backend_server)
    tray_menu.addAction(action_start)
    
    action_stop = QAction("停止服务 (Stop)", window)
    action_stop.triggered.connect(window.stop_backend_server)
    tray_menu.addAction(action_stop)
    window.tray_menu_actions["stop"] = action_stop
    
    action_restart = QAction("重启服务 (Restart)", window)
    action_restart.triggered.connect(window.restart_backend_server)
    tray_menu.addAction(action_restart)
    window.tray_menu_actions["restart"] = action_restart
    
    tray_menu.addSeparator()
    
    action_logs = QAction("查看运行日志 (View Logs)", window)
    action_logs.triggered.connect(lambda: [window.show_window(), window.nav_group[2].setChecked(True), window.on_nav_clicked()])
    tray_menu.addAction(action_logs)
    window.tray_menu_actions["logs"] = action_logs
    
    action_settings = QAction("偏好设置 (Settings)", window)
    action_settings.triggered.connect(lambda: [window.show_window(), window.nav_group[3].setChecked(True), window.on_nav_clicked()])
    tray_menu.addAction(action_settings)
    window.tray_menu_actions["settings"] = action_settings
    
    tray_menu.addSeparator()
    
    action_exit = QAction("退出 (Exit)", window)
    action_exit.triggered.connect(lambda: [
        setattr(window, 'poller_running', False),
        window.stop_backend_server(),
        tray_icon.hide(),
        app.quit()
    ])
    tray_menu.addAction(action_exit)
    window.tray_menu_actions["exit"] = action_exit
    
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    
    def on_tray_activated(reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            window.show_window()
            
    tray_icon.activated.connect(on_tray_activated)
    
    # Initialize translations and show panel window
    window.update_translations()
    window.show_window()
    sys.exit(app.exec())

if __name__ == '__main__':
    if sys.platform == 'win32':
        import multiprocessing
        multiprocessing.freeze_support()
    main()
