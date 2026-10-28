from typing import Any

from pydantic import BaseModel, Field


class IncidentTicketAction(BaseModel):
    action: str
    assignment_group_id: str = ""
    assignee_id: str = ""
    target_ticket_id: str = ""
    reason: str = ""
    summary: str = Field(default="", max_length=2000)
    evidence: Any = None


class AssignmentGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class AssignmentGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class AssignmentGroupMemberCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
