"""
Unified AI Platform Exceptions and Standard Error Schemas
"""

from __future__ import annotations

from typing import Optional, Any, Dict
from fastapi import HTTPException, status


class AIException(Exception):
    """Base exception for all AI Gateway & Provider errors."""
    def __init__(
        self,
        code: str,
        message: str,
        request_id: Optional[str] = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
                "details": self.details
            }
        }


class AIProviderTimeoutException(AIException):
    def __init__(self, message: str = "AI Provider request timed out", request_id: Optional[str] = None):
        super().__init__("AI_PROVIDER_TIMEOUT", message, request_id, status.HTTP_504_GATEWAY_TIMEOUT)


class AIAuthFailedException(AIException):
    def __init__(self, message: str = "AI Provider authentication failed", request_id: Optional[str] = None):
        super().__init__("AI_AUTH_FAILED", message, request_id, status.HTTP_401_UNAUTHORIZED)


class AIRateLimitException(AIException):
    def __init__(self, message: str = "AI Provider or user rate limit exceeded", request_id: Optional[str] = None):
        super().__init__("AI_RATE_LIMIT", message, request_id, status.HTTP_429_TOO_MANY_REQUESTS)


class AIModelNotFoundException(AIException):
    def __init__(self, message: str = "Requested AI model not found or disabled", request_id: Optional[str] = None):
        super().__init__("AI_MODEL_NOT_FOUND", message, request_id, status.HTTP_404_NOT_FOUND)


class AINetworkException(AIException):
    def __init__(self, message: str = "Network error connecting to AI Provider", request_id: Optional[str] = None):
        super().__init__("AI_NETWORK_ERROR", message, request_id, status.HTTP_502_BAD_GATEWAY)


class AIInvalidResponseException(AIException):
    def __init__(self, message: str = "Invalid response format from AI Provider", request_id: Optional[str] = None):
        super().__init__("AI_INVALID_RESPONSE", message, request_id, status.HTTP_502_BAD_GATEWAY)


class AISecurityBlockedException(AIException):
    """External AI egress was refused by the fail-closed security gateway."""

    def __init__(self, message: str = "AI request blocked by security policy", request_id: Optional[str] = None):
        super().__init__("AI_SECURITY_BLOCKED", message, request_id, status.HTTP_403_FORBIDDEN)
