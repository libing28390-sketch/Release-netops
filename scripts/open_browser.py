import socket
import time
import webbrowser
import sys

def wait_and_open(url, host, port, timeout=10.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Try to connect to the port
            with socket.create_connection((host, port), timeout=0.5):
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(0.2)
    # If timeout, open it anyway
    webbrowser.open(url)

if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5010"
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 5010
    wait_and_open(url, host, port)
