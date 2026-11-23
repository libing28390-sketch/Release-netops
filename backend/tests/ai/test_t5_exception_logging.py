"""Review L2: swallowed exceptions now leave a log line with a stable code.

Each case simulates a failure at a former ``except Exception: pass`` site and
checks that (1) the caller still gets the same degraded result, (2) a log
record with the stable ``code=AI_...`` marker is written, and (3) the
exception text -- which may carry connection strings or user data -- is not
logged; only the exception type name is.
"""

from __future__ import annotations

import logging

import pytest

LEAK_MARKER = "dsn-leak-marker-10.9.8.7"


class _Boom(RuntimeError):
    pass


def _failing_connection(*_args, **_kwargs):
    raise _Boom(LEAK_MARKER)


def _assert_logged(caplog, code: str, level: int) -> None:
    records = [record for record in caplog.records if f"code={code}" in record.getMessage()]
    assert records, f"expected a log record with code={code}"
    assert any(record.levelno == level for record in records)
    for record in caplog.records:
        assert LEAK_MARKER not in record.getMessage()
    assert any("_Boom" in record.getMessage() for record in records)


def test_read_only_tool_logs_and_returns_empty_result(monkeypatch, caplog):
    from ai.tools import read_only_tools

    monkeypatch.setattr(read_only_tools, "get_db_connection", _failing_connection)
    caplog.set_level(logging.DEBUG, logger=read_only_tools.logger.name)

    result = read_only_tools.tool_search_ip("10.0.0.1")

    assert result["device"] is None
    assert result["evidence"] == []
    _assert_logged(caplog, "AI_TOOL_QUERY_FAILED", logging.WARNING)
    assert any("tool_search_ip" in record.getMessage() for record in caplog.records)


def test_ip_trace_logs_and_returns_partial_facts(monkeypatch, caplog):
    from ai.services import ip_troubleshooting

    monkeypatch.setattr(ip_troubleshooting, "get_db_connection", _failing_connection)
    caplog.set_level(logging.DEBUG, logger=ip_troubleshooting.logger.name)

    facts = ip_troubleshooting.IPTroubleshootingService().trace_ip_facts("10.0.0.1")

    assert facts["target_ip"] == "10.0.0.1"
    assert facts["device"] is None and facts["active_alarms"] == []
    _assert_logged(caplog, "AI_IP_TRACE_FAILED", logging.WARNING)


def test_natural_query_device_search_logs_and_returns_no_results(monkeypatch, caplog):
    from ai.services import natural_query

    monkeypatch.setattr(natural_query, "get_db_connection", _failing_connection)
    caplog.set_level(logging.DEBUG, logger=natural_query.logger.name)

    assert natural_query.NaturalQueryService().search_devices({"vendor": "cisco"}) == []
    _assert_logged(caplog, "AI_NATURAL_QUERY_DEVICE_SEARCH_FAILED", logging.WARNING)


def test_failed_rollback_is_ignored_but_logged_at_debug(caplog):
    from ai.services import database_observability

    class _Connection:
        def rollback(self):
            raise _Boom(LEAK_MARKER)

    caplog.set_level(logging.DEBUG, logger=database_observability.logger.name)

    database_observability._safe_rollback(_Connection())  # must not raise

    _assert_logged(caplog, "AI_DB_OBS_ROLLBACK_FAILED", logging.DEBUG)


@pytest.mark.parametrize(
    "module_name",
    [
        "ai.api.security",
        "ai.api.usage",
        "ai.services.database_observability",
        "ai.services.ip_troubleshooting",
        "ai.services.job_observability",
        "ai.services.knowledge_reindex_service",
        "ai.services.mac_troubleshooting",
        "ai.services.natural_query",
        "ai.services.product_resolver",
        "ai.services.rag_retriever",
        "ai.tools.read_only_tools",
    ],
)
def test_no_bare_except_exception_pass_left(module_name):
    """Guard against the pattern coming back in the files cleaned up for L2."""
    import importlib
    import inspect
    import re

    source = inspect.getsource(importlib.import_module(module_name))
    lines = source.splitlines()
    offenders = [
        index + 1
        for index, line in enumerate(lines[:-1])
        if re.match(r"\s*except\s+Exception\s*:\s*$", line) and lines[index + 1].strip() == "pass"
    ]
    assert offenders == [], f"{module_name}: `except Exception: pass` at lines {offenders}"
