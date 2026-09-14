from desktop.launcher import (
    build_fast_start_confirmation_message,
    database_passwords_match,
    require_supported_postgres_major,
)


def test_fast_start_confirmation_shows_target_and_never_the_password():
    message = build_fast_start_confirmation_message(
        {
            "host": "db.example.internal",
            "port": "55432",
            "user": "nexora_app",
            "db_name": "nexora_prod",
            "password": "do-not-display-this",
        }
    )

    assert "PostgreSQL 18" in message
    assert "db.example.internal:55432" in message
    assert "nexora_prod" in message
    assert "nexora_app" in message
    assert "do-not-display-this" not in message
    assert "密码不会显示或修改" in message


def test_fast_start_confirmation_uses_safe_defaults():
    message = build_fast_start_confirmation_message({})

    assert "127.0.0.1:5432" in message
    assert "数据库：netops" in message
    assert "用户名：postgres" in message


def test_database_password_must_be_entered_consistently():
    assert database_passwords_match("secret", "secret")
    assert not database_passwords_match("secret", "secreT")


def test_windows_launcher_rejects_non_postgresql_18_servers():
    require_supported_postgres_major(18, "18.6")

    for major, version in ((17, "17.11"), (19, "19.0")):
        try:
            require_supported_postgres_major(major, version)
        except RuntimeError as exc:
            assert "仅支持 PostgreSQL 18" in str(exc)
            assert version in str(exc)
        else:
            raise AssertionError(f"PostgreSQL {version} must be rejected")
