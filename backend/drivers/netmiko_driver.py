import re
import time
from typing import List, Dict, Any
try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    HAS_NETMIKO = True
except ImportError:
    HAS_NETMIKO = False
from .base import BaseDriver, CommandResult
from .ssh_compat import build_netmiko_compatibility_kwargs

# ── CLI 错误特征（通用），用于在 success=True 时二次检测配置失败 ──────────────
# 注意：
#   1. 使用 re.MULTILINE，^ 匹配每行行首，m.start() 直接指向匹配行首字符，
#      避免在错误行提取时因 (?:^|\n) 导致误取上一行。
#   2. 孤立 ^ 行（Cisco 游标）用 ^[ \t]*\^[ \t]*$ 匹配，确保仅在 ^ 独占整行时
#      才命中，不会误匹配 banner 定界符 ^C 等包含其他字符的行。
_CLI_ERROR_PATTERNS = re.compile(
    r'(?:'
    r'^[ \t]*\^[ \t]*$|'                                # Cisco/H3C 游标行（^ 独占一行）
    r'^[ \t]*%[ \t]*(?:Invalid|Unknown|Incomplete|'
    r'Ambiguous|Error|Bad|Cannot|Not allowed)|'         # Cisco IOS / NX-OS %错误
    r'^[ \t]*Error(?::\s|\[)|'                         # Huawei / JunOS
    r'^[ \t]*error:\s|'                                # 通用小写
    r'^[ \t]*<Error>|'                                 # Huawei XML
    r'^[ \t]*syntax error|'                            # H3C Comware
    r'^[ \t]*Unrecognized command'                     # Arista
    r')',
    re.IGNORECASE | re.MULTILINE,
)

# 慢速平台（Huawei/H3C）不适合 fast_cli，需要保守的时序参数
_SLOW_PLATFORMS = {'huawei_vrp', 'h3c_comware'}

# ── IP 地址前缀长度 → 点分十进制子网掩码 自动归一化 ─────────────────────────
# 华为 VRP / H3C Comware 支持 `ip address X.X.X.X 24` 写法；
# Cisco IOS/NX-OS/IOS-XR、Arista EOS 均要求点分十进制掩码。
# 此处在下发前统一转换，避免因写法差异导致 CLI 错误。
_CISCO_LIKE_PLATFORMS = frozenset({'cisco_ios', 'cisco_nxos', 'cisco_iosxr', 'arista_eos'})

# 匹配: ip address A.B.C.D [/]N  （N 为 1-2 位数字，即 0-32 的有效前缀长度）
# \d{1,2} 刻意只匹配 1-2 位，确保不触碰点分十进制掩码的首段数字（255/254 等均为 3 位）。
# 分隔符逻辑：
#   (?:[ \t]*/[ \t]*|[ \t]+/?)
#   — 先尝试 "0+空格 + 强制/ + 0+空格"，匹配 10.0.0.1/24 和 10.0.0.1 /24
#   — 再尝试 "1+空格 + 可选/"，       匹配 10.0.0.1 24  和 10.0.0.1 /24
_IP_PREFIX_RE = re.compile(
    r'(?i)\bip\s+address\s+(\d{1,3}(?:\.\d{1,3}){3})(?:[ \t]*/[ \t]*|[ \t]+/?)(\d{1,2})\b(?![\d.])'
)


def _prefix_to_mask(prefix_len: int) -> str:
    """将前缀长度 0-32 转换为点分十进制子网掩码。"""
    m = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
    return f"{(m >> 24) & 0xFF}.{(m >> 16) & 0xFF}.{(m >> 8) & 0xFF}.{m & 0xFF}"


def _normalize_ip_commands(commands: List[str], platform: str) -> List[str]:
    """
    对 Cisco / Arista 平台，将 'ip address X.X.X.X N' 前缀长度写法
    自动转换为 'ip address X.X.X.X M.M.M.M' 点分十进制写法。
    华为 / H3C 原生支持前缀长度，无需转换。
    """
    if platform not in _CISCO_LIKE_PLATFORMS:
        return commands

    import logging as _logging
    logger = _logging.getLogger(__name__)
    normalized: List[str] = []
    for cmd in commands:
        def _repl(m: re.Match) -> str:
            prefix = int(m.group(2))
            if prefix > 32:
                return m.group(0)  # 不是合法前缀长度，保持原样
            mask = _prefix_to_mask(prefix)
            new_cmd = f"ip address {m.group(1)} {mask}"
            # 备份原始命令用于日志，避免闭包捕获问题
            logger.debug(
                f"[normalize] '{m.group(0).strip()}' → '{new_cmd}' (platform={platform})"
            )
            return new_cmd
        normalized.append(_IP_PREFIX_RE.sub(_repl, cmd))
    return normalized


def _sanitize_command(cmd: str) -> str:
    """脱敏命令中可能包含的明文密码，适用于日志记录和报错呈现。"""
    if not isinstance(cmd, str):
        return cmd
    
    # 1. Linux echo chpasswd 格式 (如 echo 'user:pwd' | chpasswd)
    cmd = re.sub(
        r"(echo\s+)(['\"]?)([^:'\"\s]+):([^'\"\s]+)\2(\s*\|\s*(?:sudo\s+-S\s+)?chpasswd)",
        r"\1\2\3:********\2\5",
        cmd
    )
    
    # 2. Linux printf chpasswd 格式 (如 printf "%s\n%s:%s\n" 'login_pwd' 'username' 'new_pwd' | sudo -S chpasswd)
    pattern = r"(printf\s+['\"].*?['\"]\s+)(['\"])(.*?)\2\s+(['\"])(.*?)\4\s+(['\"])(.*?)\6(\s*\|\s*(?:sudo\s+-S\s+)?chpasswd)"
    cmd = re.sub(
        pattern,
        r"\1\2********\2 \4\5\4 \6********\6\8",
        cmd
    )

    # 3. Cisco/Arista: username <user> secret [0] <password>
    cmd = re.sub(
        r"(username\s+\S+\s+secret\s+(?:0\s+)?)\S+",
        r"\1********",
        cmd,
        flags=re.IGNORECASE
    )

    # 4. Cisco: enable secret [0] <password>
    cmd = re.sub(
        r"(enable\s+secret\s+(?:0\s+)?)\S+",
        r"\1********",
        cmd,
        flags=re.IGNORECASE
    )

    # 5. Huawei: local-user <user> password cipher <password>
    cmd = re.sub(
        r"(local-user\s+\S+\s+password\s+cipher\s+)\S+",
        r"\1********",
        cmd,
        flags=re.IGNORECASE
    )

    # 6. Huawei: super password ... cipher <password>
    cmd = re.sub(
        r"(super\s+password\s+(?:role\s+privilege\s+\d+\s+)?cipher\s+)\S+",
        r"\1********",
        cmd,
        flags=re.IGNORECASE
    )

    # 7. H3C: password simple <password>
    cmd = re.sub(
        r"(password\s+simple\s+)\S+",
        r"\1********",
        cmd,
        flags=re.IGNORECASE
    )
    
    return cmd


class NetmikoDriver(BaseDriver):
    """基于 Netmiko 的驱动实现"""

    def __init__(self, device_info: Dict[str, Any]):
        super().__init__(device_info)
        self.conn = None
        self.device_type = self._map_platform(self.platform)

    def _map_platform(self, platform: str) -> str:
        import logging
        mapping = {
            'cisco_ios':    'cisco_ios',
            'huawei_vrp':   'huawei',
            'h3c_comware':  'hp_comware',
            'juniper_junos':'juniper_junos',
            'arista_eos':   'arista_eos',
            'linux':        'linux',
            'ubuntu':       'linux',
            'centos':       'linux',
            'debian':       'linux',
            'redhat':       'linux',
            'esxi':         'linux',
        }
        if platform not in mapping:
            logging.getLogger(__name__).warning(
                f"Unknown platform '{platform}', falling back to cisco_ios. "
                f"Supported: {list(mapping)}"
            )
        # 自动纠错：如果资产类型是服务器且平台是默认值或未知，强制使用 linux 驱动
        if self.device_info.get('asset_type') == 'server' and platform in ('', 'cisco_ios', 'unknown', None):
            return 'linux'
            
        return mapping.get(platform, 'cisco_ios')

    def connect(self):
        import logging
        logger = logging.getLogger(__name__)

        # Huawei / H3C 等慢速设备需要关闭 fast_cli 并增大延迟因子
        is_slow = self.platform in _SLOW_PLATFORMS
        device_params = {
            'device_type':        self.device_type,
            'host':               self.host,
            'username':           self.username,
            'password':           self.password,
            'port':               self.port,
            'timeout':            20,
            'session_timeout':    60,
            'fast_cli':           not is_slow,         # 慢速平台禁用 fast_cli
            'global_delay_factor':1.5 if is_slow else 0.5,
            'blocking_timeout':   30,
        }
        logger.info(f"Login to {self.host} as username={self.username!r} pwd_len={len(self.password or '')}")
        device_params.update(build_netmiko_compatibility_kwargs())
        
        # Override connection timeout if specified in device_info
        custom_timeout = self.device_info.get('conn_timeout') or self.device_info.get('timeout')
        if custom_timeout:
            device_params['timeout'] = custom_timeout
            device_params['conn_timeout'] = custom_timeout
            logger.info(f"Using custom connection timeout: {custom_timeout}s")
            
        # enable secret: only use an explicitly configured enable_password.
        # Do NOT fall back to the login password — if the device has no enable
        # password, passing a non-empty secret causes Netmiko to expect a
        # "Password:" prompt that never comes, and enable() fails.
        secret = (
            self.device_info.get('enable_password') or
            self.device_info.get('secret') or
            ''
        )
        if secret:
            device_params['secret'] = secret
        logger.info(f"Secret set for {self.host}: len={len(secret)}")

        try:
            logger.debug(f"Connecting to {self.host}:{self.port} type={self.device_type} fast_cli={device_params['fast_cli']}")
            self.conn = ConnectHandler(**device_params)

            # For Cisco: check prompt after login and elevate only if needed.
            if self.device_type in ('cisco_ios', 'cisco_nxos', 'cisco_iosxr'):
                try:
                    prompt = self.conn.find_prompt()
                    logger.info(f"Prompt after login on {self.host}: {prompt!r}")
                    if prompt.strip().endswith('>'):
                        logger.info(f"User exec mode on {self.host}, sending enable")
                        self.conn.write_channel('enable\n')
                        import time as _time
                        _time.sleep(1)
                        out = self.conn.read_channel()
                        logger.info(f"enable response on {self.host}: {out!r}")

                        if 'assword' in out:
                            # Device prompted for password
                            pwd_to_send = secret or self.password or ''
                            self.conn.write_channel(pwd_to_send + '\n')
                            _time.sleep(1)
                            out2 = self.conn.read_channel()
                            logger.info(f"after password on {self.host}: {out2!r}")
                        elif 'Error in authentication' in out or 'Access denied' in out:
                            # Device has enable password but we didn't get prompted —
                            # try sending admin password directly
                            logger.info(f"Auth error on enable, retrying with admin password")
                            self.conn.write_channel('enable\n')
                            _time.sleep(0.5)
                            out3 = self.conn.read_channel()
                            if 'assword' in out3:
                                pwd_to_send = secret or self.password or ''
                                self.conn.write_channel(pwd_to_send + '\n')
                                _time.sleep(1)
                                self.conn.read_channel()

                        # Update Netmiko's internal prompt state
                        self.conn.set_base_prompt()
                        prompt2 = self.conn.find_prompt()
                        logger.info(f"Prompt after enable on {self.host}: {prompt2!r}")
                    else:
                        logger.info(f"Already privilege exec on {self.host}")
                except Exception as en_err:
                    logger.warning(f"Privilege elevation failed on {self.host}: {en_err}")

            logger.info(f"Connected to {self.host} (type={self.device_type})")
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            logger.error(f"Netmiko connection failed to {self.host}: {e}", exc_info=True)
            raise Exception(f"Netmiko connection failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error connecting to {self.host}: {e}", exc_info=True)
            raise Exception(f"Connection failed: {e}")


    def disconnect(self):
        import logging
        logger = logging.getLogger(__name__)
        if self.conn:
            conn, self.conn = self.conn, None
            try:
                conn.disconnect()
            except Exception as e:
                logger.debug(f"Disconnect error (non-critical): {e}")

    @staticmethod
    def _check_cli_errors(output: str) -> str | None:
        """扫描输出中的 CLI 错误行，返回最具描述性的错误行或 None。"""
        m = _CLI_ERROR_PATTERNS.search(output)
        if not m:
            return None
        # m.start() 直接指向匹配行首（MULTILINE 模式，不含前置 \n）
        line_end = output.find('\n', m.start())
        line = output[m.start(): line_end if line_end != -1 else len(output)].strip()
        # 若匹配的是孤立 ^ 游标行，尝试读取紧随的 % Invalid... 行作为更有描述性的错误
        if line == '^' and line_end != -1:
            next_start = line_end + 1
            next_end = output.find('\n', next_start)
            next_line = output[next_start: next_end if next_end != -1 else len(output)].strip()
            if next_line.startswith('%'):
                line = next_line
        return line or None

    def send_command(self, command: str, **kwargs) -> CommandResult:
        import logging
        logger = logging.getLogger(__name__)
        start_time = time.time()
        sanitized_cmd = _sanitize_command(command)
        try:
            if not self.conn:
                raise Exception("Not connected")
            logger.debug(f"[send_command] {self.host} | {sanitized_cmd[:60]}")
            
            # Default params
            params = {
                'cmd_verify': False,
                'strip_prompt': True,
                'strip_command': True,
                'read_timeout': 120,
                'delay_factor': 2
            }
            # Override with kwargs (e.g. expect_string)
            params.update(kwargs)
            
            try:
                output = self.conn.send_command(command, **params)
            except Exception as e:
                if "Pattern not detected" in str(e) or "Timeout" in str(e):
                    logger.warning(f"[send_command] strict prompt failed on {self.host}, falling back to timing mode")
                    output = self.conn.send_command_timing(command, read_timeout=params['read_timeout'])
                else:
                    raise e
            
            elapsed = time.time() - start_time
            err_line = self._check_cli_errors(output)
            sanitized_output = _sanitize_command(output)
            sanitized_err_line = _sanitize_command(err_line) if err_line else None
            
            if err_line:
                logger.warning(
                    f"[send_command] CLI error on {self.host}: "
                    f"cmd={sanitized_cmd!r} | {sanitized_err_line}"
                )
                return CommandResult(
                    success=False,
                    output=sanitized_output,
                    error=f"CLI error: {sanitized_err_line}",
                    hostname=self.device_info.get('hostname', self.host),
                    command=sanitized_cmd,
                    execution_time=elapsed,
                )
            logger.info(f"[send_command] {self.host} | {sanitized_cmd[:50]} | {elapsed:.2f}s | {len(output)} chars")
            return CommandResult(
                success=True,
                output=sanitized_output,
                hostname=self.device_info.get('hostname', self.host),
                command=sanitized_cmd,
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            sanitized_e = _sanitize_command(str(e))
            logger.error(f"[send_command ERROR] {self.host} | {sanitized_cmd[:50]} | {elapsed:.2f}s | {sanitized_e}")
            return CommandResult(
                success=False,
                output="",
                error=sanitized_e,
                hostname=self.device_info.get('hostname', self.host),
                command=sanitized_cmd,
                execution_time=elapsed,
            )

    def send_config(self, configs: List[str]) -> CommandResult:
        import logging
        logger = logging.getLogger(__name__)
        start_time = time.time()

        # Arista EOS 使用事务性 configure session
        if self.platform == 'arista_eos':
            return self._send_config_eos_session(configs)

        try:
            if not self.conn:
                raise Exception("Not connected")
            # 平台归一化：Cisco 系列要求点分十进制掩码，自动转换前缀长度写法
            configs = _normalize_ip_commands(configs, self.platform)
            logger.debug(f"Sending {len(configs)} config cmds to {self.host}")
            per_cmd_timeout = max(30, len(configs) * 3)
            output = self.conn.send_config_set(
                configs,
                exit_config_mode=True,
                cmd_verify=False,
                read_timeout=per_cmd_timeout,
            )
            elapsed = time.time() - start_time
            err_line = self._check_cli_errors(output)
            
            sanitized_configs = [_sanitize_command(c) for c in configs]
            sanitized_output = _sanitize_command(output)
            sanitized_err_line = _sanitize_command(err_line) if err_line else None
            
            if err_line:
                logger.warning(f"[send_config] CLI error on {self.host}: {sanitized_err_line}")
                return CommandResult(
                    success=False,
                    output=sanitized_output,
                    error=f"CLI error: {sanitized_err_line}",
                    hostname=self.device_info.get('hostname', self.host),
                    command="\n".join(sanitized_configs),
                    execution_time=elapsed,
                )
            logger.info(f"[send_config] {self.host} done in {elapsed:.2f}s")
            return CommandResult(
                success=True,
                output=sanitized_output,
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(sanitized_configs),
                execution_time=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            sanitized_configs = [_sanitize_command(c) for c in configs]
            sanitized_e = _sanitize_command(str(e))
            logger.warning(f"Config failed after {elapsed:.2f}s on {self.host}: {sanitized_e}")
            return CommandResult(
                success=False,
                output="",
                error=sanitized_e,
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(sanitized_configs),
                execution_time=elapsed,
            )

    def _send_config_eos_session(self, configs: List[str]) -> CommandResult:
        """
        Arista EOS 事务性配置：configure session → 逐条下发 → commit。
        若任意命令失败，执行 abort 回滚整个 session，避免部分配置生效。
        """
        import logging
        import uuid as _uuid
        logger = logging.getLogger(__name__)
        session_name = f"netops_{_uuid.uuid4().hex[:8]}"
        start_time = time.time()
        output_lines: List[str] = []

        try:
            if not self.conn:
                raise Exception("Not connected")

            # 平台归一化：Arista EOS 同样要求点分十进制掩码
            configs = _normalize_ip_commands(configs, self.platform)

            # 进入 configure session
            out = self.conn.send_command(
                f"configure session {session_name}",
                expect_string=r'[>#$]',
                cmd_verify=False,
                strip_prompt=False,
                read_timeout=15,
            )
            output_lines.append(f"[session enter]\n{_sanitize_command(out)}")

            # 逐条下发配置命令
            for cmd in configs:
                out = self.conn.send_command(
                    cmd,
                    expect_string=r'[>#$]',
                    cmd_verify=False,
                    strip_prompt=False,
                    read_timeout=15,
                )
                output_lines.append(f"[cmd] {_sanitize_command(cmd)}\n{_sanitize_command(out)}")

            # 提交 session
            out = self.conn.send_command(
                "commit",
                expect_string=r'[>#$]',
                cmd_verify=False,
                strip_prompt=False,
                read_timeout=20,
            )
            output_lines.append(f"[commit]\n{_sanitize_command(out)}")

            elapsed = time.time() - start_time
            logger.info(f"EOS session {session_name} committed on {self.host} in {elapsed:.2f}s")
            sanitized_configs = [_sanitize_command(c) for c in configs]
            return CommandResult(
                success=True,
                output="\n".join(output_lines),
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(sanitized_configs),
                execution_time=elapsed
            )
        except Exception as e:
            elapsed = time.time() - start_time
            sanitized_e = _sanitize_command(str(e))
            logger.warning(f"EOS session {session_name} failed on {self.host}: {sanitized_e}")
            # 尝试 abort 清理 session，避免配置残留
            try:
                self.conn.send_command("abort", expect_string=r'[>#$]', cmd_verify=False, read_timeout=10)
                output_lines.append("[abort] session aborted due to error")
            except Exception as abort_err:
                logger.debug(f"Abort failed (non-critical): {abort_err}")
            sanitized_configs = [_sanitize_command(c) for c in configs]
            return CommandResult(
                success=False,
                output="\n".join(output_lines),
                error=sanitized_e,
                hostname=self.device_info.get('hostname', self.host),
                command="\n".join(sanitized_configs),
                execution_time=elapsed
            )
