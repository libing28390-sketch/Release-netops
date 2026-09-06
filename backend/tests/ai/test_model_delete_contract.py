from __future__ import annotations

import pytest
from fastapi import HTTPException

from ai.api import models as models_api


class _ModelDeleteCursor:
    def __init__(self, route_count: int, message_count: int) -> None:
        self.route_count = route_count
        self.message_count = message_count
        self.deleted = False

    def execute(self, sql: str, _params=None):
        if "ai_model_route" in sql:
            self._result = (self.route_count,)
        elif "ai_messages" in sql:
            self._result = (self.message_count,)
        else:
            self.deleted = True
            self.rowcount = 1
        return self

    def fetchone(self):
        return self._result


class _ModelDeleteConnection:
    def __init__(self, route_count: int, message_count: int) -> None:
        self.cursor_obj = _ModelDeleteCursor(route_count, message_count)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        return None


@pytest.mark.parametrize(
    ("route_count", "message_count", "expected_code", "expected_detail"),
    [
        (2, 0, "AI_MODEL_HAS_ROUTES", "route_count"),
        (0, 23, "AI_MODEL_HAS_PROVENANCE", "message_count"),
    ],
)
def test_model_delete_returns_actionable_dependency_error(route_count, message_count, expected_code, expected_detail, monkeypatch):
    connection = _ModelDeleteConnection(route_count, message_count)
    monkeypatch.setattr(models_api, "get_db_connection", lambda: connection)

    with pytest.raises(HTTPException) as exc_info:
        models_api.delete_model("model-test", {"username": "admin"})

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == expected_code
    assert exc_info.value.detail["details"][expected_detail] in {route_count, message_count}
    assert connection.cursor_obj.deleted is False
