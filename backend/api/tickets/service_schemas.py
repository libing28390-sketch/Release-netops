from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ServiceCatalogItemCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class ServiceCatalogVersionCreate(BaseModel):
    request_schema: dict[str, Any] = Field(default_factory=lambda: {"fields": []})
    requires_approval: bool = False
    assignment_group_id: str | None = Field(default=None, max_length=120)
    approval_group_id: str | None = Field(default=None, max_length=120)
    fulfillment_instructions: str = Field(default="", max_length=4000)
    acceptance_criteria: str = Field(default="", max_length=4000)
    sla_policy_version_id: str | None = Field(default=None, max_length=120)


class ServiceRequestCreate(BaseModel):
    catalog_item_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    details: dict[str, Any] = Field(default_factory=dict)


class ServiceRequestAction(BaseModel):
    action: Literal[
        "approve",
        "reject",
        "assign",
        "claim",
        "acknowledge",
        "start",
        "wait_external",
        "resume",
        "deliver",
        "confirm_complete",
        "return",
        "cancel",
        "link_change_order",
    ]
    assignment_group_id: str | None = Field(default=None, max_length=120)
    assignee_id: str | None = Field(default=None, max_length=120)
    reason: str = Field(default="", max_length=1000)
    summary: str = Field(default="", max_length=2000)
    evidence: Any = None
    change_order_number: str | None = Field(default=None, max_length=80)


class ServiceRequestChangeOrderLink(BaseModel):
    change_order_number: str = Field(min_length=1, max_length=80)


class TicketWorkCalendarCreate(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    timezone: str = Field(min_length=1, max_length=80)
    schedule: dict[str, Any]
    holidays: list[str] = Field(default_factory=list)


class TicketSlaPolicyCreate(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    source_type: Literal["incident", "service_request"]
    priority: Literal["P1", "P2", "P3", "P4"]
    response_target_minutes: int | None = Field(default=None, gt=0, le=525600)
    restore_target_minutes: int | None = Field(default=None, gt=0, le=525600)
    fulfillment_target_minutes: int | None = Field(default=None, gt=0, le=525600)
    warning_before_minutes: int | None = Field(default=None, gt=0, le=525600)
    calendar_version_id: str = Field(min_length=1, max_length=120)


__all__ = [
    "ServiceCatalogItemCreate",
    "ServiceCatalogVersionCreate",
    "ServiceRequestAction",
    "ServiceRequestChangeOrderLink",
    "ServiceRequestCreate",
    "TicketSlaPolicyCreate",
    "TicketWorkCalendarCreate",
]
