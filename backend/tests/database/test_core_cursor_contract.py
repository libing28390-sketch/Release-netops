from database.core import _PgCursor


class _FakeCursor:
    def __init__(self):
        self.entered = False
        self.exited = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exited = (exc_type, exc_value, traceback)
        return False


def test_pg_cursor_preserves_context_manager_contract():
    raw_cursor = _FakeCursor()
    wrapped_cursor = _PgCursor(raw_cursor)

    with wrapped_cursor as cursor:
        assert cursor is wrapped_cursor
        assert raw_cursor.entered is True

    assert raw_cursor.exited == (None, None, None)
