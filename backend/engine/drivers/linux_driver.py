import time
import paramiko
import socket
from typing import Dict, Any, Tuple
from .base_driver import BaseDriver
from ..base import Capability, ExecutionMode
from ..pool import ConnectionPool
from ..registry import DriverRegistry

@DriverRegistry.register("server")
class LinuxDriver(BaseDriver):
    """基于 Paramiko 的 Linux 高级驱动"""
    
    def __init__(self, device_info: Dict[str, Any]):
        super().__init__(device_info)
        self.ssh = None
        self.capabilities = {
            Capability.EXEC_COMMAND, 
            Capability.EXEC_SCRIPT, 
            Capability.UPLOAD_FILE
        }

    def connect(self):
        use_pool = self.device_info.get('use_pool', True)
        if use_pool:
            pool = ConnectionPool()
            existing = pool.get_connection(self.device_info)
            
            if existing and existing.get_transport() and existing.get_transport().is_active():
                self.ssh = existing
                return

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.ip, port=self.port, username=self.username,
            password=self.password, timeout=10, allow_agent=False, look_for_keys=False,
            disabled_algorithms={},
        )
        if use_pool:
            pool.set_connection(self.device_info, self.ssh)

    def disconnect(self):
        pass

    def _run_raw(self, command: str, use_sudo: bool = False, timeout: int = 60) -> Tuple[int, str, str]:
        if use_sudo:
            command = f"sudo -S -p '' {command}"
        
        transport = self.ssh.get_transport()
        chan = transport.open_session()
        chan.settimeout(timeout)
        chan.exec_command(command)

        if use_sudo:
            stdin = chan.makefile('wb', -1)
            # FIX: Must encode string to bytes for binary stream
            stdin.write(f"{self.password}\n".encode('utf-8'))
            stdin.flush()

        stdout = chan.makefile('r', -1).read().decode('utf-8', 'ignore')
        stderr = chan.makefile_stderr('r', -1).read().decode('utf-8', 'ignore')
        exit_status = chan.recv_exit_status()
        
        return exit_status, stdout, stderr

    def execute(self, mode: ExecutionMode, content: str, **kwargs) -> Dict[str, Any]:
        start_time = time.perf_counter()
        use_sudo = kwargs.get("sudo", False)
        timeout = kwargs.get("timeout", 60)
        
        try:
            self.connect()
            
            # Ensure content is a string (if list was passed, join it)
            final_cmd = content
            if isinstance(content, list):
                final_cmd = "\n".join(content)
                
            if mode == ExecutionMode.SCRIPT:
                final_cmd = f"bash << 'EOF'\n{final_cmd}\nEOF"
            
            exit_code, stdout, stderr = self._run_raw(final_cmd, use_sudo, timeout)
            success = (exit_code == 0)
            
            return {
                "success": success, "stdout": stdout, "stderr": stderr,
                "exit_code": exit_code, "device": self.ip,
                "duration": time.perf_counter() - start_time
            }
            
        except socket.timeout:
            return {"success": False, "stderr": "Execution Timeout", "exit_code": 124, "device": self.ip, "duration": 60}
        except Exception as e:
            return {"success": False, "stderr": str(e), "exit_code": 1, "device": self.ip, "duration": 0}
