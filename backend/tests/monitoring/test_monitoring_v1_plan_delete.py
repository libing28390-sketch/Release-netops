from fastapi import HTTPException

from api import monitoring_v1


class _Result:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row = row
        self._rows = rows if rows is not None else ([] if row is None else [row])
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, plan=None):
        self.plan = plan
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if statement.startswith("SELECT id, name"):
            return _Result(self.plan)
        if statement.startswith("DELETE FROM monitoring_collection_assignments"):
            return _Result(rowcount=2)
        return _Result(rowcount=1)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_delete_monitoring_plan_removes_derived_assignments_and_audits(monkeypatch):
    connection = _Connection(plan={"id": "plan-1", "name": "Interface baseline"})
    events = []
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: events.append((args, kwargs)))

    result = monitoring_v1.delete_monitoring_plan("plan-1", _user={"id": "operator-1", "role": "Operator"})

    assert result == {"id": "plan-1", "deleted": True, "removed_assignment_count": 2}
    assert connection.committed is True
    assert connection.closed is True
    assert any("monitoring_collection_assignments" in statement and params == ("PLAN", "plan-1") for statement, params in connection.statements)
    assert events[0][0][1] == "MONITORING_PLAN_DELETED"
    assert events[0][1]["details"]["removed_assignment_count"] == 2


def test_delete_monitoring_plan_returns_not_found_without_mutating(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)

    try:
        monitoring_v1.delete_monitoring_plan("missing", _user={"role": "Operator"})
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected a 404 for a missing collection plan")

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True
    assert all("monitoring_collection_assignments" not in statement for statement, _ in connection.statements)


def test_delete_monitoring_plan_protects_canonical_baseline(monkeypatch):
    connection = _Connection(plan={"id": "plan-generic-ifmib", "name": "Generic IF-MIB baseline"})
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)

    try:
        monitoring_v1.delete_monitoring_plan("plan-generic-ifmib", _user={"role": "Operator"})
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "canonical" in str(exc.detail)
    else:
        raise AssertionError("Expected the canonical monitoring plan to be protected")

    assert connection.committed is False
    assert connection.rolled_back is True
    assert all("DELETE FROM monitoring_collection_assignments" not in statement for statement, _ in connection.statements)


class _ModuleDeleteConnection:
    def __init__(self):
        self.statements = []
        self.committed = False
        self.closed = False

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if statement.startswith("SELECT id, module_key"):
            return _Result({"id": "module-custom", "module_key": "custom", "built_in": 0})
        if statement.startswith("SELECT id, name, config_json"):
            return _Result(rows=[])
        return _Result(rowcount=1)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("delete should not roll back")

    def close(self):
        self.closed = True


class _ApplyConnection:
    def __init__(self):
        self.committed = False
        self.closed = False

    def execute(self, statement, params=()):
        if statement.startswith("SELECT id, name, enabled"):
            return _Result({"id": "plan-1", "name": "Interface baseline", "enabled": 1})
        if "FROM monitoring_collectors" in statement:
            return _Result(rows=[{"id": "collector-local"}])
        return _Result()

    def close(self):
        self.closed = True


def test_delete_custom_module_succeeds_when_unreferenced(monkeypatch):
    connection = _ModuleDeleteConnection()
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: None)

    result = monitoring_v1.delete_module("module-custom", _user={"role": "Operator"})

    assert result == {"id": "module-custom", "deleted": True}
    assert connection.committed is True
    assert connection.closed is True


def test_apply_monitoring_plan_orchestrates_compile_publish(monkeypatch):
    connection = _ApplyConnection()
    events = []
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring_v1, "compile_collector", lambda collector_id, _user=None: {"assignment_count": 4, "collector_id": collector_id})
    monkeypatch.setattr(monitoring_v1, "publish_collector", lambda collector_id, _user=None: {"status": "APPLIED", "config_version": 3, "collector_id": collector_id})
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: events.append((args, kwargs)))

    result = monitoring_v1.apply_monitoring_plan("plan-1", _user={"role": "Administrator"})

    assert result == {"plan_id": "plan-1", "status": "APPLIED", "collectors": [{"collector_id": "collector-local", "config_version": 3, "status": "APPLIED", "assignment_count": 4}]}
    assert connection.closed is True
    assert events[0][0][1] == "MONITORING_PLAN_APPLIED"


class _CollectorDeleteConnection:
    def __init__(self):
        self.statements = []
        self.committed = False
        self.closed = False

    def execute(self, statement, params=()):
        self.statements.append((statement, params))
        if statement.startswith("SELECT id, code"):
            return _Result({"id": "collector-custom", "code": "local-custom"})
        if "monitoring_collection_assignments" in statement:
            return _Result({"count": 0})
        if "monitoring_config_versions" in statement:
            return _Result({"count": 0})
        return _Result(rowcount=1)

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("delete should not roll back")

    def close(self):
        self.closed = True


def test_delete_collector_succeeds_without_assignments_or_history(monkeypatch):
    connection = _CollectorDeleteConnection()
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring_v1, "_audit", lambda *args, **kwargs: None)

    result = monitoring_v1.delete_collector("collector-custom", _user={"role": "Operator"})

    assert result == {"id": "collector-custom", "deleted": True}
    assert connection.committed is True
    assert connection.closed is True
