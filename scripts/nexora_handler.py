import sys
import webbrowser
import subprocess
import os
from urllib.parse import urlparse, parse_qs
import ctypes

def show_error(message):
    """Show a Windows dialog popup box on failure, useful when running headless under pythonw"""
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "Nexora Protocol Handler Error", 0x10)
    except Exception:
        pass
    # Also log to file
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nexora_error.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass

def resolve_executable(client_type, custom_path=None):
    if custom_path:
        custom_path = custom_path.strip().strip('"').strip("'")
        if custom_path:
            # If user provided a directory path, append standard executable filename
            if os.path.isdir(custom_path):
                exe_names = {
                    'xshell': 'Xshell.exe',
                    'putty': 'putty.exe',
                    'securecrt': 'SecureCRT.exe',
                    'mobaxterm': 'MobaXterm.exe'
                }
                exe_name = exe_names.get(client_type, '')
                full_path = os.path.join(custom_path, exe_name)
                if os.path.exists(full_path):
                    return full_path
            elif os.path.exists(custom_path):
                return custom_path

    # Fallback to standard installation paths on Windows
    paths_dict = {
        'xshell': [
            r"C:\Program Files (x86)\NetSarang\Xshell 8\Xshell.exe",
            r"C:\Program Files (x86)\NetSarang\Xshell 7\Xshell.exe",
            r"C:\Program Files\NetSarang\Xshell 8\Xshell.exe",
            r"C:\Program Files\NetSarang\Xshell 7\Xshell.exe",
        ],
        'putty': [
            r"C:\Program Files\PuTTY\putty.exe",
            r"C:\Program Files (x86)\PuTTY\putty.exe",
            r"C:\Windows\System32\putty.exe",
            r"putty.exe",
        ],
        'securecrt': [
            r"C:\Program Files\VanDyke Software\SecureCRT\SecureCRT.exe",
            r"C:\Program Files (x86)\VanDyke Software\SecureCRT\SecureCRT.exe",
        ],
        'mobaxterm': [
            r"C:\Program Files (x86)\Mobatek\MobaXterm\MobaXterm.exe",
            r"C:\Program Files\Mobatek\MobaXterm\MobaXterm.exe",
        ]
    }
    
    candidates = paths_dict.get(client_type, [])
    for path in candidates:
        if path == "putty.exe":
            return path
        if os.path.exists(path):
            return path
            
    return None

def handle_url(url):
    try:
        parsed = urlparse(url)
        # nexora://<ip_address>?user=xxx&role=xxx&client=xxx&path=xxx
        ip = parsed.netloc
        params = parse_qs(parsed.query)
        
        user = params.get('user', ['admin'])[0]
        client_type = params.get('client', ['xshell'])[0].lower()
        custom_path = params.get('path', [''])[0]
        
        client_path = resolve_executable(client_type, custom_path)
        
        if not client_path:
            error_msg = (
                f"Could not locate the executable for terminal client: '{client_type}'.\n"
                f"Supplied path: '{custom_path}'\n\n"
                "Please configure a valid executable path in your Profile settings on the web dashboard."
            )
            show_error(error_msg)
            return

        print(f"Connecting to {ip} as {user} using {client_type} at {client_path}...")
        
        if client_type == 'xshell':
            # Xshell command: xshell.exe -url ssh://user@host
            cmd = [client_path, f"ssh://{user}@{ip}"]
            subprocess.Popen(cmd)
            
        elif client_type == 'putty':
            cmd = [client_path, "-ssh", f"{user}@{ip}"]
            subprocess.Popen(cmd)
            
        elif client_type == 'securecrt':
            cmd = [client_path, "/SSH2", "/L", user, ip]
            subprocess.Popen(cmd)
            
        elif client_type == 'mobaxterm':
            cmd = [client_path, f"ssh://{user}@{ip}"]
            subprocess.Popen(cmd)
            
        else:
            # Default fallback to standard ssh handler URL
            webbrowser.open(f"ssh://{user}@{ip}")
            
    except Exception as e:
        show_error(f"Error handling {url}:\n{str(e)}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        handle_url(sys.argv[1])
    else:
        print("Nexora Protocol Handler Active. Usage: nexora://<ip>?user=<user>&client=<xshell|putty|securecrt>&path=<path>")

