import time
from typing import Dict, Any
from netmiko import ConnectHandler
from .base_driver import BaseDriver
from ..base import Capability, ExecutionMode
from ..pool import ConnectionPool
from ..registry import DriverRegistry

@DriverRegistry.register("network")
class NetmikoDriver(BaseDriver):
    """基于 Netmiko 的网络设备驱动"""
    
    def __init__(self, device_info: Dict[str, Any]):
        super().__init__(device_info)
        # Apply strict vendor/platform mapping to prevent silent Cisco fallback
        from core.platform_utils import normalize_device_platform
        self.platform = normalize_device_platform(device_info.get("vendor"), self.platform)
        self.device_type = self._map_device_type(self.platform)
        self.secret = device_info.get("enable_password") or ""
        self.conn = None
        self.capabilities = {Capability.EXEC_COMMAND, Capability.SEND_CONFIG}

    def _map_device_type(self, platform: str) -> str:
        p = str(platform or '').lower().strip()
        aliases = {
            'cisco': 'cisco_ios',
            'ios': 'cisco_ios',
            'iosxe': 'cisco_ios',
            'cisco_iosxe': 'cisco_ios',
            'cisco_xe': 'cisco_ios',
            'nxos': 'cisco_nxos',
            'nexus': 'cisco_nxos',
            'h3c': 'h3c_comware',
            'comware': 'h3c_comware',
            'hp_comware': 'h3c_comware',
            'h3c_comware9': 'h3c_comware',
            'huawei': 'huawei_vrp',
            'huawei_vrpv8': 'huawei_vrp',
            'vrp': 'huawei_vrp',
            'ce': 'huawei_vrp',
            'ce_vrp': 'huawei_vrp',
            'ne': 'huawei_vrp',
            '\u534e\u4e3avrp': 'huawei_vrp',
            'juniper': 'juniper_junos',
            'junos': 'juniper_junos',
            'arista': 'arista_eos',
            'eos': 'arista_eos',
            'ruijie': 'ruijie_rgos',
            'ruijie_os': 'ruijie_rgos',
            'rgos': 'ruijie_rgos',
            'zte': 'zte_zxros',
            'zxros': 'zte_zxros',
            'maipu_network': 'maipu',
        }
        p = aliases.get(p, p)
        mapping = {
            'cisco_ios': 'cisco_ios',
            'huawei_vrp': 'huawei',
            'h3c_comware': 'hp_comware',
            'juniper_junos': 'juniper_junos',
            'arista_eos': 'arista_eos',
            'ruijie_rgos': 'ruijie_os',
            'zte_zxros': 'zte_zxros',
            'maipu': 'maipu',
        }
        return mapping.get(p) or p or 'cisco_ios'

    def connect(self):
        use_pool = self.device_info.get('use_pool', True)
        if use_pool:
            pool = ConnectionPool()
            existing = pool.get_connection(self.device_info)
            
            if existing and hasattr(existing, 'is_alive'):
                try:
                    if existing.is_alive():
                        self.conn = existing
                        return
                except Exception:
                    # Connection is dead (e.g. OSError: Socket is closed)
                    pass

        # Resolve enable secret: explicit field → admin password → login password
        # For accounts with privilege 15, enable() is a no-op but Netmiko still
        # needs a secret set so it can call enable() to confirm the '#' prompt.
        from core.crypto import decrypt_credential as _dec
        enable_pwd = (
            _dec(self.device_info.get('enable_password') or '') or
            self.device_info.get('enable_password') or  # already plaintext
            _dec(self.device_info.get('admin_password') or '') or
            self.password  # last resort: use login password
        )

        from drivers.ssh_compat import build_netmiko_compatibility_kwargs
        device_params = {
            'device_type': self.device_type,
            'host': self.ip,
            'username': self.username,
            'password': self.password,
            'port': self.port,
            'secret': enable_pwd or self.password,
            'timeout': 20,
            'global_delay_factor': 1.5,
            'blocking_timeout': 30,
        }
        device_params.update(build_netmiko_compatibility_kwargs())
        self.conn = ConnectHandler(**device_params)
        # Always call enable() for Cisco devices so Netmiko's internal state
        # is set to privilege exec ('#'). For privilege-15 accounts this is a
        # no-op; for privilege-1 accounts it uses the secret to elevate.
        # If enable() fails (wrong secret or account lacks privilege), we
        # continue anyway — show commands work fine at '>' level.
        if self.device_type in ('cisco_ios', 'cisco_nxos', 'cisco_iosxr'):
            try:
                self.conn.enable()
            except Exception:
                pass
        
        if use_pool:
            pool.set_connection(self.device_info, self.conn)

    def disconnect(self):
        pass

    def execute(self, mode: ExecutionMode, content: Any, **kwargs) -> Dict[str, Any]:
        start_time = time.perf_counter()
        try:
            self.connect()
            
            if mode == ExecutionMode.COMMAND:
                try:
                    output = self.conn.send_command(content, read_timeout=30)
                except Exception as e:
                    if "Pattern not detected" in str(e) or "Timeout" in str(e) or "socket" in str(e).lower():
                        output = self.conn.send_command_timing(content, read_timeout=30)
                    else:
                        raise e
                from drivers.ssh_compat import drain_paged_output
                output = drain_paged_output(self.conn, output, read_timeout=30)
                return {
                    "success": True, "stdout": output, "device": self.ip,
                    "duration": time.perf_counter() - start_time
                }
            
            elif mode == ExecutionMode.CONFIG:
                config_lines = content if isinstance(content, list) else content.splitlines()
                output = self.conn.send_config_set(config_lines)
                return {
                    "success": True, "stdout": output, "device": self.ip,
                    "duration": time.perf_counter() - start_time
                }
            
            return {"success": False, "stderr": f"Mode {mode} not supported", "device": self.ip, "duration": 0}
        except Exception as e:
            return {
                "success": False, "stderr": str(e), "device": self.ip,
                "duration": time.perf_counter() - start_time
            }
