"""subprocess 输出解码工具。

中文 Windows 的控制台工具（ping/tracert 等）默认输出 GBK，而后端解释器可能运行在
UTF-8 模式（PYTHONUTF8=1 或较新的 Python）。用 text=True 读取会在读取线程里直接抛
UnicodeDecodeError 并丢失输出，因此这里改为按字节捕获，再依次尝试 UTF-8/GBK 解码。
"""

import subprocess


def decode_console_output(data: bytes | None) -> str:
    if not data:
        return ''
    for encoding in ('utf-8', 'gbk'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


def run_console_command(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    """运行命令并以容错方式解码 stdout/stderr。

    返回的 CompletedProcess 与 subprocess.run(..., capture_output=True) 形状一致，
    TimeoutExpired 等异常语义不变。
    """
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    return subprocess.CompletedProcess(
        args=proc.args,
        returncode=proc.returncode,
        stdout=decode_console_output(proc.stdout),
        stderr=decode_console_output(proc.stderr),
    )
