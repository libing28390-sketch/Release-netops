import time
from typing import Dict, Any
try:
    from netmiko import ConnectHandler
    from drivers.ssh_compat import ensure_netmiko_custom_platforms
    ensure_netmiko_custom_platforms()
except ImportError:
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
        self.secret = device_info.get("enable_password") or device_info.get("secret") or ""
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
            'raisecom': 'raisecom_ros',
            '瑞斯康达': 'raisecom_ros',
            'maipu_network': 'maipu',
            'dptech': 'dptech_ios',
            'dptech_ios': 'dptech_ios',
            'dptech_conplat': 'dptech_ios',
            'dptech_conplat_fw': 'dptech_ios',
        }
        p = aliases.get(p, p)
        mapping = {
            'cisco_ios': 'cisco_ios',
            'huawei_vrp': 'huawei',
            'h3c_comware': 'hp_comware',
            'h3c_comware_v3': 'hp_comware',
            'juniper_junos': 'juniper_junos',
            'arista_eos': 'arista_eos',
            'ruijie_rgos': 'ruijie_os',
            'zte_zxros': 'zte_zxros',
            'raisecom_ros': 'raisecom_ros',
            'maipu': 'maipu',
            'dptech_ios': 'dptech_ios',
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

        # Resolve only an explicitly configured Enable secret. Login/admin
        # passwords are not valid implicit Enable secrets.
        from core.crypto import decrypt_credential as _dec
        raw_enable_pwd = self.device_info.get('enable_password') or self.device_info.get('secret') or ''
        enable_pwd = (
            _dec(raw_enable_pwd) or
            raw_enable_pwd
        )

        from drivers.ssh_compat import build_netmiko_compatibility_kwargs
        requested_timeout = self.device_info.get('timeout') or self.device_info.get('conn_timeout') or 60
        try:
            conn_timeout = max(60, int(float(requested_timeout)))
        except (TypeError, ValueError):
            conn_timeout = 60
        blocking_timeout = max(60, int(self.device_info.get('blocking_timeout') or 60))
        device_params = {
            'device_type': self.device_type,
            'host': self.ip,
            'username': self.username,
            'password': self.password,
            'port': self.port,
            'timeout': conn_timeout,
            'global_delay_factor': 1.5,
            'blocking_timeout': blocking_timeout,
        }
        if enable_pwd:
            device_params['secret'] = enable_pwd
        device_params.update(build_netmiko_compatibility_kwargs(timeout=conn_timeout))
        self.conn = ConnectHandler(**device_params)
        # Only attempt privilege escalation when an explicit Enable secret is
        # configured. Without one, sending ``enable`` would trigger a device
        # password prompt and could cause the login password to be submitted.
        if enable_pwd and self.device_type in ('cisco_ios', 'cisco_nxos', 'cisco_iosxr'):
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
        exec_read_timeout = int(
            kwargs.get('read_timeout')
            or self.device_info.get('read_timeout')
            or self.device_info.get('command_read_timeout')
            or 60
        )
        try:
            self.connect()
            
            if mode == ExecutionMode.COMMAND:
                try:
                    output = self.conn.send_command(content, read_timeout=exec_read_timeout)
                except Exception as e:
                    if "Pattern not detected" in str(e) or "Timeout" in str(e) or "socket" in str(e).lower():
                        output = self.conn.send_command_timing(content, read_timeout=exec_read_timeout)
                    else:
                        raise e
                from drivers.ssh_compat import drain_paged_output
                output = drain_paged_output(self.conn, output, read_timeout=exec_read_timeout)
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
