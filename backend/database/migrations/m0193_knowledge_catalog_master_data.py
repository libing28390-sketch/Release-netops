"""Create tenant-scoped product-catalog master data tables.

Reviewed YAML catalog rows remain immutable. These additive tables hold only
tenant-owned extensions and are deliberately soft-deletable so an operator
cannot erase a model that may already be referenced by knowledge metadata.
"""

from __future__ import annotations


VERSION = 193
NAME = "knowledge_catalog_master_data"
LEGACY_NAMES = ("knowledge_directory_projection",)


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_vendor (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            description TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source_kind TEXT NOT NULL DEFAULT 'custom',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, code),
            CHECK (status IN ('draft', 'active', 'disabled', 'archived', 'deleted'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_vendor_tenant_status ON kb_vendor(tenant_id, status)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_product_family (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            vendor_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            description TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source_kind TEXT NOT NULL DEFAULT 'custom',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, vendor_id, code),
            FOREIGN KEY (tenant_id, vendor_id) REFERENCES kb_vendor(tenant_id, id) ON DELETE RESTRICT,
            CHECK (status IN ('draft', 'active', 'disabled', 'archived', 'deleted'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_family_tenant_vendor ON kb_product_family(tenant_id, vendor_id, status)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_product_series (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            family_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            description TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source_kind TEXT NOT NULL DEFAULT 'custom',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, family_id, code),
            FOREIGN KEY (tenant_id, family_id) REFERENCES kb_product_family(tenant_id, id) ON DELETE RESTRICT,
            CHECK (status IN ('draft', 'active', 'disabled', 'archived', 'deleted'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_series_tenant_family ON kb_product_series(tenant_id, family_id, status)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_product_model (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            series_id TEXT NOT NULL,
            code TEXT NOT NULL,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            description TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'manual_review',
            source_refs_json TEXT NOT NULL DEFAULT '[]',
            software_scope_json TEXT NOT NULL DEFAULT '{}',
            platform_binding_advisory_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            source_kind TEXT NOT NULL DEFAULT 'custom',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, id),
            UNIQUE (tenant_id, series_id, code),
            FOREIGN KEY (tenant_id, series_id) REFERENCES kb_product_series(tenant_id, id) ON DELETE RESTRICT,
            CHECK (status IN ('draft', 'active', 'disabled', 'archived', 'deleted'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_model_tenant_status ON kb_product_model(tenant_id, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_model_tenant_series ON kb_product_model(tenant_id, series_id)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_product_alias (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            product_model_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            alias_kind TEXT NOT NULL DEFAULT 'exact',
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, normalized_alias, alias_kind),
            FOREIGN KEY (tenant_id, product_model_id) REFERENCES kb_product_model(tenant_id, id) ON DELETE RESTRICT,
            CHECK (alias_kind IN ('exact', 'canonical', 'prefix', 'trigram')),
            CHECK (status IN ('draft', 'active', 'disabled', 'archived', 'deleted'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_kb_alias_tenant_model ON kb_product_alias(tenant_id, product_model_id, status)")


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    # The catalog is an append-only control-plane contract. A rollback must be
    # an explicit operational migration, not an accidental destructive action.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
