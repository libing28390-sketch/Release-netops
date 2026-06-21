# -*- coding: utf-8 -*-
"""
desktop_tray.py - System Tray & GUI Control Panel Launcher for NetOps Platform.
Spawns the FastAPI backend (Uvicorn) as a background subprocess, places a control icon in the Windows system tray,
and provides a beautiful dark-mode Tkinter GUI control panel.
"""

import sys
import os

# 1. Adapt streams for pythonw.exe environment early to redirect all output to log file
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_ROOT, "desktop_tray.log")

import logging
import socket
import time
import threading
import webbrowser
import subprocess
import atexit
import ctypes
import pystray
from PIL import Image, ImageDraw, ImageFont, ImageTk
import tkinter as tk
from tkinter import font as tkfont

# Configure logger with FileHandler
logger = logging.getLogger("desktop_tray")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Also add StreamHandler if running with python.exe (with console)
is_pythonw = sys.executable.lower().endswith("pythonw.exe")
if not is_pythonw and sys.stdout is not None:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Stream redirector to log stdout/stderr to file independently of logging module to avoid recursion
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

APP_URL = "http://127.0.0.1:5010"
tray_icon = None
backend_process = None
process_lock = threading.Lock()
root = None
gui_app = None
button_images = {}
card_bg_image = None

def get_button_image(text, width, height, radius, bg_hex, text_hex, font_size=11, border_hex=None, border_width=1):
    """Generates a rounded rectangle button image using Pillow and returns a PhotoImage."""
    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        
    bg_color = hex_to_rgb(bg_hex)
    text_color = hex_to_rgb(text_hex)
    border_color = hex_to_rgb(border_hex) if border_hex else None
    
    # 2x supersampling for high-quality antialiasing
    scale = 2
    w = width * scale
    h = height * scale
    r = radius * scale
    
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw rounded rect
    if border_color and border_width > 0:
        bw = border_width * scale
        draw.rounded_rectangle([0, 0, w, h], radius=r, fill=bg_color, outline=border_color, width=bw)
    else:
        draw.rounded_rectangle([0, 0, w, h], radius=r, fill=bg_color)
        
    # Downsample
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    
    # Draw text on resized image
    draw_crisp = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("msyh.ttc", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
            
    try:
        bbox = draw_crisp.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = draw_crisp.textsize(text, font=font)
        
    x = (width - text_w) // 2
    y = (height - text_h) // 2 - 2
    draw_crisp.text((x, y), text, fill=text_color, font=font)
    
    return ImageTk.PhotoImage(img)

def get_card_background_image(width, height, radius, bg_hex, border_hex=None, border_width=1):
    """Generates a rounded card background image using Pillow and returns a PhotoImage."""
    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
        
    bg_color = hex_to_rgb(bg_hex)
    border_color = hex_to_rgb(border_hex) if border_hex else None
    
    scale = 2
    w = width * scale
    h = height * scale
    r = radius * scale
    
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    if border_color and border_width > 0:
        bw = border_width * scale
        draw.rounded_rectangle([0, 0, w, h], radius=r, fill=bg_color, outline=border_color, width=bw)
    else:
        draw.rounded_rectangle([0, 0, w, h], radius=r, fill=bg_color)
        
    img = img.resize((width, height), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img)

def init_button_assets():
    """Initializes and caches all button and panel image assets once Tkinter is active."""
    global button_images, card_bg_image
    
    btn_w, btn_h, radius = 195, 40, 8
    buttons_config = {
        "start": {
            "text": "Start Service",
            "normal_bg": "#0284c7", "hover_bg": "#0369a1", "active_bg": "#075985",
            "text_color": "#ffffff"
        },
        "stop": {
            "text": "Stop Service",
            "normal_bg": "#e11d48", "hover_bg": "#be123c", "active_bg": "#9f1239",
            "text_color": "#ffffff"
        },
        "restart": {
            "text": "Restart Service",
            "normal_bg": "#334155", "hover_bg": "#475569", "active_bg": "#1e293b",
            "text_color": "#ffffff"
        },
        "open": {
            "text": "Open Console",
            "normal_bg": "#059669", "hover_bg": "#047857", "active_bg": "#065f46",
            "text_color": "#ffffff"
        }
    }
    
    # Common disabled style
    disabled_bg = "#111827"
    disabled_text = "#374151"
    disabled_border = "#1f2937"
    
    for key, cfg in buttons_config.items():
        button_images[f"{key}_normal"] = get_button_image(
            cfg["text"], btn_w, btn_h, radius, cfg["normal_bg"], cfg["text_color"], font_size=11
        )
        button_images[f"{key}_hover"] = get_button_image(
            cfg["text"], btn_w, btn_h, radius, cfg["hover_bg"], cfg["text_color"], font_size=11
        )
        button_images[f"{key}_active"] = get_button_image(
            cfg["text"], btn_w, btn_h, radius, cfg["active_bg"], cfg["text_color"], font_size=11
        )
        button_images[f"{key}_disabled"] = get_button_image(
            cfg["text"], btn_w, btn_h, radius, disabled_bg, disabled_text, font_size=11, border_hex=disabled_border
        )
        
    card_bg_image = get_card_background_image(420, 95, 10, "#111827", "#1f2937", 1)

def set_dark_title_bar(window):
    """Sets the title bar of the window to dark mode on Windows 10/11 using DWM API."""
    if sys.platform != "win32":
        return
    try:
        window.update()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # Try DWMWA_USE_IMMERSIVE_DARK_MODE (attribute 20)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception as e:
        logger.error("Failed to set dark title bar: %s", e)

def get_python_executable():
    """Always returns the virtual environment's python.exe to ensure all dependencies are present."""
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    # Fallback to sys.executable if venv python is not found
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-9] + "python.exe"
    return exe

def is_backend_running():
    global backend_process
    with process_lock:
        return backend_process is not None and backend_process.poll() is None

def start_backend():
    global backend_process
    with process_lock:
        if backend_process is not None and backend_process.poll() is None:
            logger.info("Backend is already running.")
            return True
        
        logger.info("Starting backend FastAPI server via subprocess...")
        try:
            python_exe = get_python_executable()
            cmd = [
                python_exe, "-m", "uvicorn", "backend.main:app",
                "--host", "127.0.0.1",
                "--port", "5010",
                "--log-level", "warning"
            ]
            
            # Setup environment variables to include 'backend' directory in PYTHONPATH
            env = os.environ.copy()
            backend_dir = os.path.join(PROJECT_ROOT, "backend")
            if "PYTHONPATH" in env:
                env["PYTHONPATH"] = backend_dir + os.pathsep + env["PYTHONPATH"]
            else:
                env["PYTHONPATH"] = backend_dir
                
            creationflags = 0
            if sys.platform == 'win32':
                # CREATE_NO_WINDOW
                creationflags = 0x08000000
                
            backend_process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags
            )
            logger.info("Backend process started with PID: %d", backend_process.pid)
            
            # Update UI state
            update_status("Running")
            show_notification("NetOps backend server started successfully.", "NetOps")
            
            # Open browser asynchronously in a thread to prevent blocking
            def auto_open():
                time.sleep(1.5)
                open_browser()
            threading.Thread(target=auto_open, daemon=True).start()
            
            return True
        except Exception as e:
            logger.exception("Failed to start backend subprocess:")
            show_notification(f"Failed to start backend: {e}", "Error")
            return False

def stop_backend():
    global backend_process
    with process_lock:
        if backend_process is None:
            logger.info("Backend is not running.")
            return True
        
        logger.info("Stopping backend process (PID: %d)...", backend_process.pid)
        try:
            if sys.platform == 'win32':
                # Use taskkill /F /T to kill the process and all its children
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(backend_process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 # CREATE_NO_WINDOW
                )
            else:
                backend_process.terminate()
                try:
                    backend_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Backend process did not terminate, force killing...")
                    backend_process.kill()
                    backend_process.wait()
            logger.info("Backend process stopped.")
            backend_process = None
            
            # Update UI state
            update_status("Stopped")
            show_notification("NetOps backend server stopped.", "NetOps")
            return True
        except Exception as e:
            logger.exception("Error stopping backend process:")
            show_notification(f"Failed to stop backend: {e}", "Error")
            return False

def restart_backend():
    logger.info("Restarting backend...")
    show_notification("NetOps backend server is restarting...", "NetOps")
    stop_backend()
    time.sleep(1.0)
    return start_backend()

@atexit.register
def cleanup_backend():
    """Ensure the backend is stopped when the tray application exits."""
    global backend_process
    if backend_process is not None and backend_process.poll() is None:
        try:
            if sys.platform == 'win32':
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(backend_process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 # CREATE_NO_WINDOW
                )
            else:
                backend_process.terminate()
                backend_process.wait(timeout=2)
        except Exception:
            try:
                backend_process.kill()
            except Exception:
                pass

def update_status(status_str):
    """Updates the tray icon tooltip and the GUI panel status."""
    global tray_icon, gui_app, root
    if tray_icon is not None:
        try:
            tray_icon.title = f"NetOps ({status_str})"
        except Exception as e:
            logger.error("Failed to update tray status: %s", e)
            
    if gui_app is not None and root is not None:
        try:
            root.after(0, gui_app.update_ui_state)
        except Exception:
            pass

def show_notification(message, title="NetOps"):
    """Shows a balloon/toast notification in a background thread to prevent blocking."""
    global tray_icon
    if tray_icon is not None:
        def do_notify():
            try:
                tray_icon.notify(message, title)
            except Exception as e:
                logger.error("Failed to show notification: %s", e)
        threading.Thread(target=do_notify, daemon=True).start()

def open_browser():
    """Opens the browser to the web app."""
    logger.info("Opening web browser to %s", APP_URL)
    webbrowser.open(APP_URL)

def create_icon_image():
    """Generates the tray icon programmatically in memory to ensure perfect Win32 compatibility."""
    try:
        # Create a 256x256 RGBA image (transparent background)
        img = Image.new('RGBA', (256, 256), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Slate base rounded rectangle
        draw.rounded_rectangle([16, 16, 240, 240], radius=48, fill=(30, 41, 59, 255))
        
        # Glow blue ring
        draw.ellipse([48, 48, 208, 208], outline=(59, 130, 246, 255), width=8)
        
        # Connection lines
        draw.line([(128, 90), (85, 175)], fill=(99, 102, 241, 255), width=8)
        draw.line([(128, 90), (171, 175)], fill=(99, 102, 241, 255), width=8)
        draw.line([(85, 175), (171, 175)], fill=(99, 102, 241, 255), width=8)
        
        # Node circles
        draw.ellipse([108, 70, 148, 110], fill=(14, 165, 233, 255))   # Cyan/Blue top node
        draw.ellipse([65, 155, 105, 195], fill=(34, 197, 94, 255))    # Green left node
        draw.ellipse([151, 155, 191, 195], fill=(168, 85, 247, 255))  # Purple right node
        
        # Resize to 64x64 using Lanczos for clean antialiasing
        return img.resize((64, 64), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.error("Error creating icon image, falling back: %s", e)
        # Fallback simple square image
        img = Image.new('RGB', (64, 64), color=(30, 41, 59))
        draw = ImageDraw.Draw(img)
        draw.rectangle([16, 16, 48, 48], fill=(59, 130, 246))
        return img

def on_open_panel(icon, item):
    if gui_app is not None and root is not None:
        root.after(0, gui_app.show_window)

def on_open_browser(icon, item):
    open_browser()

def on_start(icon, item):
    start_backend()

def on_stop(icon, item):
    stop_backend()

def on_restart(icon, item):
    restart_backend()

def on_exit(icon, item):
    logger.info("Exiting desktop tray application")
    stop_backend()
    icon.stop()
    if root is not None:
        try:
            root.after(0, root.destroy)
        except Exception:
            pass
    sys.exit(0)

def setup_tray(icon):
    """Callback after the tray icon runs."""
    icon.visible = True
    time.sleep(1.0)
    update_status("Stopped")

_instance_socket = None

def check_single_instance():
    """Binds to a specific local loopback port to prevent multiple tray instances from running.
    Uses a connection check first to bypass socket TIME_WAIT limits on Windows."""
    global _instance_socket
    # 1. Try to connect to see if another instance is actively listening
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1.0)
        test_sock.connect(("127.0.0.1", 5019))
        test_sock.sendall("SHOW_GUI".encode("utf-8"))
        test_sock.close()
        # Connection succeeded and signal sent -> another instance is actively running!
        return False
    except socket.error:
        # Connection failed -> no active listener is running
        pass

    # 2. Try to bind to become the listener for future instances
    try:
        _instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _instance_socket.bind(("127.0.0.1", 5019))
        _instance_socket.listen(5)
    except socket.error as e:
        logger.error("Failed to bind instance socket: %s", e)
        _instance_socket = None
    return True

def socket_listener():
    global _instance_socket, root, gui_app
    if _instance_socket is None:
        logger.warning("No instance socket available, socket listener thread exiting.")
        return
    while True:
        try:
            conn, addr = _instance_socket.accept()
            data = conn.recv(1024).decode("utf-8")
            conn.close()
            if data == "SHOW_GUI":
                if gui_app is not None and root is not None:
                    root.after(0, gui_app.show_window)
        except Exception:
            break

class NetOpsGUI:
    def __init__(self, root_win):
        self.root = root_win
        self.root.title("NetOps Service Panel")
        self.root.configure(bg="#090d16")
        self.root.resizable(False, False)
        
        # Center the window
        width, height = 480, 390
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
        # Set window icon if available
        ico_path = os.path.join(PROJECT_ROOT, "netops.ico")
        if os.path.exists(ico_path):
            try:
                self.root.iconbitmap(ico_path)
            except Exception:
                pass
                
        # Intercept close window to minimize to tray
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        # Custom Fonts
        self.title_font = tkfont.Font(family="Microsoft YaHei", size=15, weight="bold")
        self.normal_font = tkfont.Font(family="Microsoft YaHei", size=10)
        self.status_font = tkfont.Font(family="Microsoft YaHei", size=11, weight="bold")
        self.detail_font = tkfont.Font(family="Microsoft YaHei", size=9)
        
        # Build layout
        self.create_widgets()
        self.update_ui_state()

    def create_widgets(self):
        # 1. Header Frame
        header_frame = tk.Frame(self.root, bg="#090d16")
        header_frame.pack(fill="x", padx=30, pady=(22, 5))
        
        # Accent Bar (Visual highlight)
        accent_bar = tk.Frame(header_frame, width=4, bg="#0284c7")
        accent_bar.pack(side="left", fill="y", padx=(0, 12))
        
        title_text_frame = tk.Frame(header_frame, bg="#090d16")
        title_text_frame.pack(side="left", fill="both", expand=True)
        
        title_lbl = tk.Label(title_text_frame, text="NetOps Control Panel", font=self.title_font, fg="#f8fafc", bg="#090d16")
        title_lbl.pack(anchor="w")
        
        subtitle_lbl = tk.Label(title_text_frame, text="Automation Platform Service Manager", font=self.normal_font, fg="#4b5563", bg="#090d16")
        subtitle_lbl.pack(anchor="w", pady=(2, 0))
        
        # 2. Status Canvas
        self.status_canvas = tk.Canvas(self.root, width=420, height=95, bg="#090d16", highlightthickness=0)
        self.status_canvas.pack(fill="x", padx=30, pady=(15, 15))
        
        # 3. Buttons Grid Frame
        btn_frame = tk.Frame(self.root, bg="#090d16")
        btn_frame.pack(fill="x", padx=30, pady=(5, 15))
        
        self.btn_start = self.create_image_button(btn_frame, "start", self.on_start_click)
        self.btn_start.grid(row=0, column=0, padx=(0, 10), pady=(0, 12), sticky="nsew")
        
        self.btn_stop = self.create_image_button(btn_frame, "stop", self.on_stop_click)
        self.btn_stop.grid(row=0, column=1, padx=(10, 0), pady=(0, 12), sticky="nsew")
        
        self.btn_restart = self.create_image_button(btn_frame, "restart", self.on_restart_click)
        self.btn_restart.grid(row=1, column=0, padx=(0, 10), pady=(0, 0), sticky="nsew")
        
        self.btn_open = self.create_image_button(btn_frame, "open", self.on_open_click)
        self.btn_open.grid(row=1, column=1, padx=(10, 0), pady=(0, 0), sticky="nsew")
        
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        
        # 4. Footer Frame (packed at the bottom with explicit padding)
        footer_frame = tk.Frame(self.root, bg="#090d16")
        footer_frame.pack(fill="x", padx=30, pady=(15, 10))
        
        copyright_lbl = tk.Label(footer_frame, text="Copyright © 2026 NetOps", font=self.normal_font, fg="#4b5563", bg="#090d16")
        copyright_lbl.pack(side="left")
        
        self.btn_exit_all = tk.Button(
            footer_frame,
            text="Exit App",
            command=self.on_exit_all_click,
            font=self.normal_font,
            fg="#e11d48",
            bg="#090d16",
            activeforeground="#be123c",
            activebackground="#090d16",
            bd=0,
            cursor="hand2",
            padx=0,
            pady=0,
            underline=True
        )
        self.btn_exit_all.pack(side="right")

    def create_image_button(self, parent, key, command):
        btn = tk.Button(
            parent,
            image=button_images[f"{key}_normal"],
            command=command,
            bd=0,
            highlightthickness=0,
            relief="flat",
            activebackground="#090d16",
            bg="#090d16",
            cursor="hand2"
        )
        
        btn.state_key = key
        btn.is_enabled = True
        
        def on_enter(e):
            if btn.is_enabled:
                btn.config(image=button_images[f"{btn.state_key}_hover"])
                
        def on_leave(e):
            if btn.is_enabled:
                btn.config(image=button_images[f"{btn.state_key}_normal"])
                
        def on_press(e):
            if btn.is_enabled:
                btn.config(image=button_images[f"{btn.state_key}_active"])
                
        def on_release(e):
            if btn.is_enabled:
                btn.config(image=button_images[f"{btn.state_key}_hover"])
                
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        
        return btn

    def set_button_state(self, btn, enabled):
        btn.is_enabled = enabled
        if enabled:
            btn.config(state="normal", image=button_images[f"{btn.state_key}_normal"])
        else:
            btn.config(state="disabled", image=button_images[f"{btn.state_key}_disabled"])

    def update_ui_state(self):
        running = is_backend_running()
        
        self.status_canvas.delete("all")
        
        # Draw the card background image
        self.status_canvas.create_image(0, 0, image=card_bg_image, anchor="nw")
        
        # Draw "Service Status" label
        self.status_canvas.create_text(25, 26, text="Service Status:", font=self.normal_font, fill="#94a3b8", anchor="w")
        
        # Draw Status Dot & State
        dot_color = "#10b981" if running else "#e11d48"
        state_text = "RUNNING" if running else "STOPPED"
        state_color = "#10b981" if running else "#e11d48"
        
        # Status Dot (x=135, y=26, radius=5)
        self.status_canvas.create_oval(130, 21, 140, 31, fill=dot_color, outline="")
        
        # Status State Text
        self.status_canvas.create_text(150, 26, text=state_text, font=self.status_font, fill=state_color, anchor="w")
        
        # Draw details
        detail_text = "Listening on http://127.0.0.1:5010" if running else "All backend processes are inactive"
        detail_color = "#4b5563"
        self.status_canvas.create_text(25, 64, text=detail_text, font=self.detail_font, fill=detail_color, anchor="w")
        
        # Update buttons
        self.set_button_state(self.btn_start, not running)
        self.set_button_state(self.btn_stop, running)
        self.set_button_state(self.btn_restart, running)
        self.set_button_state(self.btn_open, running)

    def on_start_click(self):
        start_backend()
        self.update_ui_state()

    def on_stop_click(self):
        stop_backend()
        self.update_ui_state()

    def on_restart_click(self):
        restart_backend()
        self.update_ui_state()

    def on_open_click(self):
        open_browser()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        self.root.withdraw()
        show_notification("NetOps Control Panel is minimized to system tray.", "NetOps")

    def on_exit_all_click(self):
        logger.info("Exiting application from GUI panel")
        stop_backend()
        if tray_icon is not None:
            tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

def run_tray():
    global tray_icon
    tray_icon.run(setup=setup_tray)

def main():
    logger.info("Starting NetOps System Tray Launcher")

    if not check_single_instance():
        logger.info("Another instance of NetOps tray launcher is already running. Sent SHOW_GUI signal and exiting...")
        sys.exit(0)

    # Start socket listener thread
    threading.Thread(target=socket_listener, daemon=True).start()

    # Load custom icon
    icon_image = create_icon_image()

    global tray_icon, root, gui_app
    menu = pystray.Menu(
        pystray.MenuItem("显示控制面板 (Open Panel)", on_open_panel, default=True),
        pystray.MenuItem("打开网页系统 (Open System)", on_open_browser),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("启动服务 (Start Service)", on_start, enabled=lambda item: not is_backend_running()),
        pystray.MenuItem("停止服务 (Stop Service)", on_stop, enabled=lambda item: is_backend_running()),
        pystray.MenuItem("重启服务 (Restart Service)", on_restart, enabled=lambda item: is_backend_running()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出 (Exit)", on_exit)
    )
    
    tray_icon = pystray.Icon(
        "NetOps",
        icon_image,
        "NetOps",
        menu=menu
    )
    
    # Start pystray in a background thread
    threading.Thread(target=run_tray, daemon=True).start()

    # Start Tkinter GUI on the main thread
    root = tk.Tk()
    
    # Enable dark title bar on Windows
    set_dark_title_bar(root)
    
    # Initialize UI assets
    init_button_assets()
    
    gui_app = NetOpsGUI(root)
    root.mainloop()

if __name__ == '__main__':
    if sys.platform == 'win32':
        import multiprocessing
        multiprocessing.freeze_support()
    main()
