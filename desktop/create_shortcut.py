# -*- coding: utf-8 -*-
"""
create_shortcut.py - Creates a Windows Desktop Shortcut for NetOps.
Generates a custom .ico file and sets up a desktop shortcut using PowerShell.
"""

import os
import sys
import subprocess
from PIL import Image, ImageDraw

DESKTOP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(DESKTOP_DIR)
ICO_PATH = os.path.join(DESKTOP_DIR, "netops.ico")
TRAY_SCRIPT = os.path.join(DESKTOP_DIR, "desktop_tray.py")
PYTHONW_PATH = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "pythonw.exe")

def generate_ico_file():
    """Generates a high-quality multi-resolution .ico file using Pillow."""
    print("Generating custom application icon...")
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
        
        # Save as ICO with multiple sizes for Windows Explorer
        img.save(ICO_PATH, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        print(f"[OK] Icon file generated at: {ICO_PATH}")
        return True
    except Exception as e:
        print(f"[Error] Failed to generate icon: {e}")
        return False

def create_desktop_shortcut():
    """Creates a Windows Desktop Shortcut pointing to desktop_tray.py using pythonw.exe."""
    # 1. Verify virtual environment pythonw.exe exists
    if not os.path.exists(PYTHONW_PATH):
        print(f"[Error] Virtual environment pythonw.exe not found at: {PYTHONW_PATH}")
        print("Please make sure the virtual environment (.venv) is installed and active first.")
        return False
        
    # 2. Verify desktop_tray.py exists
    if not os.path.exists(TRAY_SCRIPT):
        print(f"[Error] Launcher script not found at: {TRAY_SCRIPT}")
        return False

    print("Creating Windows Desktop Shortcut...")
    
    # Get user desktop path
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    shortcut_path = os.path.join(desktop_path, "NetOps 运维平台.lnk")
    
    # Use temporary VBScript to create the shortcut (more reliable/lightweight than PowerShell on Windows)
    vbs_path = os.path.join(PROJECT_ROOT, "temp_create_shortcut.vbs")
    
    # Escape quotes inside VBScript string
    vbs_content = f"""Set WshShell = CreateObject("WScript.Shell")
Set Shortcut = WshShell.CreateShortcut("{shortcut_path}")
Shortcut.TargetPath = "{PYTHONW_PATH}"
Shortcut.Arguments = """ + '"' + f'""{TRAY_SCRIPT}""' + '"' + f"""
Shortcut.WorkingDirectory = "{PROJECT_ROOT}"
Shortcut.IconLocation = "{ICO_PATH}"
Shortcut.Description = "NetOps 自动化运维平台"
Shortcut.Save()
"""
    
    try:
        # Write VBScript in UTF-16 (with BOM) to guarantee perfect Unicode support in Windows Script Host
        vbs_encoding = "utf-16"
        with open(vbs_path, "w", encoding=vbs_encoding) as f:
            f.write(vbs_content)
            
        result = subprocess.run(
            ["cscript.exe", "/nologo", vbs_path],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Clean up temporary VBScript
        if os.path.exists(vbs_path):
            os.remove(vbs_path)
            
        if result.returncode == 0:
            print(f"[OK] Desktop Shortcut successfully created at: {shortcut_path}")
            # Clean up old corrupted shortcuts if they exist
            try:
                for filename in os.listdir(desktop_path):
                    if filename.endswith(".lnk") and "NetOps" in filename:
                        if filename != "NetOps 运维平台.lnk":
                            os.remove(os.path.join(desktop_path, filename))
                            print(f"[Cleaned] Removed corrupted shortcut: {filename}")
            except Exception:
                pass
            return True
        else:
            print(f"[Error] VBScript failed: {result.stderr}")
            return False
    except Exception as e:
        if os.path.exists(vbs_path):
            try:
                os.remove(vbs_path)
            except Exception:
                pass
        print(f"[Error] Failed to create shortcut: {e}")
        return False

if __name__ == "__main__":
    # Ensure dependencies are met
    generate_ico_file()
    create_desktop_shortcut()
