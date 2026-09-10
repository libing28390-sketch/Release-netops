"""Bound conversational history and raise safe defaults for cloud models."""

from __future__ import annotations


VERSION = 217
NAME = "ai_context_and_model_token_defaults"


_REMOTE_PROVIDER_TYPES = (
    "deepseek",
    "openai",
    "openai_compatible",
    "azure_openai",
    "qwen",
)


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("AI context and model token defaults migration requires PostgreSQL")

    # These are defaults for newly created records. Existing model-specific
    # capabilities remain authoritative after this migration.
    cursor.execute("ALTER TABLE ai_model ALTER COLUMN context_length SET DEFAULT 131072")
    cursor.execute("ALTER TABLE ai_model ALTER COLUMN max_output_tokens SET DEFAULT 16384")
    cursor.execute("ALTER TABLE ai_model ALTER COLUMN default_max_tokens SET DEFAULT 4096")
    cursor.execute("ALTER TABLE ai_conversations ALTER COLUMN context_budget SET DEFAULT 8192")
    cursor.execute(
        "UPDATE ai_conversations SET context_budget = 8192 WHERE context_budget = 32768"
    )

    # Upgrade only untouched legacy seed values for remote providers. A local
    # Ollama/model row, or any row with a deliberately customized capability,
    # is left unchanged so we do not advertise an unsupported context window.
    placeholders = ", ".join("?" for _ in _REMOTE_PROVIDER_TYPES)
    cursor.execute(
        f"""
        UPDATE ai_model AS m
        SET context_length = 131072,
            max_output_tokens = 16384,
            default_max_tokens = 4096
        FROM ai_provider AS p
        WHERE p.id = m.provider_id
          AND LOWER(p.provider_type) IN ({placeholders})
          AND COALESCE(m.context_length, 32768) IN (32768, 128000)
          AND COALESCE(m.max_output_tokens, 4096) = 4096
          AND COALESCE(m.default_max_tokens, 2048) = 2048
        """,
        _REMOTE_PROVIDER_TYPES,
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Do not reduce model capacities or conversation budgets during rollback;
    # doing so could truncate existing sessions or invalidate model settings.
    return None
