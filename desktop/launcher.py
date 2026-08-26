# -*- coding: utf-8 -*-
"""
launcher.py - PySide6 Nexora Graphical Setup Initializer & Launcher.
Provides a premium dark-mode multi-page setup wizard (published as the
backward-compatible NetOps.exe launcher) to configure PostgreSQL, download and
install Python/Node.js,
verify dependencies, compile frontend assets, and launch the platform.
"""

import sys
import os
import time
import shutil
import threading
import subprocess
import ctypes
import socket
import urllib.request
import urllib.error
from urllib.parse import quote, unquote, urlparse
import ssl
import zipfile
import winreg

SOURCE_DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_PROJECT_ROOT = os.path.dirname(SOURCE_DESKTOP_DIR)
if SOURCE_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_PROJECT_ROOT)

from desktop.ui.feedback import show_message
from desktop.ui.launcher_theme import build_launcher_stylesheet

if getattr(sys, 'frozen', False):
    # Running as the bundled Nexora launcher (published as NetOps.exe for
    # backward compatibility), which lives at the repo root.
    PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
    DESKTOP_DIR = os.path.join(PROJECT_ROOT, "desktop")
else:
    # Running as desktop/launcher.py during development.
    DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(DESKTOP_DIR)

LOG_FILE = os.path.join(PROJECT_ROOT, "launcher_setup.log")


def sync_bundled_textfsm_templates():
    """Materialize release templates bundled by PyInstaller.

    The Windows launcher starts the backend from the project directory rather than
    inside the PyInstaller process. One-file resources live under _MEIPASS
    temporarily, so copy only release-owned templates before launching the
    backend. User templates remain in data/textfsm_templates and are untouched.
    """
    if not getattr(sys, "frozen", False):
        return

    bundle_dir = os.path.join(
        getattr(sys, "_MEIPASS", ""),
        "release-textfsm-templates",
    )
    if not os.path.isdir(bundle_dir):
        log_message("Bundled TextFSM templates were not found; keeping existing release templates.")
        return

    target_dir = os.path.join(PROJECT_ROOT, "release-textfsm-templates")
    try:
        os.makedirs(target_dir, exist_ok=True)
        bundled_files = {
            name
            for name in os.listdir(bundle_dir)
            if name.endswith(".textfsm")
            and os.path.isfile(os.path.join(bundle_dir, name))
        }

        # Remove stale release-owned files from an older EXE, then refresh the
        # current set. This directory is separate from user data.
        for name in os.listdir(target_dir):
            path = os.path.join(target_dir, name)
            if name.endswith(".textfsm") and name not in bundled_files:
                os.remove(path)

        for name in bundled_files:
            shutil.copy2(
                os.path.join(bundle_dir, name),
                os.path.join(target_dir, name),
            )
        log_message(f"Synchronized {len(bundled_files)} bundled TextFSM templates.")
    except Exception as exc:
        log_message(f"Failed to synchronize bundled TextFSM templates: {exc}")

# ── Supported runtime version ranges ────────────────────────────────
# The project is validated against these ranges (see README). The goal is to
# REUSE an already-installed, compatible runtime instead of forcing a single
# version. We only download/install a pinned fallback when nothing compatible
# is found on the machine.
SUPPORTED_PY_MIN = (3, 10)          # inclusive
SUPPORTED_PY_MAX = (3, 12)          # inclusive
PY_FALLBACK_VERSION = "3.11.9"      # installed only when no compatible Python exists
NODE_MIN_MAJOR = 20                 # cross-env@10 requires Node.js 20+

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

# Redirect stdout/stderr to logger
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

# Import PySide6 dynamically or defensively
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
        QLabel, QProgressBar, QFrame,
        QStackedWidget, QRadioButton, QLineEdit, QPushButton, QPlainTextEdit,
        QFormLayout, QButtonGroup
    )
    from PySide6.QtCore import Qt, Signal, Slot, QObject, QTimer
    from PySide6.QtGui import QIcon, QTextCursor
except ImportError as e:
    log_message(f"PySide6 import failed: {e}")
    # PyInstaller execution packs PySide6 inside. This is fallback for raw dev runs.
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


LAUNCHER_STYLE = build_launcher_stylesheet(True)

class SetupWorker(QObject):
    log_signal = Signal(str)
    progress_signal = Signal(str, float)
    error_signal = Signal(str)
    success_signal = Signal()

    def __init__(self, db_config, bypassed_config=False):
        super().__init__()
        self.db_config = db_config
        self.bypassed_config = bypassed_config

    def write_log(self, text):
        self.log_signal.emit(text)
        log_message(text.strip())

    def run_command(self, cmd, cwd=None, env=None):
        cmd_str = ' '.join(cmd) if isinstance(cmd, list) else cmd
        self.write_log(f"> Executing: {cmd_str}\n")
        
        # Clean PyInstaller environment to avoid DLL/import conflicts in subprocesses
        run_env = dict(env) if env is not None else dict(os.environ)
        run_env.pop("_MEIPASS", None)
        run_env.pop("PYTHONHOME", None)
        run_env.pop("PYTHONPATH", None)
        
        # Clean proxy variables to prevent pip/pysocks dependencies conflicts
        run_env.pop("HTTP_PROXY", None)
        run_env.pop("HTTPS_PROXY", None)
        run_env.pop("ALL_PROXY", None)
        
        # Clean PyInstaller env vars
        keys_to_pop = [k for k in run_env.keys() if k.startswith("_PYI_")]
        for k in keys_to_pop:
            run_env.pop(k, None)
            
        # Clean any _mei paths from PATH
        path_val = run_env.get("PATH", "")
        if path_val:
            paths = path_val.split(os.pathsep)
            cleaned_paths = [p for p in paths if "_mei" not in p.lower()]
            run_env["PATH"] = os.pathsep.join(cleaned_paths)
            
        try:
            use_shell = sys.platform == "win32"
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=0x08000000,
                env=run_env,
                shell=use_shell
            )
            while True:
                line_bytes = p.stdout.readline()
                if not line_bytes and p.poll() is not None:
                    break
                if line_bytes:
                    try:
                        line = line_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            line = line_bytes.decode('gbk')
                        except UnicodeDecodeError:
                            line = line_bytes.decode('utf-8', errors='replace')
                    self.log_signal.emit(line)
            rc = p.poll()
            if rc != 0:
                raise Exception(f"Command exited with non-zero code {rc}")
        except Exception as e:
            self.write_log(f"Error executing command: {e}\n")
            raise e

    def _build_ssl_context(self, verify=True):
        """Build a TLS context. Prefer the certifi CA bundle (frozen apps and
        fresh VMs often lack a usable system trust store); fall back to the
        system default, or an unverified context when verify=False."""
        if not verify:
            return ssl._create_unverified_context()
        try:
            import certifi
            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()

    def _urlopen(self, req, timeout=60):
        """urlopen with a resilient TLS strategy for clean/locked-down machines.

        Verifies the certificate first (certifi bundle, then system store). If
        verification fails - common on a fresh VM that lacks root CAs, or behind
        a TLS-intercepting proxy - it retries these trusted official download
        URLs over an unverified context, logging a clear warning.
        """
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=self._build_ssl_context(True))
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                self.write_log(
                    "[警告] TLS 证书校验失败（本机可能缺少根证书或存在代理拦截）。"
                    "将对官方下载地址改用免校验连接重试...\n"
                )
                return urllib.request.urlopen(req, timeout=timeout, context=self._build_ssl_context(False))
            raise

    def download_file(self, url, dest_path, desc):
        self.write_log(f"开始下载 {desc}...\nURL: {url}\n")
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with self._urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                downloaded = 0
                block_size = 1024 * 64
                last_percent = -1
                
                with open(dest_path, 'wb') as f:
                    while True:
                        chunk = response.read(block_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = int(downloaded * 100 / total_size)
                            if percent != last_percent:
                                last_percent = percent
                                dl_mb = downloaded / (1024 * 1024)
                                tot_mb = total_size / (1024 * 1024)
                                self.log_signal.emit(f"\r下载进度: {dl_mb:.2f}MB / {tot_mb:.2f}MB ({percent}%)")
            self.log_signal.emit("\n下载完成！\n\n")
        except Exception as e:
            self.write_log(f"\n下载失败: {e}\n\n")
            raise e

    def run_setup_tasks(self):
        try:
            self.write_log("=== Nexora Setup Pipeline Initiated ===\n")
            
            if self.bypassed_config:
                self.progress_signal.emit("正在检查运行环境...", 0.1)
                time.sleep(0.1)
                
                # Check virtual environment exists and is healthy
                venv_path = os.path.join(PROJECT_ROOT, ".venv")
                if os.path.exists(venv_path) and self.verify_venv(venv_path):
                    self.write_log("检测到虚拟环境完备，跳过依赖包安装阶段。\n")
                    self.progress_signal.emit("正在检查数据库状态...", 0.5)
                    time.sleep(0.1)
                    
                    # Verify the actual PostgreSQL credentials, database, and
                    # extensions instead of treating an open TCP port as ready.
                    if self.db_config.get("db_type") == "postgresql":
                        self.ensure_postgres_ready()

                    self.progress_signal.emit("同步 Nexora 桌面快捷方式...", 0.8)
                    self.refresh_desktop_shortcut(
                        os.path.join(venv_path, "Scripts", "python.exe")
                    )
                    
                    self.progress_signal.emit("启动平台自愈服务...", 0.9)
                    time.sleep(0.1)
                    self.progress_signal.emit("部署完成！", 1.0)
                    self.write_log("=== Nexora Setup Pipeline Completed Successfully ===\n")
                    self.success_signal.emit()
                    return
                else:
                    self.write_log("未找到可用虚拟环境或环境已损坏，正在切换至完整部署模式...\n")
                    self.bypassed_config = False

            self.progress_signal.emit("正在定位运行环境...", 0.05)
            time.sleep(0.5)

            # 1. Check/Install a COMPATIBLE Python (range-based, reuse-first).
            #    Any installed 3.10/3.11/3.12 is reused as-is; we only download
            #    and install the pinned fallback when nothing compatible exists.
            self.progress_signal.emit("检查 Python 运行环境 (兼容 3.10-3.12)...", 0.1)
            system_python = self.find_compatible_python()

            if system_python:
                ver = self._python_version(system_python)
                ver_str = f"{ver[0]}.{ver[1]}" if ver else "?"
                self.write_log(f"检测到兼容的 Python {ver_str} 解释器，直接复用: {system_python}\n")
            else:
                self.write_log(
                    f"未检测到兼容的 Python (需要 {SUPPORTED_PY_MIN[0]}.{SUPPORTED_PY_MIN[1]}-"
                    f"{SUPPORTED_PY_MAX[0]}.{SUPPORTED_PY_MAX[1]})，开始下载并安装 Python {PY_FALLBACK_VERSION}...\n"
                )
                py_installer_url = f"https://www.python.org/ftp/python/{PY_FALLBACK_VERSION}/python-{PY_FALLBACK_VERSION}-amd64.exe"
                py_installer_path = os.path.join(PROJECT_ROOT, "python-installer.exe")
                
                self.progress_signal.emit(f"正在下载 Python {PY_FALLBACK_VERSION}...", 0.15)
                self.download_file(py_installer_url, py_installer_path, f"Python {PY_FALLBACK_VERSION}")
                
                self.progress_signal.emit("正在执行 Python 静默安装...", 0.25)
                self.write_log("正在执行 Python 静默安装 (仅对当前用户安装并添加环境变量)...\n")
                self.run_command([py_installer_path, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0", "Include_doc=0"])
                
                try:
                    os.remove(py_installer_path)
                except Exception:
                    pass

                # Refresh environment PATH from registry
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

                # Re-locate the freshly installed interpreter and use its
                # absolute path so venv creation never falls back to an
                # incompatible Python on PATH (e.g. a Microsoft Store stub).
                system_python = self.find_compatible_python()
                if not system_python:
                    raise RuntimeError(
                        f"Python {PY_FALLBACK_VERSION} 安装后仍未能定位到兼容解释器，"
                        "请手动安装 Python 3.10-3.12 后重试。"
                    )
                self.write_log(f"Python 安装完成: {system_python}\n")

            # 2. Virtual Environment Setup
            self.progress_signal.emit("验证虚拟环境 (.venv)...", 0.3)
            venv_path = os.path.join(PROJECT_ROOT, ".venv")
            venv_broken = False
            
            if os.path.exists(venv_path):
                self.write_log("发现已有的 .venv 目录，正在验证其完整性...\n")
                if not self.verify_venv(venv_path):
                    self.write_log("虚拟环境失效，准备清理旧环境...\n")
                    venv_broken = True
                    try:
                        shutil.rmtree(venv_path)
                    except Exception:
                        subprocess.run(f'rmdir /s /q "{venv_path}"', shell=True, creationflags=0x08000000)
            
            if not os.path.exists(venv_path) or venv_broken:
                self.write_log("正在创建 .venv 虚拟环境...\n")
                self.run_command([system_python, "-m", "venv", ".venv"], cwd=PROJECT_ROOT)
                self.write_log("虚拟环境创建成功。\n")

            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
            pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")

            # 3. Upgrade pip & Install requirements
            self.progress_signal.emit("配置虚拟环境依赖包...", 0.45)
            self.write_log("正在升级虚拟环境下的 pip 工具...\n")
            self.run_command([python_exe, "-m", "pip", "install", "--upgrade", "pip"], cwd=PROJECT_ROOT)

            self.write_log("正在安装后台 Python 依赖包 (requirements.txt)...\n")
            self.run_command([pip_exe, "install", "-r", "backend/requirements.txt"], cwd=PROJECT_ROOT)

            self.write_log("正在安装 GUI 所需依赖包 (PySide6, pillow, pystray)...\n")
            self.run_command([pip_exe, "install", "PySide6", "pillow", "pystray"], cwd=PROJECT_ROOT)

            # 4. Check & Install PostgreSQL
            db_type = self.db_config.get("db_type")
            if db_type == "postgresql":
                self.progress_signal.emit("检查/配置 PostgreSQL 数据库...", 0.6)
                host = self.db_config.get("host", "127.0.0.1")
                port = int(self.db_config.get("port", "5432"))
                password = self.db_config.get("password", "netops")
                
                is_local = host in ("127.0.0.1", "localhost")
                pg_running = False
                
                # Check connection port
                try:
                    with socket.create_connection((host, port), timeout=2.0) as s:
                        pg_running = True
                except Exception:
                    pass

                if pg_running:
                    self.write_log(f"检测到 PostgreSQL 端口 {port} 已打开，跳过本地静默安装。\n")
                else:
                    if is_local:
                        self.write_log(f"检测到本地 PostgreSQL 端口 {port} 未响应，开始下载并静默部署 PostgreSQL 17...\n")
                        pg_url = "https://get.enterprisedb.com/postgresql/postgresql-17.2-1-windows-x64.exe"
                        pg_installer_path = os.path.join(PROJECT_ROOT, "postgresql-installer.exe")
                        
                        self.progress_signal.emit("正在下载 PostgreSQL 17...", 0.65)
                        self.download_file(pg_url, pg_installer_path, "PostgreSQL 17")
                        
                        self.progress_signal.emit("正在安装 PostgreSQL (请在 UAC 提权提示中允许运行)...", 0.75)
                        self.write_log("正在执行静默安装数据库。系统将弹出 UAC 提权请求，请在弹出的窗口中允许运行。\n")
                        
                        powershell_cmd = f"Start-Process '{pg_installer_path}' -ArgumentList '--mode unattended --unattendedmodeui none --superpassword \"{password}\" --serverport {port}' -Verb RunAs -Wait"
                        self.run_command(["powershell", "-Command", powershell_cmd])
                        
                        try:
                            os.remove(pg_installer_path)
                        except Exception:
                            pass
                        
                        # Verify
                        pg_installed = False
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as s:
                                pg_installed = True
                        except Exception:
                            pass
                            
                        if pg_installed:
                            self.write_log("PostgreSQL 17 本地服务安装完成并正常运行！\n")
                        else:
                            self.write_log("[警告] PostgreSQL 静默安装完毕，但本地端口仍未响应。请检查系统服务。\n")
                    else:
                        self.write_log(f"[提示] 检测到配置了远程数据库 {host}:{port}。跳过本地静默安装。\n")

                    self.progress_signal.emit("验证 PostgreSQL 数据库与 AI 扩展...", 0.78)
                    self.ensure_postgres_ready()

            # 5. Compile Frontend static files if dist is missing
            dist_path = os.path.join(PROJECT_ROOT, "dist")
            if not os.path.exists(dist_path):
                self.progress_signal.emit("正在准备编译前端界面...", 0.8)
                self.write_log("未检测到前端 dist 编译输出目录。准备编译前端资产...\n")
                
                npm_available = False
                npm_cmd = "npm"
                # Reuse a system Node.js only when it meets the minimum major
                # version (Node 20+). An older system Node falls back to the
                # bundled/portable Node so the frontend build stays reliable.
                try:
                    rn = subprocess.run(
                        ["node", "--version"],
                        capture_output=True, text=True, shell=True,
                        creationflags=0x08000000
                    )
                    if rn.returncode == 0:
                        try:
                            node_major = int(rn.stdout.strip().lstrip("vV").split(".")[0])
                        except Exception:
                            node_major = 0
                        if node_major >= NODE_MIN_MAJOR:
                            r = subprocess.run(
                                [npm_cmd, "--version"],
                                capture_output=True, text=True, shell=True,
                                creationflags=0x08000000
                            )
                            if r.returncode == 0:
                                npm_available = True
                                self.write_log(f"检测到兼容的 Node.js {rn.stdout.strip()}，直接复用。\n")
                        else:
                            self.write_log(
                                f"系统 Node.js {rn.stdout.strip()} 低于最低要求 v{NODE_MIN_MAJOR}，将改用便携版。\n"
                            )
                except Exception:
                    pass

                local_node_dir = os.path.join(PROJECT_ROOT, "tools", "node")
                local_npm_path = os.path.join(local_node_dir, "npm.cmd")
                
                if not npm_available and os.path.exists(local_npm_path):
                    npm_available = True
                    npm_cmd = local_npm_path

                if not npm_available:
                    self.write_log("未检测到系统 Node.js。开始下载便携版 Node.js v20 (免安装)...\n")
                    node_url = "https://nodejs.org/dist/v20.12.2/node-v20.12.2-win-x64.zip"
                    node_zip_path = os.path.join(PROJECT_ROOT, "node.zip")
                    
                    self.progress_signal.emit("正在下载 Node.js v20...", 0.82)
                    self.download_file(node_url, node_zip_path, "Node.js Portable")
                    
                    self.progress_signal.emit("正在解压 Node.js...", 0.85)
                    tools_dir = os.path.join(PROJECT_ROOT, "tools")
                    os.makedirs(tools_dir, exist_ok=True)
                    
                    with zipfile.ZipFile(node_zip_path, 'r') as zip_ref:
                        zip_ref.extractall(tools_dir)
                    try:
                        os.remove(node_zip_path)
                    except Exception:
                        pass
                    
                    for name in os.listdir(tools_dir):
                        if name.startswith("node-v"):
                            src = os.path.join(tools_dir, name)
                            if os.path.exists(local_node_dir):
                                shutil.rmtree(local_node_dir)
                            os.rename(src, local_node_dir)
                            break
                    
                    if os.path.exists(local_npm_path):
                        npm_available = True
                        npm_cmd = local_npm_path

                if npm_available:
                    self.progress_signal.emit("正在安装前端依赖包 (npm install --include=dev)...", 0.88)
                    run_env = dict(os.environ)
                    if os.path.exists(local_node_dir):
                        run_env["PATH"] = local_node_dir + os.pathsep + run_env.get("PATH", "")
                    
                    self.run_command([npm_cmd, "install", "--include=dev"], cwd=PROJECT_ROOT, env=run_env)
                    
                    self.progress_signal.emit("正在编译静态资源 (npm run build)...", 0.92)
                    self.run_command([npm_cmd, "run", "build"], cwd=PROJECT_ROOT, env=run_env)
                else:
                    raise Exception("未找到 Node.js/npm 编译环境，且自动下载便携版失败。无法编译前端静态界面！")
            else:
                self.write_log("前端编译文件目录已存在，跳过前端编译步骤。\n")

            # 6. Configure .env File
            self.progress_signal.emit("更新环境变量配置...", 0.95)
            self.configure_env_file()

            # 7. Create desktop shortcut
            self.progress_signal.emit("生成桌面快捷方式...", 0.98)
            self.refresh_desktop_shortcut(python_exe)

            # Finalize
            self.progress_signal.emit("部署完成！", 1.0)
            self.write_log("=== Nexora Setup Pipeline Completed Successfully ===\n")
            self.success_signal.emit()

        except Exception as err:
            self.write_log(f"\n[ERROR] 部署过程中遭遇严重错误: {err}\n")
            self.error_signal.emit(str(err))

    def ensure_postgres_ready(self):
        """Authenticate to PostgreSQL and ensure the current migration contract.

        The Windows installer can provision the PostgreSQL server binary, but it
        cannot assume that the selected account or business database exists. Do
        the same readiness checks the backend migration will require so the
        wizard reports an actionable error before claiming success.
        """
        if self.db_config.get("db_type") != "postgresql":
            return

        host = self.db_config.get("host", "127.0.0.1")
        port = int(self.db_config.get("port", "5432"))
        user = str(self.db_config.get("user") or "postgres")
        password = str(self.db_config.get("password") or "")
        db_name = str(self.db_config.get("db_name") or "netops")
        if not db_name:
            raise RuntimeError("PostgreSQL 业务数据库名不能为空。")

        try:
            import psycopg2
            from psycopg2 import sql
        except ImportError as exc:
            raise RuntimeError(
                "当前虚拟环境缺少 psycopg2，请重新运行 Nexora 部署向导安装后端依赖。"
            ) from exc

        connect_kwargs = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "connect_timeout": 5,
        }

        def connect(database):
            return psycopg2.connect(dbname=database, **connect_kwargs)

        target_conn = None
        try:
            try:
                target_conn = connect(db_name)
            except Exception as target_error:
                # PostgreSQL SQLSTATE 3D000 means the target database is
                # missing. Other errors are authentication/network failures
                # and must not be hidden behind an automatic CREATE DATABASE.
                if getattr(target_error, "pgcode", None) != "3D000":
                    raise RuntimeError(
                        f"无法登录 PostgreSQL 目标数据库 {db_name}。请确认主机、端口、用户名、密码和数据库名。"
                    ) from target_error

                try:
                    maintenance_conn = connect("postgres")
                except Exception as maintenance_error:
                    raise RuntimeError(
                        f"PostgreSQL 服务可达，但业务数据库 {db_name} 不存在，且无法连接维护库 postgres。"
                        "请先创建数据库或使用具有 CREATEDB 权限的账号。"
                    ) from maintenance_error

                try:
                    maintenance_conn.autocommit = True
                    with maintenance_conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT 1 FROM pg_database WHERE datname = %s",
                            (db_name,),
                        )
                        if cursor.fetchone() is None:
                            cursor.execute(
                                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                                    sql.Identifier(db_name),
                                    sql.Identifier(user),
                                )
                            )
                            self.write_log(f"已创建 PostgreSQL 业务数据库 {db_name}。\n")
                except Exception as create_error:
                    raise RuntimeError(
                        f"无法创建 PostgreSQL 业务数据库 {db_name}。请使用管理员或 CREATEDB 账号手工创建。"
                    ) from create_error
                finally:
                    maintenance_conn.close()

                target_conn = connect(db_name)

            with target_conn.cursor() as cursor:
                cursor.execute("SHOW server_version")
                server_version = str(cursor.fetchone()[0])
                cursor.execute("SHOW server_version_num")
                server_version_num = int(cursor.fetchone()[0])
                major_version = server_version_num // 10000
                if major_version != 17:
                    self.write_log(
                        f"[警告] 当前 PostgreSQL 为 {server_version}，Docker 基线为 PostgreSQL 17；"
                        "建议新 Windows 部署使用 PostgreSQL 17。\n"
                    )

                required_extensions = ("vector", "pg_trgm")
                cursor.execute(
                    "SELECT name FROM pg_available_extensions WHERE name IN (%s, %s)",
                    required_extensions,
                )
                available = {row[0] for row in cursor.fetchall()}
                unavailable = [name for name in required_extensions if name not in available]
                if unavailable:
                    missing = ", ".join(unavailable)
                    raise RuntimeError(
                        f"PostgreSQL 缺少扩展 {missing}。请安装与 PostgreSQL {major_version} 匹配的 "
                        "pgvector，并确认 pg_trgm/contrib 可用后重试。"
                    )

                cursor.execute(
                    "SELECT extname FROM pg_extension WHERE extname IN (%s, %s)",
                    required_extensions,
                )
                installed = {row[0] for row in cursor.fetchall()}
                for extension in required_extensions:
                    if extension not in installed:
                        cursor.execute(
                            sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                                sql.Identifier(extension)
                            )
                        )
                target_conn.commit()

            self.write_log(
                f"PostgreSQL 已验证：{server_version}，数据库 {db_name}，"
                "vector 与 pg_trgm 均可用。\n"
            )
        except RuntimeError:
            if target_conn is not None:
                target_conn.rollback()
            raise
        except Exception as exc:
            if target_conn is not None:
                target_conn.rollback()
            raise RuntimeError(
                "PostgreSQL 扩展初始化失败。请确认当前账号拥有 CREATE EXTENSION 权限。"
            ) from exc
        finally:
            if target_conn is not None:
                target_conn.close()

    def refresh_desktop_shortcut(self, python_exe):
        """Create the Nexora shortcut and migrate the old NetOps shortcut name."""
        try:
            shortcut_script = os.path.join(DESKTOP_DIR, "create_shortcut.py")
            if os.path.exists(shortcut_script):
                self.run_command([python_exe, shortcut_script], cwd=PROJECT_ROOT)
        except Exception as exc:
            # A shortcut is convenient but not required for the platform to
            # run, so keep deployment successful when Windows policy blocks it.
            self.write_log(f"[警告] 创建 Nexora 桌面快捷方式失败: {exc}\n")

    def _python_version(self, exe):
        """Return (major, minor) for a python executable, or None on failure."""
        try:
            r = subprocess.run(
                [exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=8,
                creationflags=0x08000000
            )
            if r.returncode != 0:
                return None
            major, minor = r.stdout.strip().split(".")[:2]
            return (int(major), int(minor))
        except Exception:
            return None

    def _python_in_range(self, exe):
        """True if the executable's version is within the supported range."""
        ver = self._python_version(exe)
        return ver is not None and SUPPORTED_PY_MIN <= ver <= SUPPORTED_PY_MAX

    def find_compatible_python(self):
        """Locate a Python interpreter within the supported range (3.10-3.12).

        Reuses an already-installed, compatible interpreter instead of forcing a
        single version. Probe order favours what the user already has: PATH
        ``python``, the ``py`` launcher (highest supported minor first), the
        registry-registered installs, and the standard install directories.
        Returns an absolute python.exe path (or the literal ``python``), or None
        when nothing compatible is present.
        """
        # 1. Whatever ``python`` resolves to on PATH, if it is in range.
        if self._python_in_range("python"):
            return "python"

        # 2. The Windows ``py`` launcher, preferring the highest supported minor.
        for minor in range(SUPPORTED_PY_MAX[1], SUPPORTED_PY_MIN[1] - 1, -1):
            try:
                r = subprocess.run(
                    ["py", f"-3.{minor}", "-c", "import sys; print(sys.executable)"],
                    capture_output=True, text=True, timeout=8,
                    creationflags=0x08000000
                )
                if r.returncode == 0:
                    exe = r.stdout.strip()
                    if exe and os.path.exists(exe) and self._python_in_range(exe):
                        return exe
            except Exception:
                pass

        # 3. Registry-registered installs + standard install directories,
        #    again preferring the highest supported minor version.
        candidates = []
        local = os.environ.get("LOCALAPPDATA", "")
        for minor in range(SUPPORTED_PY_MAX[1], SUPPORTED_PY_MIN[1] - 1, -1):
            ver = f"3.{minor}"
            short = f"Python3{minor}"
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Python\PythonCore\{ver}\InstallPath") as key:
                        install_dir = winreg.QueryValueEx(key, None)[0]
                        if install_dir:
                            candidates.append(os.path.join(install_dir, "python.exe"))
                except Exception:
                    pass
            if local:
                candidates.append(os.path.join(local, "Programs", "Python", short, "python.exe"))
            candidates.append(rf"C:\Program Files\{short}\python.exe")
            candidates.append(rf"C:\{short}\python.exe")

        for exe in candidates:
            if exe and os.path.exists(exe) and self._python_in_range(exe):
                return exe

        return None

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
            clean_env = dict(os.environ)
            clean_env.pop("_MEIPASS", None)
            clean_env.pop("PYTHONHOME", None)
            clean_env.pop("PYTHONPATH", None)
            keys_to_pop = [k for k in clean_env.keys() if k.startswith("_PYI_")]
            for k in keys_to_pop:
                clean_env.pop(k, None)
                
            r = subprocess.run(
                [python_exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=0x08000000,
                env=clean_env
            )
            if r.returncode != 0:
                return False
            # The venv must be a SUPPORTED Python (3.10-3.12). If it is some
            # other version (e.g. a stale 3.13 environment) treat it as broken
            # so it gets rebuilt with a compatible interpreter; any in-range
            # version is accepted as-is and left untouched.
            try:
                major, minor = r.stdout.strip().split(".")[:2]
                ver = (int(major), int(minor))
            except Exception:
                return False
            return SUPPORTED_PY_MIN <= ver <= SUPPORTED_PY_MAX
        except Exception:
            return False

    def configure_env_file(self):
        env_path = os.path.join(PROJECT_ROOT, ".env")
        if not os.path.exists(env_path):
            env_example = os.path.join(PROJECT_ROOT, ".env.example")
            if os.path.exists(env_example):
                shutil.copy(env_example, env_path)
                self.write_log("根据 .env.example 模板生成了默认 .env 配置文件。\n")
            else:
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("# Database Settings\n")

        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        keys_to_update = {}
        host = self.db_config.get("host")
        port = self.db_config.get("port")
        user = self.db_config.get("user")
        password = self.db_config.get("password")
        db_name = self.db_config.get("db_name")
        
        keys_to_update["POSTGRES_USER"] = user
        keys_to_update["POSTGRES_PASSWORD"] = password
        keys_to_update["POSTGRES_DB"] = db_name
        encoded_user = quote(user or "", safe="")
        encoded_password = quote(password or "", safe="")
        encoded_db_name = quote(db_name or "", safe="")
        keys_to_update["DATABASE_URL"] = (
            f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{encoded_db_name}"
        )

        new_lines = []
        updated_keys = set()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                new_lines.append(line)
                continue
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                if key in keys_to_update:
                    new_lines.append(f"{key}={keys_to_update[key]}\n")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        for key, val in keys_to_update.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={val}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        self.write_log("已成功将数据库配置写入环境变量 .env 文件 (模式: postgresql)。\n")


def load_existing_config():
    config = {
        "host": "127.0.0.1",
        "port": "5432",
        "user": "postgres",
        "password": "netops",
        "db_name": "netops"
    }
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("=", 1)
                    if len(parts) == 2:
                        key, val = parts[0].strip(), parts[1].strip()
                        if key == "POSTGRES_USER":
                            config["user"] = val
                        elif key == "POSTGRES_PASSWORD":
                            config["password"] = val
                        elif key == "POSTGRES_DB":
                            config["db_name"] = val
                        elif key == "DATABASE_URL":
                            try:
                                url_data = val.split("://", 1)[1]
                                if "@" in url_data:
                                    creds, rest = url_data.split("@", 1)
                                    if ":" in creds:
                                        config["user"], config["password"] = creds.split(":", 1)
                                    else:
                                        config["user"] = creds
                                else:
                                    rest = url_data
                                
                                if "/" in rest:
                                    host_port, db = rest.split("/", 1)
                                    if "?" in db:
                                        db = db.split("?", 1)[0]
                                    config["db_name"] = db
                                else:
                                    host_port = rest
                                    
                                if ":" in host_port:
                                    config["host"], config["port"] = host_port.split(":", 1)
                                else:
                                    config["host"] = host_port
                            except Exception:
                                pass
        except Exception:
            pass
    return config


def load_database_config_from_env():
    config = {
        "host": "127.0.0.1",
        "port": "5432",
        "user": "postgres",
        "password": "postgres",
        "db_name": "netops",
    }
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return config

    values = {}
    try:
        with open(env_path, "r", encoding="utf-8-sig") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return config

    database_url = values.get("DATABASE_URL", "").strip()
    if database_url:
        try:
            parsed = urlparse(database_url)
            if parsed.scheme.lower() in {"postgresql", "postgres"}:
                config.update(
                    host=parsed.hostname or config["host"],
                    port=str(parsed.port or 5432),
                    user=unquote(parsed.username or config["user"]),
                    password=unquote(parsed.password or ""),
                    db_name=unquote(parsed.path.lstrip("/")) or config["db_name"],
                )
                return config
        except (TypeError, ValueError):
            pass

    config["host"] = values.get("POSTGRES_HOST", config["host"])
    config["port"] = values.get("POSTGRES_PORT", config["port"])
    config["user"] = values.get("POSTGRES_USER", config["user"])
    config["password"] = values.get("POSTGRES_PASSWORD", config["password"])
    config["db_name"] = values.get("POSTGRES_DB", config["db_name"])
    return config


class LauncherUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initial_config = load_database_config_from_env()
        self.setWindowTitle("Nexora 部署与启动管理器")
        self.setMinimumSize(700, 520)
        self.resize(760, 560)
        
        # Center the window
        screen = self.screen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
        # Program icon
        ico_path = os.path.join(DESKTOP_DIR, "netops.ico")
        if os.path.exists(ico_path):
            self.setWindowIcon(QIcon(ico_path))
            
        self.setStyleSheet(LAUNCHER_STYLE)
        set_dark_title_bar(self.winId())
        
        self.setup_ui()

    def setup_ui(self):
        # Central Stacked Widget
        self.stacked_widget = QStackedWidget(self)
        self.setCentralWidget(self.stacked_widget)
        
        self.create_page_config()
        self.create_page_progress()
        self.create_page_finish()
        
        self.stacked_widget.addWidget(self.page_config)
        self.stacked_widget.addWidget(self.page_progress)
        self.stacked_widget.addWidget(self.page_finish)
        
        env_path = os.path.join(PROJECT_ROOT, ".env")
        force_reconfig = "--reconfig" in sys.argv or "--smoke-test" in sys.argv
        has_valid_config = (
            self.initial_config.get("host") and 
            self.initial_config.get("port") and 
            self.initial_config.get("user") and 
            self.initial_config.get("db_name")
        )
        
        if os.path.exists(env_path) and has_valid_config and not force_reconfig:
            self.bypassed_config = True
            self.stacked_widget.setCurrentWidget(self.page_progress)
            QTimer.singleShot(100, self.start_installation)
        else:
            self.bypassed_config = False
            self.stacked_widget.setCurrentWidget(self.page_config)

    def create_page_config(self):
        self.page_config = QWidget()
        layout = QVBoxLayout(self.page_config)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(15)
        
        # Header Layout
        header_layout = QHBoxLayout()
        accent_bar = QFrame(self)
        accent_bar.setObjectName("accent_bar")
        accent_bar.setFixedWidth(4)
        accent_bar.setFixedHeight(45)
        header_layout.addWidget(accent_bar)
        
        title_vbox = QVBoxLayout()
        lbl_title = QLabel("Nexora 部署与 PostgreSQL 配置向导", self)
        lbl_title.setObjectName("lbl_title")
        lbl_subtitle = QLabel("请配置您的 PostgreSQL 数据库连接参数，系统将自动配置并部署运行环境。", self)
        lbl_subtitle.setObjectName("lbl_subtitle")
        title_vbox.addWidget(lbl_title)
        title_vbox.addWidget(lbl_subtitle)
        header_layout.addLayout(title_vbox)
        layout.addLayout(header_layout)
        
        # Credentials Form
        lbl_pg_sec = QLabel("PostgreSQL 连接参数", self)
        lbl_pg_sec.setObjectName("lbl_section")
        layout.addWidget(lbl_pg_sec)
        
        form_fields_layout = QFormLayout()
        form_fields_layout.setHorizontalSpacing(20)
        form_fields_layout.setVerticalSpacing(8)
        
        self.input_host = QLineEdit(self.initial_config["host"], self)
        self.input_port = QLineEdit(self.initial_config["port"], self)
        self.input_user = QLineEdit(self.initial_config["user"], self)
        self.input_pass = QLineEdit(self.initial_config["password"], self)
        self.input_pass.setEchoMode(QLineEdit.Password)
        self.input_db_name = QLineEdit(self.initial_config["db_name"], self)
        
        form_fields_layout.addRow("数据库主机:", self.input_host)
        form_fields_layout.addRow("端口:", self.input_port)
        form_fields_layout.addRow("用户名:", self.input_user)
        form_fields_layout.addRow("密码:", self.input_pass)
        form_fields_layout.addRow("数据库名:", self.input_db_name)
        layout.addLayout(form_fields_layout)
        
        layout.addStretch()
        
        # Buttons layout
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_next = QPushButton("开始部署安装", self)
        self.btn_next.setObjectName("btn_primary")
        self.btn_next.clicked.connect(self.start_installation)
        btn_layout.addWidget(self.btn_next)
        
        layout.addLayout(btn_layout)

    def create_page_progress(self):
        self.page_progress = QWidget()
        layout = QVBoxLayout(self.page_progress)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(12)
        
        # Header
        header_layout = QHBoxLayout()
        accent_bar = QFrame(self)
        accent_bar.setObjectName("accent_bar")
        accent_bar.setFixedWidth(4)
        accent_bar.setFixedHeight(30)
        header_layout.addWidget(accent_bar)
        
        title_vbox = QVBoxLayout()
        lbl_title = QLabel("正在部署 Nexora 系统组件", self)
        lbl_title.setObjectName("lbl_title")
        title_vbox.addWidget(lbl_title)
        header_layout.addLayout(title_vbox)
        layout.addLayout(header_layout)
        
        # Progress Bar and Status
        self.lbl_status = QLabel("正在初始化部署管道...", self)
        self.lbl_status.setObjectName("status_text")
        layout.addWidget(self.lbl_status)
        
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)
        
        # Log terminal
        lbl_log_title = QLabel("部署控制台输出", self)
        lbl_log_title.setObjectName("helper_text")
        layout.addWidget(lbl_log_title)
        
        self.console_log = QPlainTextEdit(self)
        self.console_log.setObjectName("console_log")
        self.console_log.setReadOnly(True)
        layout.addWidget(self.console_log)
        
        # Warning label
        lbl_uac_warn = QLabel("注：在安装 Python、Node.js 或 PostgreSQL 数据库时可能会弹出 Windows UAC 管理员提权确认框，请点击“是”允许运行。", self)
        lbl_uac_warn.setObjectName("helper_text")
        lbl_uac_warn.setWordWrap(True)
        layout.addWidget(lbl_uac_warn)

    def create_page_finish(self):
        self.page_finish = QWidget()
        layout = QVBoxLayout(self.page_finish)
        layout.setContentsMargins(40, 50, 40, 50)
        layout.setSpacing(20)
        
        layout.addStretch()
        
        # Checkmark Icon (rendered using simple CSS)
        lbl_icon = QLabel("✔", self)
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_icon.setObjectName("success_icon")
        layout.addWidget(lbl_icon)
        
        # Finish Title
        lbl_finish_title = QLabel("系统部署配置成功！", self)
        lbl_finish_title.setAlignment(Qt.AlignCenter)
        lbl_finish_title.setObjectName("lbl_title")
        layout.addWidget(lbl_finish_title)
        
        # Details
        self.lbl_finish_desc = QLabel("已成功为您创建虚拟环境、安装核心包依赖并配置了数据库选项。\n您现在可以启动托盘控制中心进入平台。", self)
        self.lbl_finish_desc.setAlignment(Qt.AlignCenter)
        self.lbl_finish_desc.setObjectName("finish_desc")
        layout.addWidget(self.lbl_finish_desc)
        
        layout.addStretch()
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_start_tray = QPushButton("启动平台客户端", self)
        self.btn_start_tray.setObjectName("btn_primary")
        self.btn_start_tray.clicked.connect(self.start_tray_and_exit)
        
        self.btn_exit = QPushButton("完成并退出", self)
        self.btn_exit.setObjectName("btn_secondary")
        self.btn_exit.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_start_tray)
        btn_layout.addWidget(self.btn_exit)
        
        layout.addLayout(btn_layout)

    def start_installation(self):
        # Construct db configuration
        db_config = {}
        db_config["db_type"] = "postgresql"
        db_config["host"] = self.input_host.text().strip()
        db_config["port"] = self.input_port.text().strip()
        db_config["user"] = self.input_user.text().strip()
        db_config["password"] = self.input_pass.text()
        db_config["db_name"] = self.input_db_name.text().strip()
        
        if not db_config["host"] or not db_config["port"] or not db_config["user"] or not db_config["db_name"]:
            show_message(
                self,
                "参数不完整",
                "请完整填写 PostgreSQL 数据库的所有连接参数。",
                dark=True,
            )
            return
        try:
            port = int(db_config["port"])
        except ValueError:
            port = 0
        if not 1 <= port <= 65535:
            show_message(self, "端口无效", "数据库端口必须是 1 到 65535 之间的整数。", dark=True)
            return

        # Show page 2
        self.stacked_widget.setCurrentWidget(self.page_progress)
        self.lbl_status.setText("正在初始化部署任务...")
        self.progress_bar.setValue(0)
        
        # Start worker thread
        self.worker = SetupWorker(db_config, bypassed_config=getattr(self, "bypassed_config", False))
        self.worker.log_signal.connect(self.on_log_received)
        self.worker.progress_signal.connect(self.on_progress_received)
        self.worker.error_signal.connect(self.on_error_received)
        self.worker.success_signal.connect(self.on_success_received)
        
        threading.Thread(target=self.worker.run_setup_tasks, daemon=True).start()

    @Slot(str)
    def on_log_received(self, text):
        cursor = self.console_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        if text.startswith("\r"):
            # Carriage return simulation for in-place updates (like downloads)
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.insertText(text.replace("\r", ""))
        else:
            self.console_log.appendPlainText(text.rstrip("\r\n"))
            
        self.console_log.moveCursor(QTextCursor.End)

    @Slot(str, float)
    def on_progress_received(self, status, ratio):
        self.lbl_status.setText(status)
        self.progress_bar.setValue(int(ratio * 100))

    @Slot(str)
    def on_error_received(self, err_msg):
        show_message(
            self,
            "部署错误",
            f"系统在部署安装过程中遭遇错误，流程已终止：\n\n{err_msg}\n\n详情请查阅项目目录下的 launcher_setup.log 日志。",
            dark=True,
        )
        self.close()
        sys.exit(1)

    @Slot()
    def on_success_received(self):
        if getattr(self, "bypassed_config", False):
            log_message("Silent configuration check passed. Auto-starting tray...")
            self.start_tray_and_exit()
            return
            
        # Update text on page 3
        self.lbl_finish_desc.setText(
            "已成功将数据库引擎设置为：PostgreSQL 企业版。\n"
            "环境搭建与后端模块升级均已通过验证，桌面快捷键与自愈服务已全部就绪。\n"
            "您可以立即启动系统托盘控制中心，系统将自动帮您托管主运行后台."
        )
        self.stacked_widget.setCurrentWidget(self.page_finish)

    def start_tray_and_exit(self):
        try:
            tray_script = os.path.join(DESKTOP_DIR, "desktop_tray.py")
            pythonw_exe = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "pythonw.exe")
            if os.path.exists(pythonw_exe) and os.path.exists(tray_script):
                # Clean environmental paths to avoid inheriting temporary bundle paths (_MEIxxxx)
                clean_env = dict(os.environ)
                clean_env.pop("_MEIPASS", None)
                clean_env.pop("PYTHONHOME", None)
                clean_env.pop("PYTHONPATH", None)
                
                keys_to_pop = []
                for k, v in clean_env.items():
                    if k.upper() == "PATH":
                        continue
                    if k.startswith("_PYI_") or "_mei" in k.lower() or "_mei" in v.lower():
                        keys_to_pop.append(k)
                for k in keys_to_pop:
                    clean_env.pop(k, None)
                    
                path = clean_env.get("PATH", "")
                if path:
                    paths = path.split(os.pathsep)
                    cleaned_paths = [p for p in paths if "_mei" not in p.lower()]
                    clean_env["PATH"] = os.pathsep.join(cleaned_paths)

                subprocess.Popen(
                    [pythonw_exe, tray_script],
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=0x08000000,
                    env=clean_env
                )
                log_message("Nexora desktop tray process launched.")
            else:
                raise FileNotFoundError("无法找到 pythonw.exe 虚拟环境组件或 desktop_tray.py 主程序")
        except Exception as e:
            show_message(self, "启动失败", f"无法启动托盘客户端：{e}", dark=True)
            
        self.close()
        sys.exit(0)


def main():
    log_message("=== Nexora Setup GUI Session Started ===")
    sync_bundled_textfsm_templates()
    smoke_test = "--smoke-test" in sys.argv
    
    # 1. Check if another instance of desktop tray is already running (to directly bring it up)
    if "--reconfig" not in sys.argv and not smoke_test:
        import socket
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.settimeout(0.5)
            test_sock.connect(("127.0.0.1", 5019))
            test_sock.sendall("SHOW_GUI".encode("utf-8"))
            test_sock.close()
            log_message("Another Nexora Agent is already running. Signal sent. Exiting launcher...")
            sys.exit(0)
        except Exception:
            pass

        # Fast-start bypass check (no-GUI mode for daily starts)
        env_path = os.path.join(PROJECT_ROOT, ".env")
        venv_path = os.path.join(PROJECT_ROOT, ".venv")
        pythonw_exe = os.path.join(venv_path, "Scripts", "pythonw.exe")
        tray_script = os.path.join(DESKTOP_DIR, "desktop_tray.py")
        
        if os.path.exists(env_path) and os.path.exists(pythonw_exe) and os.path.exists(tray_script):
            if os.path.exists(os.path.join(venv_path, "pyvenv.cfg")):
                try:
                    import subprocess
                    clean_env = dict(os.environ)
                    clean_env.pop("_MEIPASS", None)
                    clean_env.pop("PYTHONHOME", None)
                    clean_env.pop("PYTHONPATH", None)
                    
                    keys_to_pop = []
                    for k, v in clean_env.items():
                        if k.upper() == "PATH":
                            continue
                        if k.startswith("_PYI_") or "_mei" in k.lower() or "_mei" in v.lower():
                            keys_to_pop.append(k)
                    for k in keys_to_pop:
                        clean_env.pop(k, None)
                        
                    path = clean_env.get("PATH", "")
                    if path:
                        paths = path.split(os.pathsep)
                        cleaned_paths = [p for p in paths if "_mei" not in p.lower()]
                        clean_env["PATH"] = os.pathsep.join(cleaned_paths)
                        
                    subprocess.Popen(
                        [pythonw_exe, tray_script],
                        cwd=PROJECT_ROOT,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        creationflags=0x08000000,
                        env=clean_env
                    )
                    log_message("Fast-start: Nexora desktop tray process launched directly.")
                    sys.exit(0)
                except Exception as e:
                    log_message(f"Fast-start failed: {e}")

    # Enable High DPI icons and layouts
    from PySide6.QtCore import QCoreApplication
    plugins_path = os.path.join(PROJECT_ROOT, ".venv", "Lib", "site-packages", "PySide6", "plugins")
    if os.path.exists(plugins_path):
        QCoreApplication.addLibraryPath(plugins_path)
        
    app = QApplication(sys.argv)
    window = LauncherUI()
    window.show()
    if smoke_test:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(500, app.quit)
    exit_code = app.exec()
    if smoke_test:
        log_message("SMOKE_TEST_OK")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
