from __future__ import annotations

import pytest
from fastapi import HTTPException

from ai.api import providers as providers_api


class _DeleteCursor:
    def __init__(self, model_count: int) -> None:
        self.model_count = model_count
        self.deleted = False

    def execute(self, sql: str, _params=None):
        if "COUNT(*)" in sql:
            return self
        self.deleted = True
        return self

    def fetchone(self):
        return (self.model_count,)


class _DeleteConnection:
    def __init__(self, model_count: int) -> None:
        self.cursor_obj = _DeleteCursor(model_count)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        return None


def test_provider_delete_returns_actionable_dependency_error(monkeypatch):
    connection = _DeleteConnection(model_count=2)
    monkeypatch.setattr(providers_api, "get_db_connection", lambda: connection)

    with pytest.raises(HTTPException) as exc_info:
        providers_api.delete_provider("prov-test", {"username": "admin"})

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "AI_PROVIDER_HAS_MODELS",
        "message": "该 Provider 仍关联模型，暂时不能删除。请先处理关联模型；如果只是暂时不用，可以直接停用 Provider。",
        "details": {
            "model_count": 2,
            "next_action": "disable_provider_or_remove_models",
        },
    }
    assert connection.cursor_obj.deleted is False
