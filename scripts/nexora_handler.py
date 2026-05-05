import sys
import webbrowser
import subprocess
import os
import json
from urllib.parse import urlparse, parse_qs

# Configuration: You can modify these paths or let the script find them
CLIENT_PATHS = {
    'xshell': r"C:\Program Files (x86)\NetSarang\Xshell 7\Xshell.exe",
    'putty': r"putty.exe", # Assumes in PATH
    'securecrt': r"C:\Program Files\VanDyke Software\SecureCRT\SecureCRT.exe"
}

def handle_url(url):
    try:
        parsed = urlparse(url)
        # nexora://<ip_address>?user=xxx&role=xxx&client=xxx
        ip = parsed.netloc
        params = parse_qs(parsed.query)
        
        user = params.get('user', ['admin'])[0]
        client_type = params.get('client', ['xshell'])[0].lower()
        
        print(f"Connecting to {ip} as {user} using {client_type}...")
        
        if client_type == 'xshell':
            # Xshell command: xshell.exe -url ssh://user:pwd@host
            # Since we don't pass password in URL for security, user will be prompted or uses saved session
            cmd = [CLIENT_PATHS['xshell'], f"ssh://{user}@{ip}"]
            subprocess.Popen(cmd)
            
        elif client_type == 'putty':
            cmd = [CLIENT_PATHS['putty'], "-ssh", f"{user}@{ip}"]
            subprocess.Popen(cmd)
            
        else:
            # Default to default SSH handler if unknown
            webbrowser.open(f"ssh://{user}@{ip}")
            
    except Exception as e:
        with open("nexora_error.log", "a") as f:
            f.write(f"Error handling {url}: {str(e)}\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        handle_url(sys.argv[1])
    else:
        print("Nexora Protocol Handler Active. Usage: nexora://<ip>?user=<user>")
