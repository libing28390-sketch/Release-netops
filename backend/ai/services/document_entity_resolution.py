"""AI-layer compatibility exports for the V2 entity resolver."""

from services.document_entity_resolution import (
    DocumentEntityResolution,
    EntityCatalogSnapshot,
    EntityResolutionDecision,
    EntityResolutionIssue,
    EntityResolutionOutcome,
    resolve_document_entities,
    resolve_entities,
)

__all__ = [
    "DocumentEntityResolution",
    "EntityCatalogSnapshot",
    "EntityResolutionDecision",
    "EntityResolutionIssue",
    "EntityResolutionOutcome",
    "resolve_document_entities",
    "resolve_entities",
]
