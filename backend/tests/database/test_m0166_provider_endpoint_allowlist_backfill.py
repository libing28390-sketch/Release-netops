import json
import sqlite3

from database.migrations.m0166_provider_endpoint_allowlist_backfill import upgrade


def test_m0166_backfills_only_empty_cloud_endpoint_allowlists():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ai_provider (id TEXT PRIMARY KEY, provider_type TEXT, base_url TEXT, approved_endpoint_patterns_json TEXT)"
    )
    conn.executemany(
        "INSERT INTO ai_provider VALUES (?, ?, ?, ?)",
        [
            ("cloud", "deepseek", "https://api.deepseek.com", "[]"),
            ("configured", "openai", "https://api.openai.com/v1", json.dumps(["https://api.openai.com/v1"])),
            ("local", "ollama", "http://127.0.0.1:11434/v1", "[]"),
        ],
    )
    upgrade(conn, use_pg=False)
    assert conn.execute("SELECT approved_endpoint_patterns_json FROM ai_provider WHERE id = 'cloud'").fetchone()[0] == '["https://api.deepseek.com"]'
    assert conn.execute("SELECT approved_endpoint_patterns_json FROM ai_provider WHERE id = 'configured'").fetchone()[0] == '["https://api.openai.com/v1"]'
    assert conn.execute("SELECT approved_endpoint_patterns_json FROM ai_provider WHERE id = 'local'").fetchone()[0] == "[]"
    conn.close()

