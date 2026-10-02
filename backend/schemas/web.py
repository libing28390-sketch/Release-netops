"""Shared request models for asset Web management entries."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class WebAccessProfileInput(BaseModel):
    """A user-configurable HTTP(S) entry point for an asset."""

    id: Optional[str] = None
    profile_name: str = "Web management"
    scheme: Literal["http", "https"] = "https"
    port: int = 443
    path: str = "/"
    enabled: bool = True
    credential_mode: Literal["inherit_asset", "independent"] = "inherit_asset"
    normal_username: str = ""
    normal_password: Optional[str] = None
    admin_username: str = ""
    admin_password: Optional[str] = None
    credential_id: str = ""
    admin_credential_id: str = ""

    @field_validator("profile_name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        value = str(value or "Web management").strip()
        return value[:100] or "Web management"

    @field_validator("port", mode="before")
    @classmethod
    def validate_port(cls, value):
        try:
            port = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Web port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Web port must be between 1 and 65535")
        return port

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, value):
        path = str(value or "/").strip()
        if not path.startswith("/"):
            path = "/" + path
        # A path is only a path; reject an accidental absolute URL or control
        # characters before it can be used to construct a target URL.
        if any(ord(char) < 0x20 for char in path) or re.match(r"^//|^[a-z][a-z0-9+.-]*:", path, re.I):
            raise ValueError("Web path must be a relative path")
        return path[:512] or "/"

    @field_validator(
        "normal_username", "admin_username", "credential_id", "admin_credential_id",
        mode="before",
    )
    @classmethod
    def normalize_credential_text(cls, value):
        return str(value or "").strip()[:255]


class WebSessionCreateInput(BaseModel):
    asset_id: str
    web_profile_id: str
    access_level: Literal["normal", "admin"] = "normal"
    reason: str = ""
    requester_username: str = "unknown"


class WebSessionExchangeInput(BaseModel):
    session_token: str
    agent_id: str = ""


class WebSessionStatusInput(BaseModel):
    callback_token: str
    agent_id: str = ""
    status: Literal["active", "closed", "interrupted", "error"]
    reason: str = ""
    recording_status: str = "not_started"
