"""Add a PostgreSQL authority generation fence for locator dependencies."""

from __future__ import annotations


VERSION = 226
NAME = "locator_dependency_generation"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_dependency_generation requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_dependency_generations (
            dependency_key TEXT PRIMARY KEY,
            scope TEXT NOT NULL DEFAULT 'global' CHECK (scope = 'global'),
            generation BIGINT NOT NULL CHECK (generation > 0),
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO locator_dependency_generations
            (dependency_key, scope, generation, updated_at)
        VALUES ('topology:global', 'global', 1, clock_timestamp())
        ON CONFLICT (dependency_key) DO NOTHING
        """
    )
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS "
        "dependency_manifest_json JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION bump_locator_topology_generation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO locator_dependency_generations
                (dependency_key, scope, generation, updated_at)
            VALUES ('topology:global', 'global', 1, clock_timestamp())
            ON CONFLICT (dependency_key) DO UPDATE
               SET generation = locator_dependency_generations.generation + 1,
                   updated_at = clock_timestamp();
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    cursor.execute("DROP TRIGGER IF EXISTS trg_locator_topology_generation ON topology_links")
    cursor.execute(
        """
        CREATE TRIGGER trg_locator_topology_generation
        AFTER INSERT OR UPDATE OR DELETE ON topology_links
        FOR EACH ROW EXECUTE FUNCTION bump_locator_topology_generation()
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the generation fence when application code is rolled back.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
