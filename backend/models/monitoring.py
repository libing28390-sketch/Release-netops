"""SQLAlchemy metadata for the Monitoring V1 control plane.

Runtime services currently use the project's database adapter for PostgreSQL
compatibility; these models keep the six domain objects explicit for tooling,
schema inspection, and future repository extraction.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from .models import Base


class MonitoringCollector(Base):
    __tablename__ = "monitoring_collectors"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False, unique=True, index=True)
    site_id = Column(String, nullable=False, default="")
    collector_type = Column(String, nullable=False, default="LOCAL")
    status = Column(String, nullable=False, default="UNKNOWN")
    enabled = Column(Boolean, nullable=False, default=True)
    management_address = Column(String, nullable=False, default="")
    remote_write_endpoint = Column(String, nullable=False, default="")
    last_heartbeat_at = Column(DateTime(timezone=True))
    last_config_version = Column(Integer)
    last_config_status = Column(String, nullable=False, default="")
    last_config_applied_at = Column(DateTime(timezone=True))
    max_concurrency = Column(Integer, nullable=False, default=8)
    queue_disk_limit_mb = Column(Integer, nullable=False, default=2048)
    software_version = Column(String, nullable=False, default="")
    vmagent_version = Column(String, nullable=False, default="")
    snmp_exporter_version = Column(String, nullable=False, default="")
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class SnmpModule(Base):
    __tablename__ = "snmp_modules"

    id = Column(String, primary_key=True)
    module_key = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    vendor = Column(String, nullable=False, default="")
    cli_platform = Column(String, nullable=False, default="")
    feature_domain = Column(String, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    metric_group = Column(String, nullable=False, default="")
    walk_fingerprint = Column(String, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    built_in = Column(Boolean, nullable=False, default=False)


class SnmpModuleVariant(Base):
    __tablename__ = "snmp_module_variants"

    id = Column(String, primary_key=True)
    module_id = Column(String, ForeignKey("snmp_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_key = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    max_repetitions = Column(Integer, nullable=False, default=25)
    retries = Column(Integer, nullable=False, default=2)
    request_timeout_ms = Column(Integer, nullable=False, default=3000)
    scrape_timeout_ms = Column(Integer, nullable=False, default=20000)
    supported_platforms = Column(JSON, nullable=False, default=list)
    supported_models = Column(JSON, nullable=False, default=list)
    supported_version_scope = Column(JSON, nullable=False, default=list)
    verified_models = Column(JSON, nullable=False, default=list)
    verified_versions = Column(JSON, nullable=False, default=list)
    mib_bundle_id = Column(String, nullable=False, default="")
    mib_hash = Column(String, nullable=False, default="")
    generator_version = Column(String, nullable=False, default="")
    generator_config_hash = Column(String, nullable=False, default="")
    generated_output_hash = Column(String, nullable=False, default="")
    # Versioned snmp_exporter generator payload.  The API exposes this as
    # ``oid_config`` after JSON parsing; keeping the raw JSON column mirrors
    # the PostgreSQL/SQLite control-plane schema used by runtime services.
    oid_config_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="DRAFT")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class MonitoringCollectionPlan(Base):
    __tablename__ = "monitoring_collection_plans"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    cli_platform = Column(String, nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    config_json = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)


class CollectionAssignment(Base):
    __tablename__ = "monitoring_collection_assignments"

    id = Column(String, primary_key=True)
    asset_id = Column(String, nullable=False, index=True)
    collector_id = Column(String, ForeignKey("monitoring_collectors.id"), nullable=False, index=True)
    module_variant_id = Column(String, ForeignKey("snmp_module_variants.id"), nullable=False)
    credential_id = Column(String, nullable=False, default="")
    auth_alias = Column(String, nullable=False, default="")
    interval_seconds = Column(Integer, nullable=False)
    scrape_timeout_seconds = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    source_type = Column(String, nullable=False, default="PLAN")
    source_plan_id = Column(String, nullable=False, default="")
    assignment_hash = Column(String, nullable=False)
    last_compiled_at = Column(DateTime(timezone=True))
    last_config_version = Column(Integer)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class MetricDefinition(Base):
    __tablename__ = "monitoring_metric_definitions"

    id = Column(String, primary_key=True)
    metric_key = Column(String, nullable=False, unique=True, index=True)
    semantic = Column(String, nullable=False, default="")
    unit = Column(String, nullable=False, default="")
    query = Column(Text, nullable=False, default="")
    metric_type = Column(String, nullable=False, default="gauge")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))


class MonitoringConfigVersion(Base):
    __tablename__ = "monitoring_config_versions"

    id = Column(String, primary_key=True)
    collector_id = Column(String, ForeignKey("monitoring_collectors.id"), nullable=False, index=True)
    config_version = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="COMPILED")
    artifact_path = Column(String, nullable=False, default="")
    manifest_json = Column(JSON, nullable=False, default=dict)
    checksum = Column(String, nullable=False, default="")
    error_code = Column(String, nullable=False, default="")
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True))
    applied_at = Column(DateTime(timezone=True))
    rolled_back_at = Column(DateTime(timezone=True))


class MonitoringTargetSnapshot(Base):
    __tablename__ = "monitoring_target_snapshots"

    id = Column(String, primary_key=True)
    collector_id = Column(String, ForeignKey("monitoring_collectors.id"), nullable=False, index=True)
    config_version = Column(Integer, nullable=False)
    snapshot_json = Column(JSON, nullable=False, default=list)
    checksum = Column(String, nullable=False)
    is_last_known_good = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True))
