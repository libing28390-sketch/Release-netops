"""AI-layer compatibility export for the canonical ING-008 scanner."""

from services.document_security_scan import (
    DocumentSecurityScanError,
    DocumentSecurityScanResult,
    SCANNER_NAME,
    SCANNER_VERSION,
    ScanStatus,
    SecurityDecision,
    SecurityFinding,
    isolate_document,
    scan_document_security,
)

__all__ = [
    "DocumentSecurityScanError",
    "DocumentSecurityScanResult",
    "SCANNER_NAME",
    "SCANNER_VERSION",
    "ScanStatus",
    "SecurityDecision",
    "SecurityFinding",
    "isolate_document",
    "scan_document_security",
]
