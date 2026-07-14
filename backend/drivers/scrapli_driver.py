import time
from typing import List, Dict, Any
try:
    from scrapli import Scrapli
    HAS_SCRAPLI = True
except ImportError:
    HAS_SCRAPLI = False
from .base import BaseDriver, CommandResult
from .ssh_compat import build_system_ssh_open_cmd

class ScrapliDriver(BaseDriver):
    """基于 Scrapli (同步) 的驱动实现"""
    
    def __init__(self, device_info: Dict[str, Any]):
        super().__init__(device_info)
        self.conn = None
        # 映射平台
        self.platform_type = self._map_platform(self.platform)

    def _map_platform(self, platform: str) -> str:
        mapping = {
            'cisco_ios': 'cisco_iosxe',
            'huawei_vrp': 'huawei_vrp',
            'huawei_vrpv8': 'huawei_vrp',
            'h3c_comware': 'hp_comware',
            'h3c_comware9': 'hp_comware',
            'hp_comware': 'hp_comware',
            'ruijie_os': 'ruijie_os',
            'ruijie_rgos': 'ruijie_os',
            'zte_zxros': 'zte_zxros',
            'maipu': 'maipu',
            'juniper_junos': 'juniper_junos',
            'arista_eos': 'arista_eos',
            'linux': 'linux',
            'server': 'linux'
        }
        return mapping.get(platform, platform or 'cisco_iosxe')

    def connect(self):
        import logging
        import platform as platform_module
        logger = logging.getLogger(__name__)
        
        # 基础设备参数
        device_params = {
            'host': self.host,
            'auth_username': self.username,
            'auth_password': self.password,
            'port': self.port,
            'platform': self.platform_type,
            'auth_strict_key': False,
            'timeout_socket': 20,       # 连接超时
            'timeout_transport': 60,    # 传输超时（含慢速设备）
            'timeout_ops': 30,          # 单次操作超时
        }
        # Enable password for privilege escalation
        secret = self.device_info.get('enable_password') or self.device_info.get('secret') or ''
        if secret:
            device_params['auth_secondary'] = secret
        
        # 检测操作系统，在 Windows 上使用 paramiko 传输
        if platform_module.system() == 'Windows':
            logger.debug(f"Windows detected, using paramiko transport")
            device_params['transport'] = 'paramiko'
            # Paramiko transport 通过 monkey-patch 自动支持 legacy SSH 算法
            device_params['transport_options'] = {
                'paramiko_open_options': {
                    'look_for_keys': False,
                    'allow_agent': False,
                }
            }
        else:
            # Linux/Mac 上使用 system transport，并支持较老的 SSH 算法
            device_params['transport_options'] = {
                'open_cmd': build_system_ssh_open_cmd()
            }
        
        try:
            logger.debug(f"Connecting to {self.host}:{self.port} with platform {self.platform_type}")
            self.conn = Scrapli(**device_params)
            self.conn.open()
            # If enable_password is provided, attempt privilege escalation
            secret = self.device_info.get('enable_password') or self.device_info.get('secret') or ''
            if secret:
                try:
                    self.conn.acquire_priv('privilege_exec')
                except Exception:
                    pass  # Not all platforms require privilege escalation
            logger.info(f"Successfully connected to {self.host}")
        except Exception as e:
            logger.error(f"Scrapli connection failed to {self.host}: {str(e)}", exc_info=True)
            raise Exception(f"Scrapli connection failed to {self.host}: {str(e)}")

    def disconnect(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            finally:
                self.conn = None

    def send_command(self, command: str) -> CommandResult:
        start_time = time.time()
        try:
            if not self.conn:
                raise Exception("Not connected")
            response = self.conn.send_command(command)
            return CommandResult(
                success=True,
                output=response.result,
                hostname=self.device_info.get('hostname', self.host),
                command=command,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return CommandResult(
                success=False,
                output="",
                error=str(e),
                hostname=self.device_info.get('hostname', self.host),
                command=command,
                execution_time=time.time() - start_time
            )

    def send_config(self, configs: List[str]) -> CommandResult:
        start_time = time.time()
        try:
            if not self.conn:
                raise Exception("Not connected")
            response = self.conn.send_configs(configs)
            return CommandResult(
                success=True,
                output=response.result,
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(configs),
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return CommandResult(
                success=False,
                output="",
                error=str(e),
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(configs),
                execution_time=time.time() - start_time
            )
