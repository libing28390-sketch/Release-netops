"""Compatibility import surface for the single-track V1 knowledge source service.

The old module name is retained temporarily so existing callers can migrate
without changing behavior in one release.  All reads and writes are delegated
to :mod:`services.knowledge_v1_source_service`; no legacy registry tables are
accessed here.
"""

from services.knowledge_v1_source_service import (  # noqa: F401
    REGISTRY_STATUSES,
    SOURCE_KINDS,
    SOURCE_TYPES,
    TRUST_LEVELS,
    VERSION_STATUSES,
    SourceRegistryError,
    _canonicalize_url,
    _decode_registry,
    collect_source,
    create_source,
    delete_source,
    disable_source,
    enable_source,
    get_source,
    get_source_refresh_status,
    list_source_refresh_observations,
    list_source_versions,
    list_sources,
    quarantine_source_for_change,
    record_source_refresh_observation,
    record_source_version,
    update_source,
    validate_official_url_input,
    validate_source,
)

__all__ = [
    "REGISTRY_STATUSES",
    "SOURCE_KINDS",
    "SOURCE_TYPES",
    "TRUST_LEVELS",
    "VERSION_STATUSES",
    "SourceRegistryError",
    "collect_source",
    "create_source",
    "delete_source",
    "disable_source",
    "enable_source",
    "get_source",
    "get_source_refresh_status",
    "list_source_refresh_observations",
    "list_source_versions",
    "list_sources",
    "quarantine_source_for_change",
    "record_source_refresh_observation",
    "record_source_version",
    "update_source",
    "validate_official_url_input",
    "validate_source",
    "_canonicalize_url",
    "_decode_registry",
]
