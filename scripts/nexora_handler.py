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

def register_protocol():
    try:
        import winreg
    except ImportError:
        show_error("winreg module not found. Registration is only supported on Windows.")
        return
    try:
        # Get path of current executable
        exe_path = os.path.abspath(sys.executable)
        if exe_path.lower().endswith(("python.exe", "pythonw.exe")):
            script_path = os.path.abspath(__file__)
            cmd_val = f'"{exe_path}" "{script_path}" "%1"'
        else:
            cmd_val = f'"{exe_path}" "%1"'
        
        # Open/create HKEY_CURRENT_USER\Software\Classes\nexora
        key_path = r"Software\Classes\nexora"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Nexora Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            
        # Create HKEY_CURRENT_USER\Software\Classes\nexora\shell\open\command
        cmd_path = r"Software\Classes\nexora\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as cmd_key:
            winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd_val)
            

        # Pop up success message box
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Nexora Terminal Assistant registered successfully!\n\nCommand: {cmd_val}",
            "Nexora Assistant",
            0x40  # MB_ICONINFORMATION
        )
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Failed to register Nexora protocol:\n{str(e)}",
            "Nexora Assistant Error",
            0x10  # MB_ICONERROR
        )

def handle_url(url):
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        client_type = params.get('client', ['xshell'])[0].lower()
        custom_path = params.get('path', [''])[0]
        
        token = params.get('token', [''])[0]
        if token:
            # Token flow: request actual connection details from the backend
            web_host = parsed.netloc
            ssl_param = params.get('ssl', ['0'])[0]
            scheme = "https" if ssl_param == "1" else "http"
            
            import urllib.request
            import json
            import ssl
            
            exchange_url = f"{scheme}://{web_host}/api/system/exchange-token?token={token}"
            
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            try:
                req = urllib.request.Request(exchange_url, headers={'User-Agent': 'NexoraAssistant/1.0'})
                with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
                    resp_data = json.loads(response.read().decode('utf-8'))
            except Exception as http_err:
                show_error(f"Failed to connect to backend at {exchange_url}:\n{str(http_err)}")
                return
                
            if not resp_data.get('success'):
                show_error(f"Token exchange failed:\n{resp_data.get('error', 'Unknown error')}")
                return
                
            ip = resp_data.get('ip')
            port = int(resp_data.get('port') or 22)
            user = resp_data.get('user')
            password = resp_data.get('password')
        else:
            # Fallback to direct credentials in URI parameters
            ip = parsed.hostname or parsed.netloc
            port = parsed.port or int(params.get('port', ['22'])[0] or 22)
            user = params.get('user', ['admin'])[0]
            password = params.get('password', [''])[0]
        
        client_path = resolve_executable(client_type, custom_path)
        
        if not client_path:
            error_msg = (
                f"Could not locate the executable for terminal client: '{client_type}'.\n"
                f"Supplied path: '{custom_path}'\n\n"
                "Please configure a valid executable path in your Profile settings on the web dashboard."
            )
            show_error(error_msg)
            return

        print(f"Connecting to {ip}:{port} as {user} using {client_type} at {client_path}...")
        
        # Construct arguments based on client type
        args = None
        if client_type == 'xshell':
            # Xshell command: xshell.exe -url ssh://user:password@host
            if password:
                args = f"-url ssh://{user}:{password}@{ip}:{port}"
            else:
                args = f"-url ssh://{user}@{ip}:{port}"
        elif client_type == 'putty':
            if password:
                args = f"-ssh {user}@{ip} -P {port} -pw \"{password}\""
            else:
                args = f"-ssh {user}@{ip} -P {port}"
        elif client_type == 'securecrt':
            if password:
                args = f"/SSH2 /L {user} /P {port} /PASSWORD \"{password}\" {ip}"
            else:
                args = f"/SSH2 /L {user} /P {port} {ip}"
        elif client_type == 'mobaxterm':
            if password:
                args = f"ssh://{user}:{password}@{ip}:{port}"
            else:
                args = f"ssh://{user}@{ip}:{port}"

        if args is not None:
            try:
                # Use ShellExecuteW for native Windows launch with proper window activation and focus,
                # which also correctly communicates with any existing open instances (e.g. to open a new tab).
                ctypes.windll.shell32.ShellExecuteW(None, "open", client_path, args, None, 1)
            except Exception as shell_err:
                # Fallback to subprocess if ShellExecuteW fails
                cmd = [client_path]
                if client_type == 'xshell':
                    cmd += ["-url", f"ssh://{user}@{ip}:{port}"]
                elif client_type == 'putty':
                    cmd += ["-ssh", f"{user}@{ip}", "-P", str(port)]
                elif client_type == 'securecrt':
                    cmd += ["/SSH2", "/L", user, "/P", str(port), ip]
                elif client_type == 'mobaxterm':
                    cmd += [f"ssh://{user}@{ip}:{port}"]
                subprocess.Popen(cmd)
        else:
            # Default fallback to standard ssh handler URL
            webbrowser.open(f"ssh://{user}@{ip}:{port}")
            
    except Exception as e:
        show_error(f"Error handling {url}:\n{str(e)}")

if __name__ == "__main__":
    # Log arguments for debugging
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nexora_debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            import datetime
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{now}] Invoked with args: {sys.argv}\n")
    except Exception as log_err:
        show_error(f"Debug logger failed: {str(log_err)}")

    if len(sys.argv) > 1:
        handle_url(sys.argv[1])
    else:
        register_protocol()
