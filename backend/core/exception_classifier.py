"""
Exception Classifier Module (Task 2.1)
Standardizes all inspection exceptions into typed findings with severity and user-friendly messages.
Requirements: R2.1, R2.2
"""

from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Exception type registry
# ─────────────────────────────────────────────────────────────────────────────

EXCEPTION_TYPES: dict[str, dict] = {
    'connectivity_error': {'severity': 'critical', 'label': '连通性异常'},
    'auth_error':         {'severity': 'critical', 'label': '认证异常'},
    'command_error':      {'severity': 'warning',  'label': '命令执行异常'},
    'parse_error':        {'severity': 'warning',  'label': '解析异常'},
    'data_error':         {'severity': 'warning',  'label': '数据异常'},
    'system_error':       {'severity': 'warning',  'label': '系统异常'},
}

# ─────────────────────────────────────────────────────────────────────────────
# Classification rules (ordered by priority — first match wins)
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFICATION_RULES: list[tuple[list[str], str, str]] = [
    # (keywords_to_match, exc_type, severity_override_or_empty)
    # Auth errors — check before connectivity so "Authentication failed" wins
    (['NetmikoAuthenticationException', 'Authentication failed', 'authentication failed'],
     'auth_error', 'critical'),
    (['Enable mode failed', 'enable mode failed', 'enable secret', 'enable password'],
     'auth_error', 'warning'),
    (['% Authorization failed', 'authorization failed'],
     'auth_error', 'warning'),
    # Connectivity errors
    (['NetmikoTimeoutException', 'timed out', 'Connection timed out', 'socket.timeout'],
     'connectivity_error', 'critical'),
    (['Connection refused', 'errno=111', 'ECONNREFUSED', 'No route to host'],
     'connectivity_error', 'critical'),
    (['SSH session disconnected', 'Connection reset', 'Disconnected', 'socket is closed',
      'SSH connection dropped'],
     'connectivity_error', 'warning'),
    # Command errors
    (['% Invalid input detected', 'Invalid input detected'],
     'command_error', 'warning'),
    (['--More--'],
     'command_error', 'warning'),
    (['__ERROR__'],
     'command_error', 'warning'),
    # Parse errors
    (['TextFSM State Error', 'State Error'],
     'parse_error', 'warning'),
    (['No template found', 'template not found', 'no textfsm template'],
     'parse_error', 'info'),
    (['TextFSM parse result is empty', 'parse result empty'],
     'parse_error', 'info'),
    # Data errors
    (['could not convert', 'invalid literal', 'ValueError', 'cannot convert to number'],
     'data_error', 'warning'),
    (['output exceeds 10MB', 'raw output truncated'],
     'data_error', 'info'),
]


def classify_exception(raw_error: str, context: str = '') -> dict:
    """
    Classify a raw error string into a standard exception record.

    Args:
        raw_error: The raw error message or exception string.
        context:   Optional context string (e.g. command name, device hostname).

    Returns:
        dict with keys: type, severity, label, raw_error
    """
    combined = f"{raw_error} {context}".lower()

    for keywords, exc_type, severity_override in _CLASSIFICATION_RULES:
        if any(kw.lower() in combined for kw in keywords):
            severity = severity_override or EXCEPTION_TYPES[exc_type]['severity']
            return {
                'type': exc_type,
                'severity': severity,
                'label': EXCEPTION_TYPES[exc_type]['label'],
                'raw_error': raw_error,
            }

    # Default fallback
    return {
        'type': 'system_error',
        'severity': EXCEPTION_TYPES['system_error']['severity'],
        'label': EXCEPTION_TYPES['system_error']['label'],
        'raw_error': raw_error,
    }


def make_finding(
    exc_type: str,
    message: str,
    raw_error: str = '',
    severity: Optional[str] = None,
) -> dict:
    """
    Construct a standard finding record for insertion into findings_json.

    Args:
        exc_type:  One of the keys in EXCEPTION_TYPES.
        message:   User-friendly Chinese description of the problem.
        raw_error: Optional raw error string for debugging.
        severity:  Override the default severity for this exception type.

    Returns:
        dict with keys: type, severity, message, raw_error
    """
    if exc_type not in EXCEPTION_TYPES:
        exc_type = 'system_error'

    resolved_severity = severity or EXCEPTION_TYPES[exc_type]['severity']

    return {
        'type': exc_type,
        'severity': resolved_severity,
        'message': message,
        'raw_error': raw_error,
    }
