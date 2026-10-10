"""AI-layer compatibility export for the canonical ING-010 service."""

from services.document_metadata_extraction import (
    DocumentMetadataError,
    DocumentMetadataResult,
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    MAX_METADATA_BYTES,
    METADATA_CONTRACT_VERSION,
    MetadataDecision,
    MetadataIssue,
    MetadataStatus,
    UNKNOWN_VALUE,
    extract_document_metadata,
)

__all__ = [
    "DocumentMetadataError",
    "DocumentMetadataResult",
    "EXTRACTOR_NAME",
    "EXTRACTOR_VERSION",
    "MAX_METADATA_BYTES",
    "METADATA_CONTRACT_VERSION",
    "MetadataDecision",
    "MetadataIssue",
    "MetadataStatus",
    "UNKNOWN_VALUE",
    "extract_document_metadata",
]
