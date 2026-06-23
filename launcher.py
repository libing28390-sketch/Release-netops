# -*- coding: utf-8 -*-
"""
launcher.py - PySide6 NetOps Graphical Setup Initializer & Launcher.
Provides a premium dark-mode Qt GUI with a smooth progress bar to verify the Python environment,
self-heal/recreate virtual environments, install dependencies, compile frontend assets,
regenerate desktop shortcuts, and launch the PySide6 tray agent.
"""

import sys
import os
import time
import shutil
import threading
import subprocess
import ctypes

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))

LOG_FILE = os.path.join(PROJECT_ROOT, "launcher_setup.log")

# Setup logging
def log_message(message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"{timestamp} - {message}\n"
    try:
        sys.__stdout__.write(formatted)
        sys.__stdout__.flush()
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted)
    except Exception:
        pass

# Ensure standard streams are logged
class LogStreamRedirector:
    def __init__(self, prefix):
        self.prefix = prefix
    def write(self, text):
        if text.strip():
            log_message(f"[{self.prefix}] {text.strip()}")
    def flush(self):
        pass

sys.stdout = LogStreamRedirector("LAUNCHER-OUT")
sys.stderr = LogStreamRedirector("LAUNCHER-ERR")

# Try importing PySide6 defensively
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QLabel, QProgressBar, QFrame, QGraphicsDropShadowEffect, QMessageBox
    )
    from PySide6.QtCore import Qt, Signal, Slot, QObject, QTimer
    from PySide6.QtGui import QIcon, QFont, QColor
except ImportError as e:
    log_message(f"PySide6 not available in compiler environment. PySide6 will be installed: {e}")
    # Define fallback structures so it compiles under PyInstaller if run outside compiled app.
    # Note: PyInstaller bundle itself includes PySide6, so imports will always succeed when run by user.
    pass

# IMMERSIVE DARK MODE FOR WINDOWS 10/11
def set_dark_title_bar(window_handle):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window_handle)
        value = ctypes.c_int(1)
        # Attribute 20 controls immersive dark mode
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception as e:
        log_message(f"Failed to set dark title bar: {e}")

LAUNCHER_STYLE = """
QWidget {
    font-family: "Segoe UI", "Microsoft YaHei UI";
    color: #F8FAFC;
    font-size: 13px;
}
QMainWindow {
    background-color: #0B0F19;
}
QLabel#lbl_title {
    font-size: 16px;
    font-weight: bold;
    color: #F8FAFC;
}
QLabel#lbl_subtitle {
    font-size: 11px;
    color: #64748B;
}
QFrame#card {
    background-color: #111827;
    border: 1px solid #1F2937;
    border-radius: 12px;
}
QLabel#lbl_status {
    font-weight: bold;
    color: #2563EB;
    font-size: 13px;
}
QLabel#lbl_log {
    color: #94A3B8;
    font-size: 11px;
}
QProgressBar {
    background-color: #1F2937;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #2563EB;
    border-radius: 5px;
}
"""

class SetupWorker(QObject):
    progress_signal = Signal(str, str, float)
    error_signal = Signal(str)
    success_signal = Signal()

    def run_setup_tasks(self):
        log_message("Starting PySide6 launcher execution plan...")
        
        # Step 1: Check system Python
        self.progress_signal.emit("正在定位运行环境...", "检查系统 Python 状态...", 0.1)
        time.sleep(0.5)
        
        system_python = "python"
        has_python = False
        try:
            r = subprocess.run(
                [system_python, "--version"],
                capture_output=True,
                text=True,
                creationflags=0x08000000
            )
            if r.returncode == 0:
                has_python = True
        except (FileNotFoundError, Exception):
            pass

        if not has_python:
            log_message("System python not found. Starting automatic installer wizard...")
            self.progress_signal.emit("正在下载运行环境...", "正在下载 Python 3.11 安装包...", 0.12)
            try:
                import urllib.request
                import winreg
                py_installer_url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
                py_installer_path = os.path.join(PROJECT_ROOT, "python-installer.exe")
                urllib.request.urlretrieve(py_installer_url, py_installer_path)
                
                self.progress_signal.emit("正在安装运行环境...", "正在执行 Python 3.11 静默安装...", 0.18)
                r_inst = subprocess.run(
                    [py_installer_path, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0", "Include_doc=0"],
                    creationflags=0x08000000
                )
                try: os.remove(py_installer_path)
                except: pass
                
                if r_inst.returncode != 0:
                    raise Exception(f"Python installer exited with code {r_inst.returncode}")
                
                # Refresh PATH env
                new_path = ""
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                        new_path += winreg.QueryValueEx(key, "Path")[0] + ";"
                except Exception:
                    pass
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                        new_path += winreg.QueryValueEx(key, "Path")[0]
                except Exception:
                    pass
                if new_path:
                    os.environ["PATH"] = new_path
                    log_message("Python installed and environment PATH refreshed.")
            except Exception as py_err:
                self.error_signal.emit(f"自动安装 Python 失败！请前往官网手动安装 Python 3.10+ 并添加到 PATH。\n\n具体报错: {py_err}")
                return

        # Step 2: Verify or recreate Virtual Environment (.venv)
        self.progress_signal.emit("正在检查虚拟环境...", "验证 .venv 虚拟环境可用性...", 0.25)
        time.sleep(0.5)
        
        venv_path = os.path.join(PROJECT_ROOT, ".venv")
        venv_broken = False
        
        if os.path.exists(venv_path):
            log_message("Found existing .venv directory. Verifying integrity...")
            if not self.verify_venv(venv_path):
                log_message("Virtual environment is broken or was moved. Recreating...")
                venv_broken = True
                self.progress_signal.emit("正在重建虚拟环境...", "检测到旧环境失效，正在清理旧的 .venv 文件夹...", 0.35)
                try:
                    shutil.rmtree(venv_path)
                except Exception as e:
                    subprocess.run(f'rmdir /s /q "{venv_path}"', shell=True, creationflags=0x08000000)
                    if os.path.exists(venv_path):
                        self.error_signal.emit(f"无法清理旧的虚拟环境文件夹，请关闭占用此目录的程序后重试。原因: {e}")
                        return
        else:
            log_message("No .venv directory found. Creating new environment...")
            
        if not os.path.exists(venv_path) or venv_broken:
            self.progress_signal.emit("正在创建虚拟环境...", "执行 python -m venv .venv...", 0.45)
            try:
                r = subprocess.run(
                    [system_python, "-m", "venv", ".venv"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    creationflags=0x08000000
                )
                if r.returncode != 0:
                    raise Exception(r.stderr)
                log_message("Virtual environment created successfully.")
            except Exception as e:
                self.error_signal.emit(f"创建虚拟环境失败: {e}")
                return

        # Step 3: Install/Verify Python dependencies
        self.progress_signal.emit("正在安装后台依赖...", "升级 pip 并执行包下载安装...", 0.6)
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")
        
        packages_installed = True
        try:
            r = subprocess.run(
                [python_exe, "-c", "import PySide6, PIL, uvicorn, fastapi, sqlalchemy"],
                capture_output=True,
                creationflags=0x08000000
            )
            if r.returncode != 0:
                packages_installed = False
        except Exception:
            packages_installed = False
            
        if not packages_installed:
            log_message("Backend packages not fully installed. Installing now...")
            try:
                self.progress_signal.emit("正在升级 pip 工具...", "执行 pip upgrade...", 0.65)
                subprocess.run(
                    [python_exe, "-m", "pip", "install", "--upgrade", "pip"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    creationflags=0x08000000
                )
                
                self.progress_signal.emit("正在安装第三方依赖包...", "安装 pip requirements.txt 依赖...", 0.75)
                req_path = os.path.join(PROJECT_ROOT, "backend", "requirements.txt")
                if os.path.exists(req_path):
                    subprocess.run(
                        [pip_exe, "install", "-r", "backend/requirements.txt"],
                        cwd=PROJECT_ROOT,
                        capture_output=True,
                        creationflags=0x08000000
                    )
                        
                self.progress_signal.emit("正在配置客户端依赖...", "安装 PySide6 pillow...", 0.8)
                subprocess.run(
                    [pip_exe, "install", "PySide6", "pillow"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    creationflags=0x08000000
                )
                log_message("Python dependency installation completed successfully.")
            except Exception as e:
                self.error_signal.emit(f"安装依赖包失败: {e}")
                return
        else:
            log_message("All backend python dependencies are already satisfied.")

        # Step 4: Verify Frontend static files
        self.progress_signal.emit("正在配置前端界面...", "校验静态编译资源...", 0.85)
        dist_path = os.path.join(PROJECT_ROOT, "dist")
        if not os.path.exists(dist_path):
            log_message("No static directory 'dist' found. Attempting to build frontend...")
            
            npm_available = False
            npm_cmd = "npm"
            try:
                r = subprocess.run(
                    [npm_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    shell=True,
                    creationflags=0x08000000
                )
                if r.returncode == 0:
                    npm_available = True
            except Exception:
                pass
                
            # If system npm is not available, check for local portable Node
            local_node_dir = os.path.join(PROJECT_ROOT, "tools", "node")
            local_npm_path = os.path.join(local_node_dir, "npm.cmd")
            if not npm_available and os.path.exists(local_npm_path):
                npm_available = True
                npm_cmd = local_npm_path

            if not npm_available:
                log_message("System node/npm not found. Downloading portable Node.js v20...")
                self.progress_signal.emit("正在下载前端工具...", "正在下载便携版 Node.js (免安装)...", 0.86)
                try:
                    import urllib.request
                    import zipfile
                    node_zip_url = "https://nodejs.org/dist/v20.12.2/node-v20.12.2-win-x64.zip"
                    node_zip_path = os.path.join(PROJECT_ROOT, "node.zip")
                    urllib.request.urlretrieve(node_zip_url, node_zip_path)
                    
                    self.progress_signal.emit("正在解压前端工具...", "正在配置 Node.js 绿色运行环境...", 0.88)
                    tools_dir = os.path.join(PROJECT_ROOT, "tools")
                    os.makedirs(tools_dir, exist_ok=True)
                    
                    with zipfile.ZipFile(node_zip_path, 'r') as zip_ref:
                        zip_ref.extractall(tools_dir)
                    try: os.remove(node_zip_path)
                    except: pass
                    
                    # Rename extracted folder to 'node'
                    for name in os.listdir(tools_dir):
                        if name.startswith("node-v"):
                            src = os.path.join(tools_dir, name)
                            dst = local_node_dir
                            if os.path.exists(dst):
                                shutil.rmtree(dst)
                            os.rename(src, dst)
                            break
                            
                    if os.path.exists(local_npm_path):
                        npm_available = True
                        npm_cmd = local_npm_path
                        log_message("Portable Node.js set up successfully.")
                except Exception as node_err:
                    self.error_signal.emit(f"自动下载便携版 Node.js 失败！请确保网络正常或手动安装 Node.js。\n\n具体报错: {node_err}")
                    return

            if npm_available:
                self.progress_signal.emit("正在下载前端依赖...", "首次构建前端，执行 npm install...", 0.89)
                try:
                    subprocess.run(
                        [npm_cmd, "install"],
                        cwd=PROJECT_ROOT,
                        shell=True,
                        capture_output=True,
                        creationflags=0x08000000
                    )
                    
                    self.progress_signal.emit("正在编译静态界面...", "执行 npm run build...", 0.92)
                    r = subprocess.run(
                        [npm_cmd, "run", "build"],
                        cwd=PROJECT_ROOT,
                        shell=True,
                        capture_output=True,
                        text=True,
                        creationflags=0x08000000
                    )
                    if not os.path.exists(dist_path):
                        raise Exception(f"Compilation finished but dist folder was not generated: {r.stderr}")
                    log_message("Frontend static assets compiled successfully.")
                except Exception as e:
                    self.error_signal.emit(f"前端静态资源构建失败: {e}")
                    return
            else:
                self.error_signal.emit(
                    "未检测到本地前端静态资源目录 'dist'，且系统未安装 Node.js / npm，无法自动编译前端。\n\n"
                    "请确认是否有预编译好的 'dist' 文件夹并放置在项目根目录，或者在当前系统安装 Node.js。"
                )
                return
        else:
            log_message("Frontend compilation folder 'dist' exists.")

        # Step 5: Verify environment file exists
        self.progress_signal.emit("正在检查系统设置...", "配置默认数据库与环境变量...", 0.95)
        env_path = os.path.join(PROJECT_ROOT, ".env")
        if not os.path.exists(env_path):
            env_example = os.path.join(PROJECT_ROOT, ".env.example")
            if os.path.exists(env_example):
                try:
                    shutil.copy(env_example, env_path)
                    log_message("Default .env file generated from template.")
                except Exception as e:
                    log_message(f"Failed to copy .env template: {e}")

        # Step 5.5: Check and install PostgreSQL database if needed
        need_pg = False
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line_stripped = line.strip()
                        if line_stripped.startswith("DATABASE_URL") and ("postgresql://" in line_stripped.lower() or "postgres://" in line_stripped.lower()):
                            need_pg = True
                            break
            except Exception as e:
                log_message(f"Failed to parse .env file: {e}")

        if need_pg:
            pg_running = False
            import socket
            try:
                # Check if port 5432 is open locally
                with socket.create_connection(("127.0.0.1", 5432), timeout=2.0) as s:
                    pg_running = True
            except Exception:
                pass

            if not pg_running:
                log_message("PostgreSQL port 5432 is closed. Prompting user for auto-installation...")
                import ctypes
                # MB_YESNO = 4, MB_ICONINFORMATION = 0x40
                # Return IDYES = 6
                res = ctypes.windll.user32.MessageBoxW(
                    0, 
                    "检测到配置了 PostgreSQL，但本地 5432 端口未开启。\n\n是否现在自动下载并静默安装 PostgreSQL 16？\n(需要管理员权限且可能会弹出 UAC 提权确认)", 
                    "PostgreSQL 数据库检测", 
                    4 | 0x40
                )
                if res == 6:
                    self.progress_signal.emit("正在下载数据库...", "正在从官方获取 PostgreSQL 16 安装包，请稍候...", 0.96)
                    try:
                        import urllib.request
                        pg_installer_path = os.path.join(PROJECT_ROOT, "postgresql-installer.exe")
                        urllib.request.urlretrieve("https://get.enterprisedb.com/postgresql/postgresql-16.3-1-windows-x64.exe", pg_installer_path)
                        
                        self.progress_signal.emit("正在安装数据库...", "正在执行静默安装 (请在弹出的 UAC 窗口中允许运行)...", 0.97)
                        powershell_cmd = f"Start-Process '{pg_installer_path}' -ArgumentList '--mode unattended --unattendedmodeui none --superpassword netops --serverport 5432' -Verb RunAs -Wait"
                        subprocess.run(["powershell", "-Command", powershell_cmd], creationflags=0x08000000)
                        
                        try:
                            os.remove(pg_installer_path)
                        except Exception:
                            pass
                        
                        # Verify if port 5432 is now open
                        pg_installed = False
                        try:
                            with socket.create_connection(("127.0.0.1", 5432), timeout=2.0) as s:
                                pg_installed = True
                        except Exception:
                            pass
                        
                        if pg_installed:
                            log_message("PostgreSQL auto-installation and startup completed successfully.")
                        else:
                            log_message("PostgreSQL installer finished, but port 5432 is still not responding.")
                    except Exception as pg_err:
                        log_message(f"PostgreSQL installation error: {pg_err}")
                else:
                    log_message("User declined PostgreSQL auto-installation.")

        # Step 6: Create/Update Shortcut
        self.progress_signal.emit("正在生成快捷入口...", "在桌面配置快捷方式...", 0.98)
        try:
            shortcut_script = os.path.join(PROJECT_ROOT, "create_shortcut.py")
            if os.path.exists(shortcut_script):
                subprocess.run(
                    [python_exe, "create_shortcut.py"],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    creationflags=0x08000000
                )
                log_message("Desktop shortcut updated successfully.")
        except Exception as e:
            log_message(f"Failed to regenerate desktop shortcut: {e}")

        # Step 7: Launch desktop_tray.py
        self.progress_signal.emit("初始化完成！", "正在后台启动 NetOps 托盘控制中心...", 1.0)
        time.sleep(0.5)
        
        try:
            tray_script = os.path.join(PROJECT_ROOT, "desktop_tray.py")
            pythonw_exe = os.path.join(venv_path, "Scripts", "pythonw.exe")
            if os.path.exists(pythonw_exe) and os.path.exists(tray_script):
                # 清理环境变量，防止子进程继承并锁定 PyInstaller 的临时目录 _MEIxxxxx
                clean_env = dict(os.environ)
                clean_env.pop("_MEIPASS", None)
                clean_env.pop("PYTHONHOME", None)
                clean_env.pop("PYTHONPATH", None)
                
                keys_to_pop = []
                for k, v in clean_env.items():
                    if k.upper() == "PATH":
                        continue
                    if "_mei" in k.lower() or "_mei" in v.lower():
                        keys_to_pop.append(k)
                for k in keys_to_pop:
                    clean_env.pop(k, None)
                    
                path = clean_env.get("PATH", "")
                if path:
                    paths = path.split(os.pathsep)
                    cleaned_paths = [p for p in paths if "_mei" not in p.lower()]
                    clean_env["PATH"] = os.pathsep.join(cleaned_paths)

                subprocess.Popen(
                    [pythonw_exe, "desktop_tray.py"],
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=0x08000000,
                    env=clean_env
                )
                log_message("NetOps desktop tray process launched.")
            else:
                raise FileNotFoundError("Could not find pythonw.exe or desktop_tray.py")
        except Exception as e:
            self.error_signal.emit(f"启动托盘程序失败: {e}")
            return
            
        self.success_signal.emit()

    def verify_venv(self, venv_path):
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            return False
            
        cfg_path = os.path.join(venv_path, "pyvenv.cfg")
        if not os.path.exists(cfg_path):
            return False
            
        try:
            home_dir = None
            with open(cfg_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("home"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            home_dir = parts[1].strip()
            
            if not home_dir or not os.path.exists(home_dir):
                return False
        except Exception:
            return False
            
        try:
            r = subprocess.run(
                [python_exe, "-c", "import sys; print(sys.prefix)"],
                capture_output=True,
                timeout=5,
                creationflags=0x08000000
            )
            return r.returncode == 0
        except Exception:
            return False

class LauncherUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NetOps Initializer")
        self.setFixedSize(480, 320)
        
        # Center the window
        screen_width = self.screen().geometry().width()
        screen_height = self.screen().geometry().height()
        x = (screen_width - 480) // 2
        y = (screen_height - 320) // 2
        self.setGeometry(x, y, 480, 320)
        
        # Program icon
        ico_path = os.path.join(PROJECT_ROOT, "netops.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))
            
        self.setStyleSheet(LAUNCHER_STYLE)
        set_dark_title_bar(self.winId())
        
        # Set light shadow
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setColor(QColor(0, 0, 0, 80))
        self.shadow.setOffset(0, 4)
        
        self.setup_ui()
        
        # Set up thread worker
        self.worker = SetupWorker()
        self.worker.progress_signal.connect(self.on_progress)
        self.worker.error_signal.connect(self.on_error)
        self.worker.success_signal.connect(self.on_success)
        
        # Run worker after window displays
        QTimer.singleShot(500, lambda: threading.Thread(target=self.worker.run_setup_tasks, daemon=True).start())

    def setup_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(30, 25, 30, 25)
        main_layout.setSpacing(16)
        
        # Header Layout
        header_layout = QHBoxLayout()
        accent_bar = QFrame(self)
        accent_bar.setFixedWidth(4)
        accent_bar.setStyleSheet("background-color: #2563EB;")
        header_layout.addWidget(accent_bar)
        
        title_vbox = QVBoxLayout()
        self.lbl_title = QLabel("NetOps 启动与自愈管理器", self)
        self.lbl_title.setObjectName("lbl_title")
        self.lbl_subtitle = QLabel("Environment Initializer & Launcher", self)
        self.lbl_subtitle.setObjectName("lbl_subtitle")
        
        title_vbox.addWidget(self.lbl_title)
        title_vbox.addWidget(self.lbl_subtitle)
        header_layout.addLayout(title_vbox)
        main_layout.addLayout(header_layout)
        
        # Card container
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setGraphicsEffect(self.shadow)
        
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        
        # Status Label
        self.lbl_status = QLabel("Initializing configuration...", self)
        self.lbl_status.setObjectName("lbl_status")
        card_layout.addWidget(self.lbl_status)
        
        # Progress Bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        card_layout.addWidget(self.progress_bar)
        
        # Log Label
        self.lbl_log = QLabel("Preparing launcher environment...", self)
        self.lbl_log.setObjectName("lbl_log")
        card_layout.addWidget(self.lbl_log)
        
        main_layout.addWidget(self.card)

    @Slot(str, str, float)
    def on_progress(self, status, log_detail, ratio):
        self.lbl_status.setText(status)
        self.lbl_log.setText(log_detail)
        self.progress_bar.setValue(int(ratio * 100))

    @Slot(str)
    def on_error(self, err_msg):
        log_message(f"Fatal setup error: {err_msg}")
        QMessageBox.critical(
            self,
            "NetOps 启动错误",
            f"启动程序时遇到以下严重问题：\n\n{err_msg}\n\n详细报错请查看项目下的 launcher_setup.log 文件。"
        )
        self.close()
        sys.exit(1)

    @Slot()
    def on_success(self):
        log_message("Setup completed successfully. Exiting launcher UI.")
        self.close()
        sys.exit(0)

def main():
    log_message("=== NetOps PySide6 Launcher Session Started ===")
    from PySide6.QtCore import QCoreApplication
    plugins_path = os.path.join(PROJECT_ROOT, ".venv", "Lib", "site-packages", "PySide6", "plugins")
    if os.path.exists(plugins_path):
        QCoreApplication.addLibraryPath(plugins_path)
    app = QApplication(sys.argv)
    window = LauncherUI()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
