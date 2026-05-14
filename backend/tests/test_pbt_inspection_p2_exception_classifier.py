"""
P2 Exploration Test: Exception Classifier Property-Based Tests
Task 2.2: Validates that classify_exception and make_finding work correctly for all exception types.
Requirements: R2.1, R2.2
Validates: P2 (Exception Complete Recording)
"""
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from backend.core.exception_classifier import (
    classify_exception,
    make_finding,
    EXCEPTION_TYPES,
)

# ─────────────────────────────────────────────────────────────────────────────
# Parametric unit tests — one per exception type trigger
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw_error,expected_type", [
    # connectivity_error triggers
    ("NetmikoTimeoutException: timed out", "connectivity_error"),
    ("Connection refused errno=111", "connectivity_error"),
    ("SSH session disconnected", "connectivity_error"),
    ("Connection reset by peer", "connectivity_error"),
    # auth_error triggers
    ("NetmikoAuthenticationException: Authentication failed", "auth_error"),
    ("Enable mode failed: authentication failed", "auth_error"),
    ("% Authorization failed", "auth_error"),
    # command_error triggers
    ("% Invalid input detected at '^' marker", "command_error"),
    ("output contains --More-- residual", "command_error"),
    ("__ERROR__: send_command failed", "command_error"),
    # parse_error triggers
    ("TextFSM State Error: unexpected token", "parse_error"),
    ("No template found for cisco_ios/show version", "parse_error"),
    # data_error triggers
    ("could not convert string to float: 'N/A'", "data_error"),
    ("invalid literal for int() with base 10", "data_error"),
])
def test_classify_exception_returns_correct_type(raw_error, expected_type):
    """R2.1: Each known error pattern must classify to the correct exception type."""
    result = classify_exception(raw_error)
    assert result['type'] == expected_type, (
        f"Expected type '{expected_type}' for error '{raw_error}', got '{result['type']}'"
    )
    assert result['severity'] in ('critical', 'warning', 'info')
    assert result['type'] in EXCEPTION_TYPES
    assert 'raw_error' in result


def test_classify_exception_unknown_falls_back_to_system_error():
    """R2.1: Unknown errors should fall back to system_error."""
    result = classify_exception("some completely unknown error xyz123")
    assert result['type'] == 'system_error'
    assert result['severity'] == 'warning'


@pytest.mark.parametrize("exc_type", list(EXCEPTION_TYPES.keys()))
def test_make_finding_all_types(exc_type):
    """R2.2: make_finding must work for all 6 exception types."""
    finding = make_finding(exc_type, f"测试消息 for {exc_type}")
    assert finding['type'] == exc_type
    assert finding['message'] == f"测试消息 for {exc_type}"
    assert finding['severity'] == EXCEPTION_TYPES[exc_type]['severity']
    assert 'raw_error' in finding


def test_make_finding_message_never_empty():
    """P2: make_finding must never produce an empty message."""
    for exc_type in EXCEPTION_TYPES:
        finding = make_finding(exc_type, "非空消息")
        assert finding['message'] != '', f"message is empty for type {exc_type}"


def test_make_finding_type_always_in_exception_types():
    """P2: make_finding type must always be in EXCEPTION_TYPES."""
    for exc_type in EXCEPTION_TYPES:
        finding = make_finding(exc_type, "test")
        assert finding['type'] in EXCEPTION_TYPES


def test_make_finding_severity_override():
    """R2.2: make_finding should respect explicit severity override."""
    finding = make_finding('connectivity_error', '会话中断', severity='warning')
    assert finding['severity'] == 'warning'
    # Default for connectivity_error is critical, but we overrode it
    assert finding['type'] == 'connectivity_error'


def test_make_finding_unknown_type_falls_back():
    """R2.2: make_finding with unknown type should fall back to system_error."""
    finding = make_finding('nonexistent_type', '未知类型测试')
    assert finding['type'] == 'system_error'
    assert finding['message'] == '未知类型测试'


# ─────────────────────────────────────────────────────────────────────────────
# Property-based tests with Hypothesis
# ─────────────────────────────────────────────────────────────────────────────

@given(raw_error=st.text(min_size=1, max_size=500))
@settings(max_examples=200)
def test_classify_exception_always_returns_valid_type(raw_error):
    """P2: classify_exception must always return a valid exception type for any input."""
    result = classify_exception(raw_error)
    assert result['type'] in EXCEPTION_TYPES
    assert result['severity'] in ('critical', 'warning', 'info')
    assert isinstance(result['raw_error'], str)


@given(
    exc_type=st.sampled_from(list(EXCEPTION_TYPES.keys())),
    message=st.text(min_size=1, max_size=200),
    raw_error=st.text(max_size=200),
)
@settings(max_examples=200)
def test_make_finding_always_valid(exc_type, message, raw_error):
    """P2: make_finding must always produce a valid finding record."""
    finding = make_finding(exc_type, message, raw_error)
    assert finding['type'] in EXCEPTION_TYPES
    assert finding['message'] == message
    assert finding['message'] != ''
    assert finding['severity'] in ('critical', 'warning', 'info')


@given(
    exc_type=st.sampled_from(list(EXCEPTION_TYPES.keys())),
    message=st.text(min_size=1, max_size=200),
    severity=st.sampled_from(['critical', 'warning', 'info']),
)
@settings(max_examples=100)
def test_make_finding_severity_override_property(exc_type, message, severity):
    """P2: Severity override must always be respected."""
    finding = make_finding(exc_type, message, severity=severity)
    assert finding['severity'] == severity


# ─────────────────────────────────────────────────────────────────────────────
# Severity defaults validation
# ─────────────────────────────────────────────────────────────────────────────

def test_exception_type_severity_defaults():
    """R2.2: Verify default severity assignments per spec."""
    assert EXCEPTION_TYPES['connectivity_error']['severity'] == 'critical'
    assert EXCEPTION_TYPES['auth_error']['severity'] == 'critical'
    assert EXCEPTION_TYPES['command_error']['severity'] == 'warning'
    assert EXCEPTION_TYPES['parse_error']['severity'] == 'warning'
    assert EXCEPTION_TYPES['data_error']['severity'] == 'warning'
    assert EXCEPTION_TYPES['system_error']['severity'] == 'warning'


def test_all_exception_types_have_labels():
    """R2.1: All exception types must have Chinese labels."""
    for exc_type, meta in EXCEPTION_TYPES.items():
        assert 'label' in meta, f"Missing label for {exc_type}"
        assert meta['label'], f"Empty label for {exc_type}"
