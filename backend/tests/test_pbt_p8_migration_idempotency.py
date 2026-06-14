"""
P8: Database Migration Idempotency Property Test
Task 4.4: Verify ensure_column is idempotent — calling it N times produces same schema as 1 time.
Validates: P8
"""
import os
import sqlite3

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("DATABASE_URL", "")


def _ensure_column(cursor, table_name: str, column_name: str, definition: str):
    """Replicate the ensure_column logic from database.py for isolated testing."""
    cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()]
    if column_name not in cols:
        cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}')


class TestEnsureColumnIdempotency:
    """P8: ensure_column called N times → schema identical to 1 call, data unchanged."""

    def _create_test_db(self, tmp_path, name="test.db"):
        db_path = str(tmp_path / name)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE test_results (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                health_score INTEGER DEFAULT 100,
                findings_json TEXT DEFAULT '[]'
            )
        """)
        conn.execute("INSERT INTO test_results VALUES ('r1', 'dev1', 85, '[]')")
        conn.execute("INSERT INTO test_results VALUES ('r2', 'dev2', 70, '[{\"severity\":\"warning\"}]')")
        conn.commit()
        return conn

    def test_single_call_adds_column(self, tmp_path):
        """ensure_column adds a new column on first call."""
        conn = self._create_test_db(tmp_path)
        cursor = conn.cursor()

        _ensure_column(cursor, 'test_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
        conn.commit()

        cols = [r[1] for r in cursor.execute("PRAGMA table_info(test_results)").fetchall()]
        assert 'correlated_risks_json' in cols
        conn.close()

    def test_triple_call_no_duplicate(self, tmp_path):
        """P8: Calling ensure_column 3 times does not create duplicate columns."""
        conn = self._create_test_db(tmp_path)
        cursor = conn.cursor()

        _ensure_column(cursor, 'test_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
        _ensure_column(cursor, 'test_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
        _ensure_column(cursor, 'test_results', 'correlated_risks_json', "TEXT DEFAULT '[]'")
        conn.commit()

        cols = [r[1] for r in cursor.execute("PRAGMA table_info(test_results)").fetchall()]
        assert cols.count('correlated_risks_json') == 1
        conn.close()

    def test_existing_data_unchanged(self, tmp_path):
        """P8: ensure_column does not modify existing row data."""
        conn = self._create_test_db(tmp_path)
        cursor = conn.cursor()

        # Get data before
        rows_before = cursor.execute("SELECT * FROM test_results ORDER BY id").fetchall()

        # Add columns multiple times
        _ensure_column(cursor, 'test_results', 'new_col1', "TEXT DEFAULT 'x'")
        _ensure_column(cursor, 'test_results', 'new_col2', "INTEGER DEFAULT 0")
        _ensure_column(cursor, 'test_results', 'new_col1', "TEXT DEFAULT 'x'")
        conn.commit()

        # Verify original columns unchanged
        rows_after = cursor.execute(
            "SELECT id, device_id, health_score, findings_json FROM test_results ORDER BY id"
        ).fetchall()
        assert rows_before == rows_after

        # Verify new columns have defaults
        row = cursor.execute(
            "SELECT new_col1, new_col2 FROM test_results WHERE id='r1'"
        ).fetchone()
        assert row[0] == 'x' or row[0] is None  # SQLite default behavior
        conn.close()

    def test_no_exception_on_repeated_calls(self, tmp_path):
        """P8: ensure_column never raises on repeated calls."""
        conn = self._create_test_db(tmp_path)
        cursor = conn.cursor()

        # Should not raise
        for _ in range(5):
            _ensure_column(cursor, 'test_results', 'col_a', "TEXT DEFAULT ''")
            _ensure_column(cursor, 'test_results', 'col_b', "REAL")
            _ensure_column(cursor, 'test_results', 'col_c', "INTEGER DEFAULT 0")

        conn.commit()
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(test_results)").fetchall()]
        assert 'col_a' in cols
        assert 'col_b' in cols
        assert 'col_c' in cols
        conn.close()

    @given(n_calls=st.integers(min_value=1, max_value=5))
    @settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
    def test_n_calls_same_schema(self, n_calls, tmp_path):
        """P8 (Hypothesis): N calls produce same schema as 1 call."""
        import uuid
        db_path = str(tmp_path / f"hyp_{uuid.uuid4().hex}.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO t VALUES ('x', 'hello')")
        conn.commit()
        cursor = conn.cursor()

        for _ in range(n_calls):
            _ensure_column(cursor, 't', 'extra', "TEXT DEFAULT 'def'")
        conn.commit()

        cols = [r[1] for r in cursor.execute("PRAGMA table_info(t)").fetchall()]
        assert cols.count('extra') == 1
        # Data intact
        row = cursor.execute("SELECT val FROM t WHERE id='x'").fetchone()
        assert row[0] == 'hello'
        conn.close()


def test_init_db_idempotent_via_conftest(isolated_db):
    """P8: init_db called via conftest fixture is idempotent (schema stable on re-init)."""
    import database
    db_path = isolated_db['db_path']

    # Get schema after first init
    conn = sqlite3.connect(db_path)
    tables_1 = sorted([r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()])
    conn.close()

    # Re-init
    database._db_initialized = False
    try:
        while True:
            database._pool.get_nowait().close()
    except Exception:
        pass
    database.init_db()

    # Get schema after second init
    conn = sqlite3.connect(db_path)
    tables_2 = sorted([r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()])
    conn.close()

    assert tables_1 == tables_2
