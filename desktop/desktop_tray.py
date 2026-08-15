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
import json
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler

SOURCE_DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_PROJECT_ROOT = os.path.dirname(SOURCE_DESKTOP_DIR)
if SOURCE_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_PROJECT_ROOT)

from desktop.ui.feedback import ask_confirmation, show_message, show_toast
from desktop.release_notes import CLIENT_BUILD, CLIENT_VERSION, build_release_notes
from desktop.update_service import (
    UpdateError,
    WindowsRelease,
    create_windows_updater,
    download_windows_release,
    find_latest_windows_release,
    is_newer_version,
)
from desktop.ui.theme import build_codex_stylesheet
from desktop.ui.tokens import theme_tokens

DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DESKTOP_DIR)
LOG_FILE = os.path.join(PROJECT_ROOT, "desktop_tray.log")

def rotate_log_file(filepath, max_backups=10):
    try:
        for i in range(max_backups - 1, 0, -1):
            s = f"{filepath}.{i}"
            d = f"{filepath}.{i+1}"
            if os.path.exists(s):
                if os.path.exists(d):
                    try: os.remove(d)
                    except: pass
                try: os.rename(s, d)
                except: pass
        d = f"{filepath}.1"
        if os.path.exists(d):
            try: os.remove(d)
            except: pass
        os.rename(filepath, d)
    except Exception:
        pass

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
                    if os.path.exists(self.filename) and os.path.getsize(self.filename) > 500 * 1024 * 1024:
                        rotate_log_file(self.filename, 10)
                    with open(self.filename, "a", encoding="utf-8") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{self.prefix}] {line.rstrip()}\n")
                except Exception:
                    pass
        return len(data)

    def flush(self):
        if self.buffer.strip():
            try:
                if os.path.exists(self.filename) and os.path.getsize(self.filename) > 500 * 1024 * 1024:
                    rotate_log_file(self.filename, 10)
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
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=500*1024*1024, backupCount=10, encoding="utf-8")
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
        QPlainTextEdit, QFileDialog, QGridLayout, QScrollArea, QListView,
        QStyledItemDelegate, QDialog, QSizePolicy
    )
    from PySide6.QtCore import Qt, Signal, Slot, QThread, QTimer, QSettings, QPropertyAnimation, QEasingCurve, Property, QRectF
    from PySide6.QtGui import QIcon, QColor, QAction, QPainter, QBrush, QPen, QPixmap
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


class UpdateCheckWorker(QThread):
    """Run the GitHub release check without blocking the Qt event loop."""

    release_found = Signal(object)
    no_release = Signal()
    failed = Signal(str)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        try:
            release = find_latest_windows_release()
            if release is None:
                self.no_release.emit()
                return
            if release and not is_newer_version(release.version, self.current_version):
                release = None
            self.release_found.emit(release)
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class UpdateDownloadWorker(QThread):
    """Download a selected Windows release asset in the background."""

    progress_changed = Signal(int)
    downloaded = Signal(str)
    failed = Signal(str)

    def __init__(self, release: WindowsRelease, destination: str, parent=None):
        super().__init__(parent)
        self.release = release
        self.destination = destination

    def run(self):
        try:
            path = download_windows_release(
                self.release,
                self.destination,
                progress=self.progress_changed.emit,
            )
            self.downloaded.emit(str(path))
        except UpdateError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


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
    ico_path = os.path.join(DESKTOP_DIR, "netops.ico")
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
        painter.setBrush(QBrush(QColor("#2DA44E")))
    elif color_name == "red":
        # Red dot
        painter.setBrush(QBrush(QColor("#CF222E")))
    elif color_name == "yellow":
        # Yellow dot for warning/error
        painter.setBrush(QBrush(QColor("#D29922")))
    elif color_name == "blue":
        # Blue dot for starting (changed to brand cyan)
        painter.setBrush(QBrush(QColor("#8B949E")))
    else:
        # Grey dot for unknown
        painter.setBrush(QBrush(QColor("#6B7280")))
        
    # Draw status dot at (19, 19) with size 11x11, and a dark outline for high visibility
    painter.setPen(QPen(QColor("#0B0F19"), 1.5))
    painter.drawEllipse(19, 19, 11, 11)
    
    painter.end()
    return QIcon(pixmap)


def create_nav_icon(icon_name, color, size=16):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), 1.35)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    inset = 2

    if icon_name == "dashboard":
        cell = 4
        for x, y in ((2, 2), (9, 2), (2, 9), (9, 9)):
            painter.drawRoundedRect(x, y, cell, cell, 1, 1)
    elif icon_name == "service":
        painter.drawEllipse(inset, inset, size - inset * 2, size - inset * 2)
        painter.drawLine(size // 2, 5, size // 2, 11)
        painter.drawLine(5, size // 2, 11, size // 2)
    elif icon_name == "logs":
        for y in (4, 8, 12):
            painter.drawLine(3, y, 13, y)
            painter.drawPoint(1, y)
    elif icon_name == "settings":
        for y, knob in ((4, 6), (8, 10), (12, 5)):
            painter.drawLine(2, y, 14, y)
            painter.setBrush(QBrush(QColor(color)))
            painter.drawEllipse(knob - 1, y - 1, 3, 3)
            painter.setBrush(Qt.NoBrush)
    else:
        painter.drawEllipse(inset, inset, size - inset * 2, size - inset * 2)
        painter.drawLine(size // 2, 7, size // 2, 12)
        painter.drawPoint(size // 2, 4)

    painter.end()
    return pixmap

# Translation resources
TRANSLATIONS = {
    "zh": {
        "title": "NetOps Agent",
        "subtitle": "开源社区版",
        "nav_dashboard": "仪表盘",
        "nav_service": "服务管理",
        "nav_logs": "实时日志",
        "nav_settings": "偏好设置",
        "nav_about": "关于",
        "btn_copy": "复制",
        "btn_copied": "已复制!",
        
        "agent_title": "NetOps Agent",
        "agent_ver": f"版本: v{CLIENT_VERSION}",
        "agent_license": "许可: 免费开源版 (Free & Open Source)",
        "dashboard_page_desc": "查看本地服务、平台连接与诊断状态",
        "service_page_title": "服务管理",
        "service_page_desc": "启动或停止本地服务，并查看运行路径",
        "logs_page_title": "实时日志",
        "logs_page_desc": "筛选、暂停和导出本地运行日志",
        "about_page_title": "关于 NetOps Agent",
        "about_page_desc": "版本信息、项目地址与技术支持",

        "status_card_title": "后台服务状态",
        "status_running": "运行中",
        "status_stopped": "已停止",
        "status_starting": "正在启动",
        "status_unknown": "未知",
        "status_pid": "进程 ID:",
        "status_uptime": "运行时长:",
        "status_port": "服务端口:",
        "status_health": "健康状态:",
        "health_healthy": "正常",
        "health_unhealthy": "异常",

        "conn_card_title": "平台连接状态",
        "conn_connected": "已连接",
        "conn_disconnected": "已断开",
        "conn_controller": "控制器地址:",
        "conn_sync": "上次同步:",
        
        "diag_card_title": "一键诊断",
        "diag_desc": "对本地 Agent 的运行状态、控制器连接性、DNS、NTP 及磁盘空间进行完整性检测。",
        "diag_btn": "运行诊断",
        "diag_running": "正在诊断...",
        "diag_done": "诊断完成！报告保存于 %s",
        "diag_failed": "诊断失败: %s",
        "recent_card_title": "最近事件",
        "recent_empty": "暂无运行事件",
        
        "control_card_title": "服务控制",
        "btn_start": "启动服务",
        "btn_stop": "停止服务",
        "btn_restart": "重启服务",
        
        "meta_card_title": "运行信息",
        "meta_addr": "监听地址",
        "meta_port": "服务端口",
        "meta_dir": "工作目录",
        "meta_cfg": "配置文件",
        "meta_log": "日志文件",
        
        "logs_card_title": "实时日志",
        "log_select_label": "日志源:",
        "log_search_placeholder": "输入关键词进行过滤...",
        "chk_pause_scroll": "暂停滚动",
        "btn_clear": "清空视图",
        "btn_export": "导出日志",
        
        "settings_page_title": "偏好设置",
        "settings_page_desc": "管理客户端行为、外观、连接和本地维护选项",
        "settings_card_title": "常规",
        "settings_appearance_title": "外观",
        "settings_connection_title": "连接",
        "setting_boot_title": "随系统自动启动",
        "setting_boot_desc": "在 Windows 启动时后台自动运行 Agent 管理器",
        "setting_service_title": "自动运行后台服务",
        "setting_service_desc": "启动管理器后自动检测并运行 FastAPI 后台服务",
        "setting_open_browser_title": "启动服务时打开浏览器",
        "setting_open_browser_desc": "当后台服务成功启动后，自动在默认浏览器中弹出 Web 管理端",
        "btn_start_loading": "正在启动...",
        "setting_minimize_title": "关闭窗口时最小化",
        "setting_minimize_desc": "点击窗口关闭按钮时最小化至系统托盘，而非完全退出",
        "setting_update_title": "自动检查可用更新",
        "setting_update_desc": "开启后，每次启动客户端自动检查最新的 exe 版本并提示",
        
        "setting_lang_title": "界面显示语言",
        "setting_lang_desc": "设置管理器客户端的用户界面显示语言",
        "setting_theme_title": "深浅主题风格",
        "setting_theme_desc": "调整主面板明亮或暗黑的系统主题样式",
        "setting_ip_title": "控制器 IP 地址",
        "setting_ip_desc": "本地代理所指向的控制器服务网络通信 IP",
        "btn_test_controller": "测试",
        "btn_test_controller_testing": "测试中...",
        
        "settings_adv_title": "高级维护",
        "setting_reconfig_title": "修改环境配置向导",
        "setting_reconfig_desc": "重新运行向导以修改数据库及平台控制器连接参数",
        "btn_reconfig_db": "启动向导",
        
        "setting_reset_title": "重置代理客户端",
        "setting_reset_desc": "恢复当前 Agent 为初始未配置状态并清除本地环境参数",
        "btn_reset_config": "恢复初始",
        
        "setting_clear_title": "危险操作！彻底清除数据库",
        "setting_clear_desc": "擦除变更工单、CMDB 设备等本地全部数据，不可逆！",
        "btn_clear_db": "清理数据",
        
        "sys_ip_copy": "复制",
        "sys_ip_copied": "已复制!",
        
        "sys_card_title": "系统信息",
        "sys_hostname": "主机名称",
        "sys_os": "操作系统",
        "sys_cpu": "处理器",
        "sys_cpu_cores": "处理器核心数",
        "sys_mem": "内存容量",
        "sys_disk": "系统磁盘空间",
        "sys_mac": "网卡物理地址",
        "sys_python": "Python 运行环境",
        "sys_ip": "网络地址",
        
        "about_name": "NetOps 智能自动化网络运维平台",
        "about_desc": "NetOps Agent 是一款轻量级、开源社区版的网络设备监测与自动化管理客户端，支持后台自愈和多端同步调度。",
        "about_build": "构建编号: 20260622.1082",
        "about_site": "官方网站: ",
        "about_support": "技术支持: ",
        "about_check_updates": "检查更新",
        "about_checking_updates": "正在检查更新...",
        "about_up_to_date": "当前已是最新版本",
        "about_no_windows_release": "暂未找到可用的 Windows Release，请稍后再试。",
        "about_update_available": "发现新版本 v%s，是否立即下载并更新？",
        "about_update_downloading": "正在下载 v%s：%s%%",
        "about_update_ready": "更新已下载，程序将关闭并自动重启完成更新。",
        "about_update_failed": "更新失败: %s",
        "about_update_not_supported": "在线更新仅支持 Windows 版 NetOps.exe。",
        
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
        "subtitle": "Community",
        "nav_dashboard": "Dashboard",
        "nav_service": "Service",
        "nav_logs": "Logs",
        "nav_settings": "Settings",
        "nav_about": "About",
        "btn_copy": "Copy",
        "btn_copied": "Copied!",
        
        "agent_title": "NetOps Agent Community",
        "agent_ver": f"Version: v{CLIENT_VERSION}",
        "agent_license": "License: Free & Open Source",
        "dashboard_page_desc": "Review local service, platform connection, and diagnostics",
        "service_page_title": "Service",
        "service_page_desc": "Control the local service and inspect runtime paths",
        "logs_page_title": "Logs",
        "logs_page_desc": "Filter, pause, and export local runtime logs",
        "about_page_title": "About NetOps Agent",
        "about_page_desc": "Version details, project links, and support",
        
        "status_card_title": "Backend Service Status",
        "status_running": "RUNNING",
        "status_stopped": "STOPPED",
        "status_starting": "STARTING",
        "status_unknown": "UNKNOWN",
        "status_pid": "PID:",
        "status_uptime": "Uptime:",
        "status_port": "Port:",
        "status_health": "Health:",
        "health_healthy": "Healthy",
        "health_unhealthy": "Unhealthy",
        
        "conn_card_title": "Platform Connection",
        "conn_connected": "Connected",
        "conn_disconnected": "Disconnected",
        "conn_controller": "Controller IP:",
        "conn_sync": "Last Sync:",
        
        "diag_card_title": "Run Diagnostics",
        "diag_desc": "Performs checks on local Agent process, controller connectivity, DNS, NTP, and local storage limits.",
        "diag_btn": "Run Diagnostics",
        "diag_running": "Running audit...",
        "diag_done": "Audit successful! Saved to %s",
        "diag_failed": "Diagnostics failed: %s",
        "recent_card_title": "Recent events",
        "recent_empty": "No recent events",
        
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
        
        "settings_page_title": "Settings",
        "settings_page_desc": "Manage client behavior, appearance, connectivity, and local maintenance",
        "settings_card_title": "General",
        "settings_appearance_title": "Appearance",
        "settings_connection_title": "Connection",
        "setting_boot_title": "Start on System Boot",
        "setting_boot_desc": "Launch Agent Manager automatically when Windows starts",
        "setting_service_title": "Auto-Start Service",
        "setting_service_desc": "Detect and spin up backend FastAPI service automatically on launch",
        "setting_open_browser_title": "Auto-Open Browser",
        "setting_open_browser_desc": "Automatically launch Web UI in default browser once the backend is ready",
        "btn_start_loading": "Starting...",
        "setting_minimize_title": "Minimize on Close",
        "setting_minimize_desc": "Minimize window to system tray instead of exiting when closed",
        "setting_update_title": "Auto Check Updates",
        "setting_update_desc": "Check for updates and notify when manager starts up",
        
        "setting_lang_title": "Interface Language",
        "setting_lang_desc": "Select display language for the client user interface",
        "setting_theme_title": "Color Theme Style",
        "setting_theme_desc": "Toggle main control panel light/dark visual theme skins",
        "setting_ip_title": "Controller IP Address",
        "setting_ip_desc": "The network IP address pointing to the central controller server",
        "btn_test_controller": "Test",
        "btn_test_controller_testing": "Testing...",
        
        "settings_adv_title": "System Maintenance & Actions",
        "setting_reconfig_title": "Re-run Configuration Wizard",
        "setting_reconfig_desc": "Run setup wizard again to modify DB credentials & Controller IP",
        "btn_reconfig_db": "Configure",
        
        "setting_reset_title": "Reset Agent Manager",
        "setting_reset_desc": "Delete local environment variables and revert to unconfigured status",
        "btn_reset_config": "Reset",
        
        "setting_clear_title": "Destructive Action! Erase Database",
        "setting_clear_desc": "Completely wipe out all CMDB devices and tickets local data",
        "btn_clear_db": "Erase Data",
        
        "sys_ip_copy": "Copy",
        "sys_ip_copied": "Copied!",
        
        "sys_card_title": "System Specifications",
        "sys_hostname": "Hostname",
        "sys_os": "Operating System (OS)",
        "sys_cpu": "Processor (CPU)",
        "sys_cpu_cores": "CPU Cores",
        "sys_mem": "Physical Memory (RAM)",
        "sys_disk": "System Disk Space",
        "sys_mac": "MAC Address",
        "sys_python": "Python Version",
        "sys_ip": "Local IP Address",
        
        "about_name": "NetOps Intelligent Network Automation Platform",
        "about_desc": "NetOps Agent is a lightweight, open-source community device monitoring and orchestration client, supporting background healing and central remote scheduling.",
        "about_build": "Build Number: 20260622.1082",
        "about_site": "Official Website: ",
        "about_support": "Technical Support: ",
        "about_check_updates": "Check for Updates",
        "about_checking_updates": "Checking for updates...",
        "about_up_to_date": "You are using the latest version",
        "about_no_windows_release": "No Windows release is available yet. Please try again later.",
        "about_update_available": "Version v%s is available. Download and install it now?",
        "about_update_downloading": "Downloading v%s: %s%%",
        "about_update_ready": "The update is ready. The app will close and restart to finish.",
        "about_update_failed": "Update failed: %s",
        "about_update_not_supported": "Online updates are available only for the Windows NetOps.exe build.",
        
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


class ToggleSwitch(QCheckBox):
    """自绘的 iOS 风格开关。

    取代原先依赖 QSS `image: url(data:image/svg+xml...)` 的 QCheckBox 指示器——
    Qt 对内联 SVG data-uri 的渲染在不同构建上并不可靠（截图里开关不可见即源于此）。
    这里完全用 QPainter 绘制轨道 + 滑块，并带轻量的滑动动画，确保在明/暗主题下都稳定可见。
    """

    def __init__(self, parent=None, dark=True):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(36, 20)
        self.setText("")
        self._dark = dark
        self._offset = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate_to_state)

    def _animate_to_state(self, _checked):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if self.isChecked() else 0.0)
        self._anim.start()

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def apply_palette(self, dark):
        self._dark = dark
        # 不经过动画，直接对齐当前勾选态，避免主题切换时滑块跳动
        self._offset = 1.0 if self.isChecked() else 0.0
        self.update()

    @staticmethod
    def _blend(c1, c2, t):
        return QColor(
            int(c1.red() + (c2.red() - c1.red()) * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue() + (c2.blue() - c1.blue()) * t),
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        radius = h / 2.0

        tokens = theme_tokens(self._dark)
        track_off = QColor(tokens["border_strong"])
        track_on = QColor(tokens["accent"])
        track = self._blend(track_off, track_on, self._offset)

        if self.hasFocus():
            painter.setPen(QPen(QColor(tokens["focus"]), 1.0))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(track))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        margin = 2.5
        knob_d = h - margin * 2
        x = margin + (w - knob_d - margin * 2) * self._offset
        knob_off = QColor(tokens["text_secondary"] if self._dark else "#FFFFFF")
        knob_on = QColor(tokens["accent_text"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._blend(knob_off, knob_on, self._offset)))
        painter.drawEllipse(QRectF(x, margin, knob_d, knob_d))
        painter.end()


class ProgressSpinner(QWidget):
    """自绘制的 Fluent 风格旋转进度条 (Smooth 60FPS spinner)."""
    def __init__(self, parent=None, color="#8B949E"):
        super().__init__(parent)
        self.color = QColor(color)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(16)  # 60 FPS
        self.setFixedSize(40, 40)

    def rotate(self):
        self.angle = (self.angle + 6) % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self.color, 4, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        painter.drawArc(rect, -self.angle * 16, 270 * 16)
        painter.end()


class StatusIcon(QWidget):
    """自绘制的成功/失败状态图标 (Success checkmark / Failure X)."""
    def __init__(self, parent=None, is_success=True):
        super().__init__(parent)
        self.is_success = is_success
        self.setFixedSize(40, 40)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.is_success:
            pen = QPen(QColor("#2DA44E"), 4, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(10, 20, 18, 28)
            painter.drawLine(18, 28, 30, 12)
        else:
            pen = QPen(QColor("#CF222E"), 4, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(12, 12, 28, 28)
            painter.drawLine(28, 12, 12, 28)
        painter.end()


class FluentProgressDialog(QDialog):
    """仿 Win11/Fluent 设计的无边框圆角模态进度对话框。"""
    def __init__(self, parent=None, title="", dark_mode=True, lang="zh"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.CustomizeWindowHint)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        if sys.platform == "win32":
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        
        self.dark_mode = dark_mode
        self.lang = lang
        self.setup_ui()

    def setup_ui(self):
        # 主边框容器
        self.container = QFrame(self)
        self.container.setObjectName("dialog_container")
        
        # 配色定义
        tokens = theme_tokens(self.dark_mode)
        bg_color = tokens["bg_overlay"]
        border_color = tokens["border"]
        text_color = tokens["text_primary"]
        desc_color = tokens["text_muted"]
        primary_bg = tokens["accent"]
        primary_fg = tokens["accent_text"]
        primary_hover = tokens["text_secondary"]
        primary_pressed = tokens["text_muted"]
        
        self.container.setStyleSheet(f"""
            QFrame#dialog_container {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text_color};
                font-family: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", sans-serif;
                font-size: 13px;
                border: none;
                background: transparent;
            }}
            QLabel#title_label {{
                font-size: 16px;
                font-weight: 600;
            }}
            QLabel#status_label {{
                color: {desc_color};
                font-size: 12px;
            }}
            QPushButton#btn_close {{
                background-color: {primary_bg};
                color: {primary_fg};
                border-radius: 8px;
                padding: 7px 20px;
                font-weight: 600;
                border: 1px solid {primary_bg};
                font-size: 12px;
                outline: none;
            }}
            QPushButton#btn_close:hover {{
                background-color: {primary_hover};
            }}
            QPushButton#btn_close:pressed {{
                background-color: {primary_pressed};
            }}
            QPushButton#btn_close:disabled {{
                background-color: {tokens['bg_subtle']};
                color: {desc_color};
                border: none;
            }}
        """)
        
        # 阴影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80 if self.dark_mode else 40))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)
        
        # 全局透明布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.container)
        
        # 容器内布局
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(24, 24, 24, 24)
        container_layout.setSpacing(16)
        
        self.lbl_title = QLabel(self.windowTitle(), self.container)
        self.lbl_title.setObjectName("title_label")
        container_layout.addWidget(self.lbl_title, 0, Qt.AlignLeft)
        
        # 进度指示布局
        self.progress_layout = QHBoxLayout()
        self.progress_layout.setSpacing(16)
        
        # 初始化 spinner 并放置在固定大小容器中
        self.icon_container = QWidget(self.container)
        self.icon_container.setFixedSize(40, 40)
        self.icon_layout = QVBoxLayout(self.icon_container)
        self.icon_layout.setContentsMargins(0, 0, 0, 0)
        
        self.spinner = ProgressSpinner(self.icon_container, color=tokens["text_muted"])
        self.icon_layout.addWidget(self.spinner)
        self.progress_layout.addWidget(self.icon_container)
        
        self.lbl_status = QLabel(
            "正在停止服务并清理数据库，请稍候..." if self.lang == "zh" else "Stopping service and cleaning database, please wait...",
            self.container
        )
        self.lbl_status.setObjectName("status_label")
        self.lbl_status.setWordWrap(True)
        self.progress_layout.addWidget(self.lbl_status, 1)
        
        container_layout.addLayout(self.progress_layout)
        
        # 关闭/确认按钮
        self.btn_close = QPushButton("确定" if self.lang == "zh" else "OK", self.container)
        self.btn_close.setObjectName("btn_close")
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        container_layout.addWidget(self.btn_close, 0, Qt.AlignRight)
        
        self.setFixedSize(420, 190)

    # 允许拖拽无边框窗口
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


class DatabaseResetConfirmDialog(QDialog):
    def __init__(self, target, config_source, backup_directory, dark_mode=True, lang="zh", parent=None):
        super().__init__(parent)
        self.database_name = target["database"]
        self.dark_mode = dark_mode
        self.lang = lang
        self.setModal(True)
        self.setWindowTitle("恢复数据库出厂状态" if lang == "zh" else "Factory Reset Database")
        self.setMinimumWidth(620)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        tokens = theme_tokens(dark_mode)
        background = tokens["bg_overlay"]
        panel = tokens["bg_subtle"]
        border = tokens["border"]
        text = tokens["text_primary"]
        muted = tokens["text_muted"]
        input_background = tokens["bg_subtle"]
        secondary_hover = tokens["bg_surface"]

        self.setStyleSheet(f"""
            QDialog {{ background-color: {background}; color: {text}; }}
            QLabel {{ color: {text}; background: transparent; font-size: 12px; }}
            QLabel#dialog_title {{ font-size: 17px; font-weight: 600; }}
            QLabel#dialog_description {{ color: {muted}; line-height: 18px; }}
            QFrame#target_panel {{ background-color: {panel}; border: 1px solid {border}; border-radius: 10px; }}
            QLabel#field_name {{ color: {muted}; }}
            QLabel#field_value {{ color: {text}; font-weight: 600; }}
            QLineEdit {{
                background-color: {input_background}; color: {text}; border: 1px solid {border};
                border-radius: 8px; padding: 8px 10px; selection-background-color: #0969DA;
            }}
            QLineEdit:focus {{ border-color: #CF222E; }}
            QPushButton {{ border-radius: 8px; padding: 8px 18px; font-weight: 600; min-width: 82px; }}
            QPushButton#cancel_button {{ background-color: transparent; color: {text}; border: 1px solid {border}; }}
            QPushButton#cancel_button:hover {{ background-color: {secondary_hover}; }}
            QPushButton#reset_button {{ background-color: {tokens['danger']}; color: #FFFFFF; border: 1px solid {tokens['danger']}; }}
            QPushButton#reset_button:hover {{ background-color: {tokens['danger_bg']}; color: {tokens['danger']}; border-color: {tokens['danger']}; }}
            QPushButton#reset_button:disabled {{ background-color: {panel}; color: {muted}; border-color: {border}; }}
            QPushButton#reset_button:disabled:hover {{ background-color: {panel}; color: {muted}; border-color: {border}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        title = QLabel("危险操作：恢复数据库出厂状态" if lang == "zh" else "Dangerous action: factory reset database")
        title.setObjectName("dialog_title")
        layout.addWidget(title)

        description = QLabel(
            "系统会先创建 PostgreSQL 备份，再清除 public schema 中的全部业务数据并重新建表。\n"
            "附件、PAM 录像、日志和环境配置不会被删除。"
            if lang == "zh"
            else "A PostgreSQL backup will be created before all business data in the public schema is removed.\n"
                 "Attachments, PAM recordings, logs, and environment files will not be deleted."
        )
        description.setObjectName("dialog_description")
        description.setWordWrap(True)
        layout.addWidget(description)

        target_address = (
            f"{target['host']}:{target['port']}" if target["backend"] == "postgresql" else target["host"]
        )
        panel_widget = QFrame(self)
        panel_widget.setObjectName("target_panel")
        panel_layout = QGridLayout(panel_widget)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setHorizontalSpacing(20)
        panel_layout.setVerticalSpacing(9)
        fields = [
            (("数据库类型", "Backend"), target["backend"]),
            (("目标地址", "Address"), target_address),
            (("数据库名", "Database"), self.database_name),
            (("配置来源", "Configuration"), f"{config_source} (DATABASE_URL)"),
            (("备份目录", "Backup directory"), backup_directory),
        ]
        for row, (labels, value) in enumerate(fields):
            name_label = QLabel(labels[0] if lang == "zh" else labels[1])
            name_label.setObjectName("field_name")
            value_label = QLabel(str(value))
            value_label.setObjectName("field_value")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)
            panel_layout.addWidget(name_label, row, 0, Qt.AlignTop)
            panel_layout.addWidget(value_label, row, 1)
        panel_layout.setColumnStretch(1, 1)
        layout.addWidget(panel_widget)

        confirmation_label = QLabel(
            f"请输入数据库名 {self.database_name} 以确认执行："
            if lang == "zh"
            else f"Type the database name {self.database_name} to continue:"
        )
        layout.addWidget(confirmation_label)
        self.confirmation_input = QLineEdit(self)
        self.confirmation_input.setPlaceholderText(self.database_name)
        layout.addWidget(self.confirmation_input)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.cancel_button = QPushButton("取消" if lang == "zh" else "Cancel", self)
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.setDefault(True)
        self.cancel_button.setAccessibleName("取消数据库清理")
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button = QPushButton("确认清理" if lang == "zh" else "Reset Database", self)
        self.reset_button.setObjectName("reset_button")
        self.reset_button.setEnabled(False)
        self.reset_button.setAutoDefault(False)
        self.reset_button.setAccessibleName("确认清理数据库")
        self.reset_button.clicked.connect(self.accept)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.reset_button)
        layout.addLayout(button_layout)

        self.confirmation_input.textChanged.connect(
            lambda value: self.reset_button.setEnabled(value.strip() == self.database_name)
        )
        self.cancel_button.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        set_dark_title_bar(self.winId(), self.dark_mode)


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
        launcher_path = os.path.join(DESKTOP_DIR, "launcher.py")
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
    controller_test_result_signal = Signal(bool)
    db_reset_finished_signal = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.lang = "zh"
        self.dark_mode = True
        self.start_time = None
        
        # Connection status fields
        self.backend_active = False
        self.backend_starting = False
        self.backend_pid = None
        self.controller_connected = False
        self.last_sync_time = "-"
        self._sidebar_collapsed = False
        self.recent_events = []
        self.update_check_worker = None
        self.update_download_worker = None
        self.pending_windows_release = None
        
        # Load persistent configurations
        self.load_settings()
        
        # Connect single instance and diagnostics signals
        self.show_window_signal.connect(self.show_window)
        self.diagnostic_log_signal.connect(self.append_diagnose_log)
        self.diagnostics_finished_signal.connect(self.on_diagnostics_finished)
        self.controller_test_result_signal.connect(self.on_controller_test_result)
        self.db_reset_finished_signal.connect(self.on_db_reset_finished)
        
        # Main Window configuration
        self.setWindowTitle("NetOps Agent Manager")
        self.setMinimumSize(920, 640)
        self.resize(1180, 760)
        
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
        settings_path = os.path.join(DESKTOP_DIR, "desktop_settings.ini")
        self.settings = QSettings(settings_path, QSettings.IniFormat)
        self.auto_start_service = self.settings.value("auto_start_service", False, type=bool)
        self.minimize_to_tray = self.settings.value("minimize_to_tray", True, type=bool)
        self.boot_start = self.settings.value("boot_start", False, type=bool)
        self.auto_updates = self.settings.value("auto_updates", True, type=bool)
        self.lang = self.settings.value("lang", "zh", type=str)
        self.dark_mode = self.settings.value("dark_mode", True, type=bool)
        self.controller_ip = self.settings.value("controller_ip", "10.1.1.10", type=str)
        self.auto_open_browser = self.settings.value("auto_open_browser", True, type=bool)

    def show_release_notes_if_needed(self):
        last_seen_version = self.settings.value("last_seen_release_notes_version", "", type=str)
        if last_seen_version == CLIENT_VERSION:
            return False

        title, message, confirm_text = build_release_notes(self.lang)
        show_message(
            self,
            title,
            message,
            dark=self.dark_mode,
            confirm_text=confirm_text,
        )
        self.settings.setValue("last_seen_release_notes_version", CLIENT_VERSION)
        self.settings.sync()
        return True

    def check_for_updates(self):
        """Check the public Windows release without freezing the About page."""

        if self.update_check_worker and self.update_check_worker.isRunning():
            return

        target_exe = os.path.join(PROJECT_ROOT, "NetOps.exe")
        if sys.platform != "win32" or not os.path.exists(target_exe):
            tr = TRANSLATIONS[self.lang]
            show_message(
                self,
                tr["about_check_updates"],
                tr["about_update_not_supported"],
                dark=self.dark_mode,
            )
            return

        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText(tr["about_checking_updates"])
        worker = UpdateCheckWorker(CLIENT_VERSION, self)
        worker.release_found.connect(self._on_update_release_found)
        worker.no_release.connect(self._on_no_windows_release)
        worker.failed.connect(self._on_update_check_failed)
        self.update_check_worker = worker
        worker.start()

    def _on_update_release_found(self, release):
        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(True)
        if release is None:
            self.lbl_update_status.setText(tr["about_up_to_date"])
            show_toast(self, tr["about_up_to_date"], dark=self.dark_mode, level="success")
            return

        self.pending_windows_release = release
        notes = (release.notes or "").strip()
        if len(notes) > 1600:
            notes = notes[:1600].rstrip() + "..."
        message = tr["about_update_available"] % release.version
        if notes:
            message += f"\n\n{notes}"
        if ask_confirmation(
            self,
            tr["about_check_updates"],
            message,
            dark=self.dark_mode,
            confirm_text="立即更新" if self.lang == "zh" else "Update now",
            cancel_text="稍后" if self.lang == "zh" else "Later",
        ):
            self._download_pending_update()
        else:
            self.pending_windows_release = None

    def _on_no_windows_release(self):
        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(True)
        self.lbl_update_status.setText(tr["about_no_windows_release"])
        show_toast(self, tr["about_no_windows_release"], dark=self.dark_mode, level="warning")

    def _on_update_check_failed(self, message):
        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(True)
        self.lbl_update_status.setText(tr["about_update_failed"] % message)
        show_toast(
            self,
            tr["about_update_failed"] % message,
            dark=self.dark_mode,
            level="error",
            duration=5000,
        )

    def _download_pending_update(self):
        release = self.pending_windows_release
        if release is None:
            return
        fd, destination = tempfile.mkstemp(prefix="NetOps-update-", suffix=".exe")
        os.close(fd)
        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(False)
        self.lbl_update_status.setText(tr["about_update_downloading"] % (release.version, 0))
        worker = UpdateDownloadWorker(release, destination, self)
        worker.progress_changed.connect(
            lambda value: self.lbl_update_status.setText(
                tr["about_update_downloading"] % (release.version, value)
            )
        )
        worker.downloaded.connect(self._on_update_downloaded)
        worker.failed.connect(self._on_update_download_failed)
        self.update_download_worker = worker
        worker.start()

    def _on_update_download_failed(self, message):
        tr = TRANSLATIONS[self.lang]
        self.btn_check_update.setEnabled(True)
        self.lbl_update_status.setText(tr["about_update_failed"] % message)
        show_toast(
            self,
            tr["about_update_failed"] % message,
            dark=self.dark_mode,
            level="error",
            duration=5000,
        )

    def _on_update_downloaded(self, downloaded_path):
        tr = TRANSLATIONS[self.lang]
        target_exe = os.path.join(PROJECT_ROOT, "NetOps.exe")
        release = self.pending_windows_release
        try:
            if not release or not os.path.exists(target_exe):
                raise UpdateError("The current Windows executable could not be located")
            updater = create_windows_updater(target_exe, downloaded_path, os.getpid())
            show_message(
                self,
                tr["about_check_updates"],
                tr["about_update_ready"],
                dark=self.dark_mode,
            )
            self.stop_backend_server()
            self.poller_running = False
            if hasattr(self, "tray_icon"):
                self.tray_icon.hide()
            subprocess.Popen(
                ["cmd.exe", "/d", "/c", str(updater)],
                cwd=PROJECT_ROOT,
                creationflags=0x08000000,
                close_fds=True,
            )
            self.pending_windows_release = None
            QApplication.quit()
        except Exception as exc:
            self._on_update_download_failed(str(exc))

    def launch_reconfig_wizard(self, force_reconfig=True):
        # Stop backend server first to release port 5010 and files
        self.stop_backend_server()
        
        # Locate NetOps.exe or launcher.py
        exe_path = os.path.join(PROJECT_ROOT, "NetOps.exe")
        if not os.path.exists(exe_path):
            launcher_script = os.path.join(DESKTOP_DIR, "launcher.py")
            pythonw_exe = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "pythonw.exe")
            if os.path.exists(pythonw_exe) and os.path.exists(launcher_script):
                cmd = [pythonw_exe, launcher_script]
            else:
                cmd = [sys.executable, os.path.join(DESKTOP_DIR, "launcher.py")]
        else:
            cmd = [exe_path]

        if force_reconfig:
            cmd.append("--reconfig")

        # Clean environment to avoid PyInstaller variable conflicts
        clean_env = dict(os.environ)
        keys_to_pop = []
        for k in clean_env.keys():
            if k.startswith("_PYI_") or k == "_MEIPASS" or k == "PYTHONHOME" or k == "PYTHONPATH":
                keys_to_pop.append(k)
        for k in keys_to_pop:
            clean_env.pop(k, None)

        try:
            subprocess.Popen(cmd, cwd=PROJECT_ROOT, creationflags=0x08000000, env=clean_env)
            logger.info("Launched configuration wizard. Exiting tray...")
            self.tray_icon.hide()
            QApplication.quit()
        except Exception as e:
            logger.error("Failed to launch configuration wizard: %s", e)
            show_message(
                self,
                "启动失败" if self.lang == "zh" else "Launch Failed",
                f"无法启动配置向导：{e}" if self.lang == "zh" else f"Unable to launch setup wizard: {e}",
                dark=self.dark_mode,
            )

    def reset_initial_config(self):
        title = "恢复初始配置" if self.lang == "zh" else "Restore Initial Config"
        msg = "确定要恢复初始配置吗？这将清除当前的环境配置和数据库连接设置，并重新启动配置向导。" if self.lang == "zh" else "Are you sure you want to restore the initial configuration? This will delete the current environment settings and database connection credentials, and restart the configuration wizard."
        
        confirmed = ask_confirmation(
            self,
            title,
            msg,
            dark=self.dark_mode,
            confirm_text="恢复初始" if self.lang == "zh" else "Restore",
            cancel_text="取消" if self.lang == "zh" else "Cancel",
            dangerous=True,
        )

        if confirmed:
            env_path = os.path.join(PROJECT_ROOT, ".env")
            try:
                if os.path.exists(env_path):
                    os.remove(env_path)
                logger.info("Deleted .env file for initial reset configuration.")
            except Exception as e:
                logger.error("Failed to delete .env file: %s", e)
                show_message(
                    self,
                    "重置失败" if self.lang == "zh" else "Reset Failed",
                    f"无法删除环境配置文件：{e}"
                    if self.lang == "zh"
                    else f"Unable to remove the environment file: {e}",
                    dark=self.dark_mode,
                )
                return
            
            self.launch_reconfig_wizard(force_reconfig=False)

    def clear_and_reset_database(self):
        try:
            inspection = self._run_database_reset_command("inspect")
            target = inspection["target"]
        except Exception as exc:
            show_message(
                self,
                "数据库检查失败" if self.lang == "zh" else "Database Check Failed",
                str(exc),
                dark=self.dark_mode,
            )
            return

        confirmation_dialog = DatabaseResetConfirmDialog(
            target=target,
            config_source=inspection.get("config_source", os.path.join(PROJECT_ROOT, ".env")),
            backup_directory=inspection.get(
                "backup_directory",
                os.path.join(PROJECT_ROOT, "data", "backups", "database-reset"),
            ),
            dark_mode=self.dark_mode,
            lang=self.lang,
            parent=self,
        )
        if confirmation_dialog.exec() != QDialog.Accepted:
            return

        database_name = target["database"]
        title = "恢复数据库出厂状态" if self.lang == "zh" else "Factory Reset Database"
        self.db_reset_dialog = FluentProgressDialog(self, title, self.dark_mode, self.lang)
        self.stop_backend_server()

        def reset_worker():
            try:
                result = self._run_database_reset_command("reset", database_name, timeout=900)
                self.db_reset_finished_signal.emit(True, json.dumps(result, ensure_ascii=False))
            except Exception as exc:
                self.db_reset_finished_signal.emit(False, str(exc))

        threading.Thread(target=reset_worker, daemon=True).start()
        self.db_reset_dialog.exec()

    def _run_database_reset_command(self, action, database_name="", timeout=30):
        command = [get_python_executable(), "-m", "database.reset", action]
        if action == "reset":
            command.extend(["--confirm-database", database_name])
        environment = os.environ.copy()
        environment.pop("_MEIPASS", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONPATH"] = os.path.join(PROJECT_ROOT, "backend")
        result = subprocess.run(
            command,
            cwd=os.path.join(PROJECT_ROOT, "backend"),
            env=environment,
            capture_output=True,
            text=True,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
            timeout=timeout,
        )
        output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(output_lines[-1]) if output_lines else {}
        except json.JSONDecodeError as exc:
            detail = result.stderr.strip() or result.stdout.strip() or str(exc)
            raise RuntimeError(detail) from exc
        if result.returncode != 0 or not payload.get("ok"):
            raise RuntimeError(payload.get("error") or result.stderr.strip() or "Database reset failed")
        return payload

    def on_db_reset_finished(self, success, message):
        if not hasattr(self, "db_reset_dialog") or self.db_reset_dialog is None:
            return

        self.db_reset_dialog.spinner.hide()
        self.db_reset_dialog.icon_layout.removeWidget(self.db_reset_dialog.spinner)
        status_icon = StatusIcon(self.db_reset_dialog.icon_container, is_success=success)
        self.db_reset_dialog.icon_layout.addWidget(status_icon)

        if success:
            try:
                result = json.loads(message) if message else {}
            except json.JSONDecodeError:
                result = {}
            backup_path = result.get("backup_path", "")
            verification = result.get("verification", {})
            table_count = verification.get("table_count", 0)
            status_message = (
                "数据库已成功备份并恢复出厂状态！\n"
                "管理员账户：admin / admin（请登录后立即修改密码）\n"
                f"已重建 {table_count} 张表。\n"
                f"备份文件：{backup_path}\n"
                "正在重新启动后端服务。"
                if self.lang == "zh"
                else (
                    "Database backup and factory reset completed successfully!\n"
                    "Administrator: admin / admin (change it immediately after login)\n"
                    f"Rebuilt {table_count} tables.\n"
                    f"Backup: {backup_path}\n"
                    "The backend service is restarting."
                )
            )
            self.db_reset_dialog.lbl_status.setText(status_message)
            QTimer.singleShot(500, self.start_backend_server)
        else:
            prefix = "数据库恢复出厂失败：\n" if self.lang == "zh" else "Database factory reset failed:\n"
            self.db_reset_dialog.lbl_status.setText(f"{prefix}{message}")

        self.db_reset_dialog.btn_close.setEnabled(True)
        self.update_runtime_state()

    def save_settings(self):
        self.auto_start_service = self.chk_auto_start.isChecked()
        self.minimize_to_tray = self.chk_minimize_close.isChecked()
        self.auto_updates = self.chk_auto_update.isChecked()
        self.lang = "zh" if self.combo_lang_settings.currentIndex() == 0 else "en"
        self.dark_mode = (self.combo_theme.currentIndex() == 0)
        self.controller_ip = self.combo_controller_ip.currentText().strip()
        self.auto_open_browser = self.chk_open_browser.isChecked()
        
        # Only update registry if boot_start value has actually changed to avoid lag
        new_boot_start = self.chk_boot_start.isChecked()
        boot_start_changed = (new_boot_start != self.boot_start)
        self.boot_start = new_boot_start
        
        self.settings.setValue("auto_start_service", self.auto_start_service)
        self.settings.setValue("minimize_to_tray", self.minimize_to_tray)
        self.settings.setValue("boot_start", self.boot_start)
        self.settings.setValue("auto_updates", self.auto_updates)
        self.settings.setValue("lang", self.lang)
        self.settings.setValue("dark_mode", self.dark_mode)
        self.settings.setValue("controller_ip", self.controller_ip)
        self.settings.setValue("auto_open_browser", self.auto_open_browser)
        self.settings.sync()
        
        # Registry integration (only update on real changes to prevent lag)
        if boot_start_changed:
            set_autostart_registry(self.boot_start)
        if hasattr(self, "lbl_settings_saved"):
            self.lbl_settings_saved.setText("已保存" if self.lang == "zh" else "Saved")
            self.lbl_settings_saved.show()
            QTimer.singleShot(1800, self.lbl_settings_saved.hide)

    def setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)

        # 自绘开关集合（在任何页面构建前初始化，供 logs/settings 页共同登记，apply_theme 统一刷新配色）
        self.toggle_switches = []
        
        # Left-Right main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 1. Left Sidebar
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("sidebar_container")
        self.sidebar.setFixedWidth(188)
        
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 18, 0, 14)
        sidebar_layout.setSpacing(4)
        
        # Sidebar branding
        brand_layout = QHBoxLayout()
        brand_layout.setContentsMargins(16, 0, 16, 14)
        self.brand_layout = brand_layout
        
        self.brand_icon = QLabel(self.sidebar)
        logo_path = os.path.join(DESKTOP_DIR, "netops_logo.png")
        if os.path.exists(logo_path):
            logo = QPixmap(logo_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.brand_icon.setPixmap(logo)
        self.brand_icon.setFixedSize(26, 26)
        self.brand_icon.setAlignment(Qt.AlignCenter)
            
        brand_text_vbox = QVBoxLayout()
        self.lbl_sidebar_title = QLabel("NetOps Agent", self.sidebar)
        self.lbl_sidebar_title.setObjectName("lbl_sidebar_title")
        self.lbl_sidebar_ver = QLabel("Enterprise Edition", self.sidebar)
        self.lbl_sidebar_ver.setObjectName("lbl_sidebar_ver")
        
        brand_text_vbox.addWidget(self.lbl_sidebar_title)
        brand_text_vbox.addWidget(self.lbl_sidebar_ver)
        brand_layout.addWidget(self.brand_icon)
        brand_layout.addLayout(brand_text_vbox)
        sidebar_layout.addLayout(brand_layout)
        
        # Sidebar Navigation buttons
        self.nav_group = []
        self.nav_labels = {}
        self.nav_icons = {}
        self.nav_layouts = []
        self.nav_items = [
            ("Dashboard", "nav_dashboard", "dashboard"),
            ("Service", "nav_service", "service"),
            ("Logs", "nav_logs", "logs"),
            ("Settings", "nav_settings", "settings"),
            ("About", "nav_about", "about")
        ]
        
        for name, key, icon_key in self.nav_items:
            btn = QPushButton(self.sidebar)
            btn.setObjectName("nav_btn_" + name.lower())
            btn.setProperty("class", "nav_btn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.setAccessibleName(TRANSLATIONS[self.lang][key])
            btn.setToolTip(TRANSLATIONS[self.lang][key])
            btn.clicked.connect(self.on_nav_clicked)
            
            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(16, 0, 16, 0)
            btn_layout.setSpacing(12)
            
            lbl_icon = QLabel(btn)
            lbl_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
            lbl_icon.setFixedSize(18, 18)
            lbl_icon.setAlignment(Qt.AlignCenter)
                
            lbl_text = QLabel(btn)
            lbl_text.setAttribute(Qt.WA_TransparentForMouseEvents)
            lbl_text.setProperty("role", "nav_text")
            
            btn_layout.addWidget(lbl_icon)
            btn_layout.addWidget(lbl_text)
            btn_layout.addStretch()
            
            sidebar_layout.addWidget(btn)
            self.nav_group.append(btn)
            self.nav_layouts.append(btn_layout)
            self.nav_labels[key] = lbl_text
            self.nav_icons[key] = lbl_icon
            
        self.nav_group[0].setChecked(True)
        sidebar_layout.addStretch()

        self.lbl_sidebar_status = QLabel(self.sidebar)
        self.lbl_sidebar_status.setObjectName("sidebar_status")
        self.lbl_sidebar_status.setText("●  未连接")
        self.lbl_sidebar_status.setAccessibleName("平台连接状态")
        self.lbl_sidebar_build = QLabel(f"v{CLIENT_VERSION}", self.sidebar)
        self.lbl_sidebar_build.setObjectName("sidebar_build")
        sidebar_layout.addWidget(self.lbl_sidebar_status)
        sidebar_layout.addWidget(self.lbl_sidebar_build)
        
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
        self._refresh_nav_styles()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sidebar"):
            self._set_sidebar_collapsed(self.width() < 1040)

    def _set_sidebar_collapsed(self, collapsed):
        if collapsed == self._sidebar_collapsed:
            return
        self._sidebar_collapsed = collapsed
        self.sidebar.setFixedWidth(64 if collapsed else 188)
        self.brand_layout.setContentsMargins(19 if collapsed else 16, 0, 16, 14)
        self.lbl_sidebar_title.setVisible(not collapsed)
        self.lbl_sidebar_ver.setVisible(not collapsed)
        self.lbl_sidebar_status.setVisible(not collapsed)
        self.lbl_sidebar_build.setVisible(not collapsed)
        for index, label in enumerate(self.nav_labels.values()):
            label.setVisible(not collapsed)
            self.nav_layouts[index].setContentsMargins(
                13 if collapsed else 16,
                0,
                0 if collapsed else 16,
                0,
            )

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
        self._refresh_nav_styles()

    def _refresh_nav_styles(self):
        """显式管理导航文字/图标颜色：未选中=中性灰，选中=主题青。

        不依赖 QSS 后代 `:checked QLabel` 级联（在部分 Qt 构建上不稳定），
        保证「灰 → 青 + pill 背景」的层级在明/暗主题下都确定生效。
        """
        tokens = theme_tokens(self.dark_mode)
        active = tokens["text_primary"]
        inactive = tokens["text_muted"]
        for i, btn in enumerate(self.nav_group):
            key = self.nav_items[i][1]
            color = active if btn.isChecked() else inactive
            lbl = self.nav_labels.get(key)
            if lbl:
                lbl.setStyleSheet(
                    f"background: transparent; border: none; font-weight: 600; "
                    f"font-size: 12px; color: {color};"
                )
            icon = self.nav_icons.get(key)
            if icon:
                icon.setPixmap(create_nav_icon(self.nav_items[i][2], color))

    # PAGE 1: Dashboard
    def init_dashboard_page(self):
        page = QWidget(self)
        page.setObjectName("dashboard_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        
        # Title Greeting Banner
        greeting_layout = QVBoxLayout()
        self.lbl_greet_title = QLabel("NetOps Agent Enterprise", self)
        self.lbl_greet_title.setObjectName("page_title")
        self.lbl_greet_desc = QLabel(f"Version v{CLIENT_VERSION} | License: Enterprise Commercial", self)
        self.lbl_greet_desc.setObjectName("page_description")
        greeting_layout.addWidget(self.lbl_greet_title)
        greeting_layout.addWidget(self.lbl_greet_desc)
        layout.addLayout(greeting_layout)
        
        # Middle Cards Layout (Service Status & Platform Connection)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)
        
        # Card 1: Service Status
        self.card_status = QFrame(self)
        self.card_status.setProperty("class", "card")
        self.card_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_status_layout = QVBoxLayout(self.card_status)
        card_status_layout.setContentsMargins(18, 16, 18, 16)
        card_status_layout.setSpacing(8)
        
        self.lbl_card_status_title = QLabel("服务状态 (Service Status)", self)
        self.lbl_card_status_title.setObjectName("lbl_card_title")
        self.lbl_status_large = QLabel("STOPPED", self)
        self.lbl_status_large.setObjectName("lbl_status_large")
        self.lbl_status_large.setProperty("tone", "error")
        
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
        self.card_conn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_conn_layout = QVBoxLayout(self.card_conn)
        card_conn_layout.setContentsMargins(18, 16, 18, 16)
        card_conn_layout.setSpacing(8)
        
        self.lbl_card_conn_title = QLabel("平台连接状态 (Platform Connection)", self)
        self.lbl_card_conn_title.setObjectName("lbl_card_title")
        self.lbl_conn_large = QLabel("DISCONNECTED", self)
        self.lbl_conn_large.setObjectName("lbl_status_large")
        self.lbl_conn_large.setProperty("tone", "error")
        
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
        conn_grid.setRowMinimumHeight(2, 28)
        card_conn_layout.addLayout(conn_grid)
        cards_layout.addWidget(self.card_conn)
        
        layout.addLayout(cards_layout)
        
        # Bottom: Diagnostics Card
        self.card_diag = QFrame(self)
        self.card_diag.setProperty("class", "card")
        self.card_diag.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        card_diag_layout = QVBoxLayout(self.card_diag)
        card_diag_layout.setContentsMargins(18, 16, 18, 16)
        card_diag_layout.setSpacing(10)
        
        self.lbl_diag_title = QLabel("一键诊断 (Run Diagnostics)", self)
        self.lbl_diag_title.setObjectName("lbl_card_title")
        card_diag_layout.addWidget(self.lbl_diag_title)
        
        diag_desc_hbox = QHBoxLayout()
        self.lbl_diag_desc = QLabel("对本地 Agent 的运行状态、控制器连接性、DNS、NTP 及磁盘空间进行完整性检测。", self)
        self.lbl_diag_desc.setObjectName("page_description")
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
        self.txt_diagnose_log.setFixedHeight(112)
        card_diag_layout.addWidget(self.txt_diagnose_log)
        
        layout.addWidget(self.card_diag)

        self.card_events = QFrame(self)
        self.card_events.setProperty("class", "card")
        self.card_events.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        events_layout = QVBoxLayout(self.card_events)
        events_layout.setContentsMargins(18, 14, 18, 14)
        events_layout.setSpacing(8)
        self.lbl_recent_title = QLabel(self)
        self.lbl_recent_title.setObjectName("lbl_card_title")
        self.lbl_recent_events = QLabel(self)
        self.lbl_recent_events.setObjectName("recent_events")
        self.lbl_recent_events.setWordWrap(True)
        events_layout.addWidget(self.lbl_recent_title)
        events_layout.addWidget(self.lbl_recent_events)
        layout.addWidget(self.card_events)
        layout.addStretch()
        self.content_pane.addWidget(page)

    # PAGE 2: Service controls & paths
    def init_service_page(self):
        page = QWidget(self)
        page.setObjectName("service_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        self.lbl_service_page_title, self.lbl_service_page_desc = self._add_page_header(
            layout, "服务管理", "启动或停止本地服务，并查看运行路径"
        )
        
        # 1. Lifecycle Panel
        card_ctrl = QFrame(self)
        card_ctrl.setProperty("class", "card")
        card_ctrl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        ctrl_layout = QVBoxLayout(card_ctrl)
        ctrl_layout.setContentsMargins(20, 16, 20, 16)
        ctrl_layout.setSpacing(12)
        
        self.lbl_service_ctrl_title = QLabel("服务生命周期控制 (Service Controls)", self)
        self.lbl_service_ctrl_title.setObjectName("lbl_card_title")
        ctrl_layout.addWidget(self.lbl_service_ctrl_title)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        
        self.btn_start = QPushButton("启动服务", self)
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_backend_server)
        
        self.btn_stop = QPushButton("停止服务", self)
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.clicked.connect(self.stop_backend_server)
        
        self.btn_restart = QPushButton("重启服务", self)
        self.btn_restart.setObjectName("btn_restart")
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
        card_meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
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
            ("meta_addr", "0.0.0.0:5010"),
            ("meta_port", "5010"),
            ("meta_dir", PROJECT_ROOT),
            ("meta_cfg", os.path.join(DESKTOP_DIR, "desktop_settings.ini")),
            ("meta_log", os.path.join(PROJECT_ROOT, "backend_server.log"))
        ]
        
        self.meta_labels = {}
        self.meta_copy_buttons = {}
        for row, (key, value) in enumerate(self.meta_fields):
            lbl_name = QLabel(key, self)
            lbl_name.setObjectName("lbl_field_name")
            
            lbl_val = QLineEdit(value, self)
            lbl_val.setReadOnly(True)
            lbl_val.setFocusPolicy(Qt.ClickFocus)
            lbl_val.setObjectName("metadata_value")
            
            btn_copy = QPushButton(self)
            btn_copy.setObjectName("btn_copy")
            btn_copy.setCursor(Qt.PointingHandCursor)
            btn_copy.clicked.connect(lambda checked=False, v=value, b=btn_copy: self.copy_to_clipboard(v, b))
            
            meta_grid.addWidget(lbl_name, row, 0)
            meta_grid.addWidget(lbl_val, row, 1, 1, 3)
            meta_grid.addWidget(btn_copy, row, 4, Qt.AlignRight)
            self.meta_labels[key] = lbl_name
            self.meta_copy_buttons[key] = btn_copy
            
        meta_layout.addLayout(meta_grid)
        layout.addWidget(card_meta)
        layout.addStretch()
        
        self.content_pane.addWidget(page)

    def copy_to_clipboard(self, val, button):
        QApplication.clipboard().setText(val)
        tr = TRANSLATIONS[self.lang]
        button.setText(tr["btn_copied"])
        button.setEnabled(False)
        show_toast(
            self,
            "已复制到剪贴板" if self.lang == "zh" else "Copied to clipboard",
            dark=self.dark_mode,
            level="success",
        )
        QTimer.singleShot(1500, lambda: [button.setText(tr["btn_copy"]), button.setEnabled(True)])

    # PAGE 3: Logs Streamer
    def init_logs_page(self):
        page = QWidget(self)
        page.setObjectName("logs_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)

        self.lbl_logs_page_title, self.lbl_logs_page_desc = self._add_page_header(
            layout, "实时日志", "筛选、暂停和导出本地运行日志"
        )
        
        # Upper Filters
        filters_frame = QFrame(self)
        filters_frame.setObjectName("toolbar_surface")
        filters_hbox = QHBoxLayout(filters_frame)
        filters_hbox.setContentsMargins(10, 8, 10, 8)
        filters_hbox.setSpacing(10)
        
        self.lbl_log_source = QLabel("日志源:", self)
        self.lbl_log_source.setObjectName("lbl_field_name")
        
        self.combo_log_source = QComboBox(self)
        self.combo_log_source.setView(QListView())
        self.combo_log_source.addItems(["FastAPI Server (backend_server.log)", "Tray Agent (desktop_tray.log)"])
        self.combo_log_source.currentIndexChanged.connect(self.on_log_source_changed)
        
        self.txt_log_search = QLineEdit(self)
        self.txt_log_search.setObjectName("txt_log_search")
        self.txt_log_search.textChanged.connect(self.trigger_log_filter)
        
        self.chk_pause_scroll = ToggleSwitch(self, dark=self.dark_mode)
        self.toggle_switches.append(self.chk_pause_scroll)
        self.lbl_pause_scroll = QLabel("暂停滚动", self)
        self.lbl_pause_scroll.setObjectName("pause_label")
        self.lbl_pause_scroll.setCursor(Qt.PointingHandCursor)
        # 点击文字也能切换开关
        self.lbl_pause_scroll.mousePressEvent = lambda _e: self.chk_pause_scroll.toggle()

        pause_widget = QWidget(self)
        pause_layout = QHBoxLayout(pause_widget)
        pause_layout.setContentsMargins(0, 0, 0, 0)
        pause_layout.setSpacing(8)
        pause_layout.addWidget(self.chk_pause_scroll)
        pause_layout.addWidget(self.lbl_pause_scroll)
        
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
        filters_hbox.addWidget(pause_widget)
        filters_hbox.addWidget(self.btn_clear_logs)
        filters_hbox.addWidget(self.btn_export_logs)
        layout.addWidget(filters_frame)
        
        # Real-time log monitor viewport
        self.txt_logs_terminal = QPlainTextEdit(self)
        self.txt_logs_terminal.setObjectName("log_viewer")
        self.txt_logs_terminal.setReadOnly(True)
        self.txt_logs_terminal.setMaximumBlockCount(2000)
        layout.addWidget(self.txt_logs_terminal)

        self.lbl_log_status = QLabel(self)
        self.lbl_log_status.setObjectName("log_status")
        self.lbl_log_status.setText("等待日志数据" if self.lang == "zh" else "Waiting for log data")
        layout.addWidget(self.lbl_log_status)
        
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
            self.lbl_log_status.setText(
                "日志文件不存在" if self.lang == "zh" else "Log file not found"
            )
            return
            
        try:
            current_size = os.path.getsize(log_path)
            modified_time = datetime.fromtimestamp(os.path.getmtime(log_path)).strftime("%H:%M:%S")
            size_text = (
                f"{current_size / 1024:.1f} KB"
                if current_size < 1024 * 1024
                else f"{current_size / (1024 * 1024):.1f} MB"
            )
            visible_lines = max(0, self.txt_logs_terminal.blockCount() - 1)
            self.lbl_log_status.setText(
                f"显示 {visible_lines} 行 · {size_text} · 更新于 {modified_time}"
                if self.lang == "zh"
                else f"{visible_lines} visible lines · {size_text} · Updated {modified_time}"
            )
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
            show_toast(
                self,
                "当前日志文件不存在或为空。" if self.lang == "zh" else "The selected log file is missing or empty.",
                dark=self.dark_mode,
                level="warning",
            )
            return
            
        dest_path, _ = QFileDialog.getSaveFileName(self, "Export Log File", "", "Log Files (*.log);;Text Files (*.txt)")
        if dest_path:
            try:
                shutil.copy(log_path, dest_path)
                show_toast(
                    self,
                    f"日志已导出到：{dest_path}" if self.lang == "zh" else f"Log exported to: {dest_path}",
                    dark=self.dark_mode,
                    level="success",
                )
            except Exception as e:
                show_message(
                    self,
                    "导出失败" if self.lang == "zh" else "Export Failed",
                    str(e),
                    dark=self.dark_mode,
                )

    def create_setting_row(self, key, control, is_last=False):
        row = QWidget()
        row.setObjectName("setting_row_" + key)
        row.setProperty("class", "setting_row_widget")
        row.setMinimumHeight(54)
        
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(12)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        lbl_title = QLabel(row)
        lbl_title.setObjectName("lbl_setting_title_" + key)
        lbl_title.setProperty("role", "setting_title")
        
        lbl_desc = QLabel(row)
        lbl_desc.setObjectName("lbl_setting_desc_" + key)
        lbl_desc.setProperty("role", "setting_description")
        lbl_desc.setWordWrap(True)
        
        text_layout.addWidget(lbl_title)
        text_layout.addWidget(lbl_desc)
        
        row_layout.addLayout(text_layout, 1)
        row_layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        
        if not hasattr(self, "settings_ui_elements"):
            self.settings_ui_elements = {}
        self.settings_ui_elements[key] = (lbl_title, lbl_desc)
        
        return row

    def create_spec_row(self, key, widget, expand_value=False):
        row = QWidget()
        row.setObjectName("spec_row_" + key)
        row.setProperty("class", "setting_row_widget")
        
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(12)
        
        lbl_name = QLabel(row)
        lbl_name.setObjectName("lbl_spec_name_" + key)
        lbl_name.setProperty("role", "spec_name")
        lbl_name.setMinimumWidth(180)
        
        row_layout.addWidget(lbl_name, 0, Qt.AlignLeft | Qt.AlignVCenter)
        if expand_value:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            row.setMinimumHeight(56)
            row_layout.addWidget(widget, 1)
        else:
            row_layout.addWidget(widget, 1, Qt.AlignRight | Qt.AlignVCenter)
        
        if not hasattr(self, "spec_ui_elements"):
            self.spec_ui_elements = {}
        self.spec_ui_elements[key] = lbl_name
        
        return row

    def copy_ip_to_clipboard(self):
        ip = self.combo_ips.currentText()
        if ip:
            QApplication.clipboard().setText(ip)
            tr = TRANSLATIONS[self.lang]
            self.btn_copy_ip.setText(tr["sys_ip_copied"])
            self.btn_copy_ip.setEnabled(False)
            show_toast(
                self,
                f"已复制网络地址：{ip}" if self.lang == "zh" else f"Copied network address: {ip}",
                dark=self.dark_mode,
                level="success",
            )
            QTimer.singleShot(1500, lambda: [self.btn_copy_ip.setText(tr["sys_ip_copy"]), self.btn_copy_ip.setEnabled(True)])

    def sync_local_ip_to_controller(self, selected_ip):
        selected_ip = selected_ip.strip()
        if selected_ip:
            self.combo_controller_ip.setCurrentText(selected_ip)
            self.on_controller_ip_changed(selected_ip)

    # PAGE 4: Settings & System info
    def init_settings_page(self):
        page = QWidget(self)
        page.setObjectName("settings_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(18)

        header = QWidget(page)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(4)
        self.lbl_settings_page_title = QLabel(header)
        self.lbl_settings_page_title.setObjectName("page_title")
        self.lbl_settings_page_desc = QLabel(header)
        self.lbl_settings_page_desc.setObjectName("page_description")
        header_text_layout.addWidget(self.lbl_settings_page_title)
        header_text_layout.addWidget(self.lbl_settings_page_desc)
        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()
        self.lbl_settings_saved = QLabel(header)
        self.lbl_settings_saved.setObjectName("settings_saved")
        self.lbl_settings_saved.hide()
        header_layout.addWidget(self.lbl_settings_saved, 0, Qt.AlignTop)
        layout.addWidget(header)
        
        # Left Scroll Area for Preferences
        scroll_prefs = QScrollArea(page)
        scroll_prefs.setObjectName("settings_scroll")
        scroll_prefs.setWidgetResizable(True)
        scroll_prefs.setFrameShape(QFrame.NoFrame)
        scroll_prefs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_prefs.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        scroll_prefs.viewport().setObjectName("settings_scroll_viewport")

        scroll_content = QWidget(scroll_prefs)
        scroll_content.setObjectName("settings_scroll_content")
        scroll_content.setMaximumWidth(900)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(16)
        
        # Prefs Card 1: General Options
        card_prefs = QFrame(scroll_content)
        card_prefs.setObjectName("settings_section")
        prefs_layout = QVBoxLayout(card_prefs)
        prefs_layout.setContentsMargins(8, 12, 8, 12)
        prefs_layout.setSpacing(0)
        
        self.lbl_settings_card_title = QLabel(card_prefs)
        self.lbl_settings_card_title.setObjectName("lbl_card_title")
        prefs_layout.addWidget(self.lbl_settings_card_title)
        
        self.settings_ui_elements = {}

        self.chk_boot_start = ToggleSwitch(card_prefs, dark=self.dark_mode)
        self.chk_boot_start.setChecked(self.boot_start)
        self.chk_boot_start.stateChanged.connect(self.save_settings)
        self.toggle_switches.append(self.chk_boot_start)
        prefs_layout.addWidget(self.create_setting_row("boot", self.chk_boot_start))
        
        self.chk_auto_start = ToggleSwitch(card_prefs, dark=self.dark_mode)
        self.chk_auto_start.setChecked(self.auto_start_service)
        self.chk_auto_start.stateChanged.connect(self.save_settings)
        self.toggle_switches.append(self.chk_auto_start)
        prefs_layout.addWidget(self.create_setting_row("service", self.chk_auto_start))
        
        self.chk_minimize_close = ToggleSwitch(card_prefs, dark=self.dark_mode)
        self.chk_minimize_close.setChecked(self.minimize_to_tray)
        self.chk_minimize_close.stateChanged.connect(self.save_settings)
        self.toggle_switches.append(self.chk_minimize_close)
        prefs_layout.addWidget(self.create_setting_row("minimize", self.chk_minimize_close))
        
        self.chk_auto_update = ToggleSwitch(card_prefs, dark=self.dark_mode)
        self.chk_auto_update.setChecked(self.auto_updates)
        self.chk_auto_update.stateChanged.connect(self.save_settings)
        self.toggle_switches.append(self.chk_auto_update)
        prefs_layout.addWidget(self.create_setting_row("update", self.chk_auto_update))
        
        self.chk_open_browser = ToggleSwitch(card_prefs, dark=self.dark_mode)
        self.chk_open_browser.setChecked(self.auto_open_browser)
        self.chk_open_browser.stateChanged.connect(self.save_settings)
        self.toggle_switches.append(self.chk_open_browser)
        prefs_layout.addWidget(self.create_setting_row("open_browser", self.chk_open_browser))

        scroll_layout.addWidget(card_prefs)

        card_appearance = QFrame(scroll_content)
        card_appearance.setObjectName("settings_section")
        appearance_layout = QVBoxLayout(card_appearance)
        appearance_layout.setContentsMargins(8, 12, 8, 12)
        appearance_layout.setSpacing(0)

        self.lbl_settings_appearance_title = QLabel(card_appearance)
        self.lbl_settings_appearance_title.setObjectName("lbl_card_title")
        appearance_layout.addWidget(self.lbl_settings_appearance_title)
        
        self.combo_lang_settings = QComboBox(card_appearance)
        self.combo_lang_settings.setView(QListView())
        self.combo_lang_settings.addItems(["中文", "English"])
        self.combo_lang_settings.setCurrentIndex(0 if self.lang == "zh" else 1)
        self.combo_lang_settings.currentIndexChanged.connect(self.on_lang_settings_changed)
        self.combo_lang_settings.setFixedWidth(156)
        appearance_layout.addWidget(self.create_setting_row("lang", self.combo_lang_settings))
        
        self.combo_theme = QComboBox(card_appearance)
        self.combo_theme.setView(QListView())
        self.combo_theme.addItems(["深色" if self.lang == "zh" else "Dark", "明亮" if self.lang == "zh" else "Light"])
        self.combo_theme.setCurrentIndex(0 if self.dark_mode else 1)
        self.combo_theme.currentIndexChanged.connect(self.on_theme_settings_changed)
        self.combo_theme.setFixedWidth(156)
        appearance_layout.addWidget(self.create_setting_row("theme", self.combo_theme))

        scroll_layout.addWidget(card_appearance)

        card_connection = QFrame(scroll_content)
        card_connection.setObjectName("settings_section")
        connection_layout = QVBoxLayout(card_connection)
        connection_layout.setContentsMargins(8, 12, 8, 12)
        connection_layout.setSpacing(0)

        self.lbl_settings_connection_title = QLabel(card_connection)
        self.lbl_settings_connection_title.setObjectName("lbl_card_title")
        connection_layout.addWidget(self.lbl_settings_connection_title)
        
        # 控制器 IP：可编辑下拉(本机非环回 IP) + 实时校验 + 连通性测试 + 状态点
        ip_ctrl_widget = QWidget(card_connection)
        ip_ctrl_layout = QHBoxLayout(ip_ctrl_widget)
        ip_ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ip_ctrl_layout.setSpacing(6)

        self.lbl_ip_status_dot = QLabel(ip_ctrl_widget)
        self.lbl_ip_status_dot.setObjectName("status_dot")
        self.lbl_ip_status_dot.setFixedSize(10, 10)
        self.lbl_ip_status_dot.setProperty("tone", "neutral")

        self.combo_controller_ip = QComboBox(ip_ctrl_widget)
        self.combo_controller_ip.setEditable(True)
        self.combo_controller_ip.setView(QListView())
        self.combo_controller_ip.setFixedWidth(132)
        self.combo_controller_ip.addItems(self._get_non_loopback_ips())
        # 先回填当前值，再连接信号，避免初始化期间触发多余保存
        if self.controller_ip:
            self.combo_controller_ip.setCurrentText(self.controller_ip)
        self.combo_controller_ip.currentTextChanged.connect(self.on_controller_ip_changed)

        self.btn_test_controller = QPushButton(ip_ctrl_widget)
        self.btn_test_controller.setObjectName("btn_secondary")
        self.btn_test_controller.setCursor(Qt.PointingHandCursor)
        self.btn_test_controller.clicked.connect(self.test_controller_connectivity)
        self.btn_test_controller.setFixedHeight(30)

        ip_ctrl_layout.addWidget(self.lbl_ip_status_dot, 0, Qt.AlignVCenter)
        ip_ctrl_layout.addWidget(self.combo_controller_ip)
        ip_ctrl_layout.addWidget(self.btn_test_controller)

        connection_layout.addWidget(self.create_setting_row("ip", ip_ctrl_widget))
        # 初始化一次校验状态
        self._validate_controller_ip(self.controller_ip)
        
        scroll_layout.addWidget(card_connection)
        
        # Prefs Card 2: Advanced Maintenance Options
        card_adv = QFrame(scroll_content)
        card_adv.setObjectName("settings_section")
        adv_layout = QVBoxLayout(card_adv)
        adv_layout.setContentsMargins(8, 12, 8, 12)
        adv_layout.setSpacing(0)
        
        self.lbl_settings_adv_title = QLabel(card_adv)
        self.lbl_settings_adv_title.setObjectName("lbl_card_title")
        adv_layout.addWidget(self.lbl_settings_adv_title)
        
        self.btn_reconfig_db = QPushButton(card_adv)
        self.btn_reconfig_db.setObjectName("btn_secondary")
        self.btn_reconfig_db.setCursor(Qt.PointingHandCursor)
        self.btn_reconfig_db.clicked.connect(lambda: self.launch_reconfig_wizard(True))
        self.btn_reconfig_db.setFixedWidth(100)
        adv_layout.addWidget(self.create_setting_row("reconfig", self.btn_reconfig_db))
        
        self.btn_reset_config = QPushButton(card_adv)
        self.btn_reset_config.setObjectName("btn_secondary")
        self.btn_reset_config.setCursor(Qt.PointingHandCursor)
        self.btn_reset_config.clicked.connect(self.reset_initial_config)
        self.btn_reset_config.setFixedWidth(100)
        adv_layout.addWidget(self.create_setting_row("reset", self.btn_reset_config))
        
        self.btn_clear_db = QPushButton(card_adv)
        self.btn_clear_db.setObjectName("btn_danger")
        self.btn_clear_db.setCursor(Qt.PointingHandCursor)
        self.btn_clear_db.clicked.connect(self.clear_and_reset_database)
        self.btn_clear_db.setFixedWidth(100)
        adv_layout.addWidget(self.create_setting_row("clear", self.btn_clear_db))
        
        scroll_layout.addWidget(card_adv)
        
        card_sys = QFrame(scroll_content)
        card_sys.setObjectName("settings_section")
        sys_layout = QVBoxLayout(card_sys)
        sys_layout.setContentsMargins(8, 12, 8, 12)
        sys_layout.setSpacing(0)
        
        self.lbl_sys_card_title = QPushButton(card_sys)
        self.lbl_sys_card_title.setObjectName("section_toggle")
        self.lbl_sys_card_title.setCheckable(True)
        self.lbl_sys_card_title.setChecked(False)
        self.lbl_sys_card_title.setCursor(Qt.PointingHandCursor)
        self.lbl_sys_card_title.clicked.connect(self._toggle_system_info)
        sys_layout.addWidget(self.lbl_sys_card_title)

        self.sys_content = QWidget(card_sys)
        self.sys_content.setObjectName("system_info_content")
        sys_content_layout = QVBoxLayout(self.sys_content)
        sys_content_layout.setContentsMargins(0, 0, 0, 0)
        sys_content_layout.setSpacing(0)
        
        # Query specs
        hostname = socket.gethostname()
        os_info = f"{platform.system()} {platform.release()}"
        cpu_info = platform.processor() or "AMD/Intel Processor"
        mem_info = self.get_total_memory()
        ip_info = self.get_local_ip_addresses()
        
        self.spec_ui_elements = {}
        
        lbl_host_val = QLabel(hostname, card_sys)
        lbl_host_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_hostname", lbl_host_val))
        
        lbl_os_val = QLabel(os_info, card_sys)
        lbl_os_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_os", lbl_os_val))
        
        lbl_cpu_val = QLabel(cpu_info, card_sys)
        lbl_cpu_val.setObjectName("lbl_cpu_value")
        lbl_cpu_val.setWordWrap(True)
        lbl_cpu_val.setProperty("compact", True)
        lbl_cpu_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_cpu_value = lbl_cpu_val
        self.cpu_spec_row = self.create_spec_row("sys_cpu", lbl_cpu_val, expand_value=True)
        sys_content_layout.addWidget(self.cpu_spec_row)
        
        lbl_mem_val = QLabel(mem_info, card_sys)
        lbl_mem_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_mem", lbl_mem_val))
        
        # CPU Cores
        cores = os.cpu_count()
        cores_info = f"{cores} Cores" if cores else "Unknown"
        lbl_cores_val = QLabel(cores_info, card_sys)
        lbl_cores_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_cpu_cores", lbl_cores_val))

        # Disk space
        try:
            usage = shutil.disk_usage("C:\\")
            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            disk_info = f"C: {used_gb:.1f} GB / {total_gb:.1f} GB"
        except Exception:
            disk_info = "Unknown"
        lbl_disk_val = QLabel(disk_info, card_sys)
        lbl_disk_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_disk", lbl_disk_val))

        # MAC Address
        import uuid
        try:
            mac_int = uuid.getnode()
            mac_str = ':'.join(['{:02x}'.format((mac_int >> ele) & 0xff) for ele in range(0,8*6,8)][::-1]).upper()
        except Exception:
            mac_str = "Unknown"
        lbl_mac_val = QLabel(mac_str, card_sys)
        lbl_mac_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_mac", lbl_mac_val))

        # Python Version
        python_ver = f"Python {sys.version.split()[0]}"
        lbl_py_val = QLabel(python_ver, card_sys)
        lbl_py_val.setObjectName("lbl_field_val")
        sys_content_layout.addWidget(self.create_spec_row("sys_python", lbl_py_val))
        
        # IP Dropdown + Copy
        ip_widget = QWidget(card_sys)
        ip_row_layout = QHBoxLayout(ip_widget)
        ip_row_layout.setContentsMargins(0, 0, 0, 0)
        ip_row_layout.setSpacing(6)
        
        self.combo_ips = QComboBox(ip_widget)
        self.combo_ips.setView(QListView())
        self.combo_ips.setFixedWidth(130)
        ip_list = [ip.strip() for ip in ip_info.split(",") if ip.strip()]
        self.combo_ips.addItems(ip_list if ip_list else ["127.0.0.1"])
        self.combo_ips.currentTextChanged.connect(self.sync_local_ip_to_controller)
        
        self.btn_copy_ip = QPushButton(ip_widget)
        self.btn_copy_ip.setObjectName("btn_copy")
        self.btn_copy_ip.setCursor(Qt.PointingHandCursor)
        self.btn_copy_ip.clicked.connect(self.copy_ip_to_clipboard)
        
        ip_row_layout.addWidget(self.combo_ips)
        ip_row_layout.addWidget(self.btn_copy_ip)
        
        sys_content_layout.addWidget(self.create_spec_row("sys_ip", ip_widget))
        sys_layout.addWidget(self.sys_content)
        self.sys_content.setVisible(False)
        self._update_system_section_title()

        scroll_layout.insertWidget(3, card_sys)
        scroll_layout.addStretch()
        scroll_prefs.setWidget(scroll_content)
        layout.addWidget(scroll_prefs, 1)
        
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

    def _toggle_system_info(self, expanded):
        self.sys_content.setVisible(expanded)
        self._update_system_section_title()

    def _update_system_section_title(self):
        if not hasattr(self, "lbl_sys_card_title"):
            return
        tr = TRANSLATIONS[self.lang]
        arrow = "⌄" if self.lbl_sys_card_title.isChecked() else "›"
        self.lbl_sys_card_title.setText(f"{tr['sys_card_title']}  {arrow}")

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

    # ── 控制器 IP 校验与连通性测试 ──
    def _get_non_loopback_ips(self):
        """返回本机所有非环回 IP（去除 127.* 与 localhost）。"""
        raw = self.get_local_ip_addresses() or ""
        ips = []
        for ip in raw.split(","):
            ip = ip.strip()
            if not ip:
                continue
            if ip.startswith("127.") or ip.lower() == "localhost":
                continue
            if ip not in ips:
                ips.append(ip)
        return ips

    @staticmethod
    def _is_valid_host(text):
        """合法性校验：标准 IPv4 或合理的主机名 (含 localhost)。"""
        text = (text or "").strip()
        if not text:
            return False
        # IPv4：四段，每段 0-255，无多余前导零
        parts = text.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            ok = True
            for p in parts:
                if not (0 <= int(p) <= 255):
                    ok = False
                    break
                if len(p) > 1 and p[0] == "0":  # 拒绝 01 / 007 之类
                    ok = False
                    break
            if ok:
                return True
        # 主机名：字母/数字/连字符/点，整体不超过 253，且至少含一个字母
        import re as _re
        if len(text) <= 253 and _re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9\-\.]{0,251}[A-Za-z0-9])?", text):
            if any(c.isalpha() for c in text):
                return True
        return False

    def _validate_controller_ip(self, text):
        """根据校验结果更新下拉框边框、状态点与测试按钮可用性。返回是否合法。

        控制器 IP 不允许使用环回口 / localhost（按需求排除）。
        """
        text = (text or "").strip()
        is_loopback = text.startswith("127.") or text.lower() == "localhost"
        valid = self._is_valid_host(text) and not is_loopback
        self.combo_controller_ip.setProperty("invalid", not valid)
        self.combo_controller_ip.style().unpolish(self.combo_controller_ip)
        self.combo_controller_ip.style().polish(self.combo_controller_ip)
        if valid:
            # 中性状态点（未测试）
            self._set_widget_tone(self.lbl_ip_status_dot, "neutral")
            if hasattr(self, "btn_test_controller"):
                self.btn_test_controller.setEnabled(True)
        else:
            self._set_widget_tone(self.lbl_ip_status_dot, "error")
            if hasattr(self, "btn_test_controller"):
                self.btn_test_controller.setEnabled(False)
        return valid

    def on_controller_ip_changed(self, text):
        valid = self._validate_controller_ip(text)
        # 仅在合法时写入设置，避免把无效地址持久化
        if valid:
            self.save_settings()

    def test_controller_connectivity(self):
        ip = self.combo_controller_ip.currentText().strip()
        if not self._validate_controller_ip(ip):
            return
        tr = TRANSLATIONS[self.lang]
        self.btn_test_controller.setEnabled(False)
        self.btn_test_controller.setText(tr["btn_test_controller_testing"])
        self._set_widget_tone(self.lbl_ip_status_dot, "warning")

        def worker():
            ok = False
            for port in (5010, 443, 80, 22):
                if self.is_port_occupied_fast(ip, port):
                    ok = True
                    break
            self.controller_test_result_signal.emit(ok)

        threading.Thread(target=worker, daemon=True).start()

    def on_controller_test_result(self, success):
        tr = TRANSLATIONS[self.lang]
        self.btn_test_controller.setEnabled(True)
        self.btn_test_controller.setText(tr["btn_test_controller"])
        if success:
            self._set_widget_tone(self.lbl_ip_status_dot, "success")
        else:
            self._set_widget_tone(self.lbl_ip_status_dot, "error")
        show_toast(
            self,
            ("控制器连接测试成功。" if success else "控制器连接测试失败。")
            if self.lang == "zh"
            else ("Controller connection succeeded." if success else "Controller connection failed."),
            dark=self.dark_mode,
            level="success" if success else "error",
        )
        self._record_event(
            ("控制器连接测试成功" if success else "控制器连接测试失败")
            if self.lang == "zh"
            else ("Controller test succeeded" if success else "Controller test failed")
        )

    # PAGE 5: About us
    def init_about_page(self):
        page = QWidget(self)
        page.setObjectName("about_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        self.lbl_about_page_title, self.lbl_about_page_desc = self._add_page_header(
            layout, "关于 NetOps Agent", "版本信息、项目地址与技术支持"
        )
        
        card_about = QFrame(self)
        card_about.setProperty("class", "card")
        about_layout = QHBoxLayout(card_about)
        about_layout.setContentsMargins(22, 20, 22, 20)
        about_layout.setSpacing(24)
        
        # Left side: specs and details
        left_widget = QWidget(self)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        
        self.lbl_about_logo = QLabel(self)
        logo_path = os.path.join(DESKTOP_DIR, "netops_logo.png")
        if os.path.exists(logo_path):
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(logo_path)
            self.lbl_about_logo.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_about_logo.setText("📡")
            self.lbl_about_logo.setObjectName("about_logo_fallback")
        left_layout.addWidget(self.lbl_about_logo, 0, Qt.AlignLeft)
        
        self.lbl_about_name = QLabel("NetOps 智能自动化网络运维平台", self)
        self.lbl_about_name.setObjectName("about_name")
        left_layout.addWidget(self.lbl_about_name, 0, Qt.AlignLeft)
        
        self.lbl_about_desc = QLabel(self)
        self.lbl_about_desc.setObjectName("about_description")
        self.lbl_about_desc.setWordWrap(True)
        self.lbl_about_desc.setAlignment(Qt.AlignLeft)
        left_layout.addWidget(self.lbl_about_desc)
        
        divider = QFrame(self)
        divider.setObjectName("subtle_divider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Sunken)
        left_layout.addWidget(divider)
        
        details_grid = QGridLayout()
        details_grid.setSpacing(10)
        repo_url = "https://github.com/libing28390-sketch/Release-netops"
        
        self.lbl_about_ver_name = QLabel(self)
        self.lbl_about_ver_name.setObjectName("lbl_field_name")
        self.lbl_about_ver_val = QLabel(f"v{CLIENT_VERSION} Community Edition", self)
        self.lbl_about_ver_val.setObjectName("lbl_field_val")
        
        self.lbl_about_build_name = QLabel(self)
        self.lbl_about_build_name.setObjectName("lbl_field_name")
        self.lbl_about_build_val = QLabel(CLIENT_BUILD, self)
        self.lbl_about_build_val.setObjectName("lbl_field_val")
        
        self.lbl_about_site_name = QLabel(self)
        self.lbl_about_site_name.setObjectName("lbl_field_name")
        self.lbl_about_site_val = QPushButton(repo_url, self)
        self.lbl_about_site_val.setObjectName("link_button")
        self.lbl_about_site_val.setCursor(Qt.PointingHandCursor)
        self.lbl_about_site_val.clicked.connect(lambda: self.open_external_link(repo_url))
        
        self.lbl_about_support_name = QLabel(self)
        self.lbl_about_support_name.setObjectName("lbl_field_name")
        self.lbl_about_support_val = QPushButton(repo_url, self)
        self.lbl_about_support_val.setObjectName("link_button")
        self.lbl_about_support_val.setCursor(Qt.PointingHandCursor)
        self.lbl_about_support_val.clicked.connect(lambda: self.open_external_link(repo_url))
        
        self.lbl_about_wechat_name = QLabel(self)
        self.lbl_about_wechat_name.setObjectName("lbl_field_name")
        self.lbl_about_wechat_val = QLabel("小网工爱运维", self)
        self.lbl_about_wechat_val.setObjectName("lbl_field_val")
        self.lbl_about_wechat_val.setProperty("tone", "success")
        
        details_grid.addWidget(self.lbl_about_ver_name, 0, 0)
        details_grid.addWidget(self.lbl_about_ver_val, 0, 1)
        details_grid.addWidget(self.lbl_about_build_name, 1, 0)
        details_grid.addWidget(self.lbl_about_build_val, 1, 1)
        details_grid.addWidget(self.lbl_about_site_name, 2, 0)
        details_grid.addWidget(self.lbl_about_site_val, 2, 1)
        details_grid.addWidget(self.lbl_about_support_name, 3, 0)
        details_grid.addWidget(self.lbl_about_support_val, 3, 1)
        details_grid.addWidget(self.lbl_about_wechat_name, 4, 0)
        details_grid.addWidget(self.lbl_about_wechat_val, 4, 1)
        
        left_layout.addLayout(details_grid)

        self.btn_check_update = QPushButton(self)
        self.btn_check_update.setObjectName("btn_secondary")
        self.btn_check_update.setCursor(Qt.PointingHandCursor)
        self.btn_check_update.clicked.connect(self.check_for_updates)
        left_layout.addWidget(self.btn_check_update, 0, Qt.AlignLeft)

        self.lbl_update_status = QLabel(self)
        self.lbl_update_status.setObjectName("about_caption")
        self.lbl_update_status.setWordWrap(True)
        left_layout.addWidget(self.lbl_update_status)
        
        self.lbl_about_copyright = QLabel(self)
        self.lbl_about_copyright.setObjectName("about_caption")
        left_layout.addWidget(self.lbl_about_copyright)
        
        about_layout.addWidget(left_widget, 5)
        
        # Right side: WeChat QR Code card
        right_widget = QWidget(self)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 10, 0)
        right_layout.setSpacing(10)
        right_layout.setAlignment(Qt.AlignCenter)
        
        self.lbl_qr_code = QLabel(self)
        qr_path = os.path.join(DESKTOP_DIR, "公众号.jpg")
        if os.path.exists(qr_path):
            from PySide6.QtGui import QPixmap
            pixmap = QPixmap(qr_path)
            self.lbl_qr_code.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.lbl_qr_code.setObjectName("qr_code")
        else:
            self.lbl_qr_code.setText("[QR Code]")
            self.lbl_qr_code.setObjectName("about_caption")
            
        self.lbl_qr_desc = QLabel(self)
        self.lbl_qr_desc.setObjectName("about_caption")
        self.lbl_qr_desc.setAlignment(Qt.AlignCenter)
        
        right_layout.addWidget(self.lbl_qr_code, 0, Qt.AlignCenter)
        right_layout.addWidget(self.lbl_qr_desc, 0, Qt.AlignCenter)
        
        about_layout.addWidget(right_widget, 3)
        
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
        self.setStyleSheet(build_codex_stylesheet(self.dark_mode))
        
        for combo in [self.combo_lang_settings, self.combo_theme, self.combo_ips, self.combo_log_source, self.combo_controller_ip]:
            # Force using QStyledItemDelegate so custom item backgrounds and highlights are respected
            if not isinstance(combo.itemDelegate(), QStyledItemDelegate):
                combo.setItemDelegate(QStyledItemDelegate(combo))
                
        set_dark_title_bar(self.winId(), self.dark_mode)

        # 同步自绘开关的明/暗配色
        for toggle in getattr(self, "toggle_switches", []):
            toggle.apply_palette(self.dark_mode)

        # 同步导航文字/图标颜色（主题切换时）
        if hasattr(self, "nav_group"):
            self._refresh_nav_styles()

    def _add_page_header(self, layout, title, description):
        header = QVBoxLayout()
        header.setSpacing(3)
        title_label = QLabel(title, self)
        title_label.setObjectName("page_title")
        description_label = QLabel(description, self)
        description_label.setObjectName("page_description")
        header.addWidget(title_label)
        header.addWidget(description_label)
        layout.addLayout(header)
        return title_label, description_label

    @staticmethod
    def _set_widget_tone(widget, tone):
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def update_translations(self):
        tr = TRANSLATIONS[self.lang]
        self.lbl_sidebar_title.setText(tr["title"])
        self.lbl_sidebar_ver.setText(tr["subtitle"])
        
        # Navigation
        self.nav_labels["nav_dashboard"].setText(tr["nav_dashboard"])
        self.nav_labels["nav_service"].setText(tr["nav_service"])
        self.nav_labels["nav_logs"].setText(tr["nav_logs"])
        self.nav_labels["nav_settings"].setText(tr["nav_settings"])
        self.nav_labels["nav_about"].setText(tr["nav_about"])
        for index, (_, key, _) in enumerate(self.nav_items):
            label = tr[key]
            self.nav_group[index].setToolTip(label)
            self.nav_group[index].setAccessibleName(label)
        
        # Page 1: Dashboard
        self.lbl_greet_title.setText(tr["agent_title"])
        self.lbl_greet_desc.setText(tr["dashboard_page_desc"])
        self.lbl_card_status_title.setText(tr["status_card_title"])
        self.lbl_dash_pid_name.setText(tr["status_pid"])
        self.lbl_dash_uptime_name.setText(tr["status_uptime"])
        self.lbl_dash_port_name.setText(tr["status_port"])
        self.lbl_dash_health_name.setText(tr["status_health"])
        
        self.lbl_card_conn_title.setText(tr["conn_card_title"])
        self.lbl_dash_ctrl_name.setText(tr["conn_controller"])
        self.lbl_dash_sync_name.setText(tr["conn_sync"])
        
        self.lbl_diag_title.setText(tr["diag_card_title"])
        self.lbl_diag_desc.setText(tr["diag_desc"])
        self.btn_run_diagnose.setText(tr["diag_btn"])
        self.lbl_recent_title.setText(tr["recent_card_title"])
        if not self.recent_events:
            self.lbl_recent_events.setText(tr["recent_empty"])
        
        # Page 2: Service controls
        self.lbl_service_page_title.setText(tr["service_page_title"])
        self.lbl_service_page_desc.setText(tr["service_page_desc"])
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
        for key, btn in self.meta_copy_buttons.items():
            btn.setText(tr["btn_copy"])
        
        # Page 3: Logs
        self.lbl_logs_page_title.setText(tr["logs_page_title"])
        self.lbl_logs_page_desc.setText(tr["logs_page_desc"])
        self.lbl_log_source.setText(tr["log_select_label"])
        self.txt_log_search.setPlaceholderText(tr["log_search_placeholder"])
        self.lbl_pause_scroll.setText(tr["chk_pause_scroll"])
        self.btn_clear_logs.setText(tr["btn_clear"])
        self.btn_export_logs.setText(tr["btn_export"])
        
        # Page 4: Settings
        self.lbl_settings_page_title.setText(tr["settings_page_title"])
        self.lbl_settings_page_desc.setText(tr["settings_page_desc"])
        self.lbl_settings_card_title.setText(tr["settings_card_title"])
        self.lbl_settings_appearance_title.setText(tr["settings_appearance_title"])
        self.lbl_settings_connection_title.setText(tr["settings_connection_title"])
        self.lbl_settings_adv_title.setText(tr["settings_adv_title"])
        self._update_system_section_title()
        self.combo_lang_settings.setItemText(0, "中文")
        self.combo_lang_settings.setItemText(1, "English")
        self.combo_theme.setItemText(0, "深色" if self.lang == "zh" else "Dark")
        self.combo_theme.setItemText(1, "明亮" if self.lang == "zh" else "Light")
        if hasattr(self, "btn_test_controller"):
            # 保留"测试中"状态文案，避免切换语言时打断进行中的测试
            if self.btn_test_controller.isEnabled():
                self.btn_test_controller.setText(tr["btn_test_controller"])
        
        for key, (lbl_title, lbl_desc) in self.settings_ui_elements.items():
            lbl_title.setText(tr["setting_" + key + "_title"])
            lbl_desc.setText(tr["setting_" + key + "_desc"])
            
        self.btn_reconfig_db.setText(tr["btn_reconfig_db"])
        self.btn_reset_config.setText(tr["btn_reset_config"])
        self.btn_clear_db.setText(tr["btn_clear_db"])
        
        for key, lbl in self.spec_ui_elements.items():
            lbl.setText(tr[key])
            
        self.btn_copy_ip.setText(tr["sys_ip_copy"])
        
        # Page 5: About
        self.lbl_about_page_title.setText(tr["about_page_title"])
        self.lbl_about_page_desc.setText(tr["about_page_desc"])
        self.lbl_about_name.setText(tr["about_name"])
        self.lbl_about_desc.setText(tr["about_desc"])
        self.lbl_about_ver_name.setText("版本:" if self.lang == "zh" else "Version:")
        self.lbl_about_build_name.setText("构建编号:" if self.lang == "zh" else "Build Number:")
        self.lbl_about_site_name.setText("官方网站:" if self.lang == "zh" else "Official Website:")
        self.lbl_about_support_name.setText("技术支持:" if self.lang == "zh" else "Technical Support:")
        self.lbl_about_wechat_name.setText("微信公众号:" if self.lang == "zh" else "WeChat Account:")
        self.btn_check_update.setText(tr["about_check_updates"])
        if not self.update_check_worker or not self.update_check_worker.isRunning():
            self.lbl_update_status.setText("")
        self.lbl_qr_desc.setText("扫码关注微信公众号" if self.lang == "zh" else "Scan to Follow WeChat")
        self.lbl_about_copyright.setText("版权所有 © 2026 NetOps 社区。保留所有权利。" if self.lang == "zh" else "Copyright © 2026 NetOps Community. All rights reserved.")
        
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
        self.backend_starting = True
        self.btn_start.setText(TRANSLATIONS[self.lang]["btn_start_loading"])
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
                    "--host", "0.0.0.0",
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
                    if os.path.exists(backend_log_path) and os.path.getsize(backend_log_path) > 500 * 1024 * 1024:
                        rotate_log_file(backend_log_path, 10)
                except Exception as rot_err:
                    logger.error("Failed to rotate backend log: %s", rot_err)
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
                self._record_event(
                    "后台服务已启动" if self.lang == "zh" else "Backend service started"
                )
                show_toast(
                    self,
                    "后台服务正在启动。" if self.lang == "zh" else "Backend service is starting.",
                    dark=self.dark_mode,
                    level="success",
                )
                self.show_tray_notification(
                    TRANSLATIONS[self.lang]["notify_started"],
                    TRANSLATIONS[self.lang]["notify_title"]
                )
                self.browser_open_attempts = 0
                self.browser_timer = QTimer(self)
                self.browser_timer.timeout.connect(self.check_server_ready_and_open_browser)
                self.browser_timer.start(200) # Check every 200ms
            except Exception as e:
                logger.exception("Failed to start FastAPI server:")
                self.backend_starting = False
                show_toast(
                    self,
                    f"后台服务启动失败：{e}" if self.lang == "zh" else f"Backend start failed: {e}",
                    dark=self.dark_mode,
                    level="error",
                    duration=4200,
                )
                self._record_event(
                    "后台服务启动失败" if self.lang == "zh" else "Backend start failed"
                )
                
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
                self._record_event(
                    "后台服务已停止" if self.lang == "zh" else "Backend service stopped"
                )
                show_toast(
                    self,
                    "后台服务已停止。" if self.lang == "zh" else "Backend service stopped.",
                    dark=self.dark_mode,
                    level="success",
                )
                self.show_tray_notification(
                    TRANSLATIONS[self.lang]["notify_stopped"],
                    TRANSLATIONS[self.lang]["notify_title"]
                )
            except Exception as e:
                logger.exception("Failed to stop backend server:")
                show_toast(
                    self,
                    f"后台服务停止失败：{e}" if self.lang == "zh" else f"Backend stop failed: {e}",
                    dark=self.dark_mode,
                    level="error",
                    duration=4200,
                )
                self._record_event(
                    "后台服务停止失败" if self.lang == "zh" else "Backend stop failed"
                )
                
        self.update_runtime_state()

    def restart_backend_server(self):
        self.stop_backend_server()
        QTimer.singleShot(1000, self.start_backend_server)

    def check_server_ready_and_open_browser(self):
        self.browser_open_attempts += 1
        if self.is_port_occupied_fast("127.0.0.1", 5010):
            self.browser_timer.stop()
            if getattr(self, "auto_open_browser", True):
                self.open_console_browser()
        elif self.browser_open_attempts >= 50:
            self.browser_timer.stop()
            logger.warning("Timeout waiting for backend server to start. Opening browser anyway.")
            if getattr(self, "auto_open_browser", True):
                self.open_console_browser()

    def open_console_browser(self):
        logger.info("Opening console browser: %s", APP_URL)
        self.open_external_link(APP_URL)

    def open_external_link(self, url):
        try:
            opened = webbrowser.open(url)
        except Exception as exc:
            logger.error("Failed to open external link %s: %s", url, exc)
            opened = False
        if not opened:
            show_toast(
                self,
                "无法打开默认浏览器。" if self.lang == "zh" else "Unable to open the default browser.",
                dark=self.dark_mode,
                level="error",
            )
        return opened

    # 1-second interval GUI state update (main thread)
    def update_runtime_state(self):
        active = self.is_backend_active()
        tr = TRANSLATIONS[self.lang]
        
        # 1. Update service cards
        if active:
            self.backend_starting = False
            self.lbl_status_large.setText(tr["status_running"])
            self._set_widget_tone(self.lbl_status_large, "success")
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
            self._set_widget_tone(self.lbl_dash_health_val, "success")
            
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)
            
            # Set dynamic green tray icon
            if hasattr(self, 'tray_icon'):
                self.tray_icon.setIcon(create_status_icon("green"))
        else:
            if getattr(self, "backend_starting", False):
                self.lbl_status_large.setText(tr["status_starting"])
                self._set_widget_tone(self.lbl_status_large, "warning")
                self.lbl_dash_pid_val.setText("-")
                self.lbl_dash_uptime_val.setText("0s")
                self.lbl_dash_health_val.setText(tr["health_unhealthy"])
                self._set_widget_tone(self.lbl_dash_health_val, "error")
                
                self.btn_start.setEnabled(False)
                self.btn_stop.setEnabled(True)
                self.btn_restart.setEnabled(False)
                
                # Set dynamic orange/yellow tray icon
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.setIcon(create_status_icon("yellow"))
            else:
                self.lbl_status_large.setText(tr["status_stopped"])
                self._set_widget_tone(self.lbl_status_large, "error")
                self.lbl_dash_pid_val.setText("-")
                self.lbl_dash_uptime_val.setText("0s")
                self.lbl_dash_health_val.setText(tr["health_unhealthy"])
                self._set_widget_tone(self.lbl_dash_health_val, "error")
                
                self.btn_start.setEnabled(True)
                self.btn_stop.setEnabled(False)
                self.btn_restart.setEnabled(False)
                
                # Set dynamic red tray icon
                if hasattr(self, 'tray_icon'):
                    self.tray_icon.setIcon(create_status_icon("red"))
                
        # 2. Update platform cards
        if self.controller_connected:
            self.lbl_conn_large.setText(tr["conn_connected"])
            self._set_widget_tone(self.lbl_conn_large, "success")
            self.lbl_sidebar_status.setText("●  已连接" if self.lang == "zh" else "●  Connected")
            self.lbl_sidebar_status.setProperty("connected", True)
        else:
            self.lbl_conn_large.setText(tr["conn_disconnected"])
            self._set_widget_tone(self.lbl_conn_large, "error")
            self.lbl_sidebar_status.setText("●  未连接" if self.lang == "zh" else "●  Disconnected")
            self.lbl_sidebar_status.setProperty("connected", False)

        self.lbl_sidebar_status.style().unpolish(self.lbl_sidebar_status)
        self.lbl_sidebar_status.style().polish(self.lbl_sidebar_status)
            
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
                cfg_path = os.path.join(DESKTOP_DIR, "desktop_settings.ini")
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
            self._record_event(
                "一键诊断已完成" if self.lang == "zh" else "Diagnostics completed"
            )
            show_toast(
                self,
                tr["diag_done"] % path_or_err,
                dark=self.dark_mode,
                level="success",
                duration=4200,
            )
        else:
            self._record_event(
                "一键诊断失败" if self.lang == "zh" else "Diagnostics failed"
            )
            show_message(
                self,
                tr["diag_card_title"],
                tr["diag_failed"] % path_or_err,
                dark=self.dark_mode,
            )

    def _record_event(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.recent_events.insert(0, f"{timestamp}  {message}")
        del self.recent_events[4:]
        if hasattr(self, "lbl_recent_events"):
            self.lbl_recent_events.setText("\n".join(self.recent_events))

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
    ico_path = os.path.join(DESKTOP_DIR, "netops.ico")
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
    QTimer.singleShot(350, window.show_release_notes_if_needed)
    sys.exit(app.exec())

if __name__ == '__main__':
    if sys.platform == 'win32':
        import multiprocessing
        multiprocessing.freeze_support()
    main()
