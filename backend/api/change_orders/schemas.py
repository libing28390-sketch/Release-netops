from typing import Optional
from pydantic import BaseModel

class TemplateValidateRequest(BaseModel):
    scenario_id: str
    source_kind: str = 'scenario'
    platform: str
    variables: dict = {}
    target_devices: list = []


class ChangeOrderCreate(BaseModel):
    title: str
    incident_id: str = ''
    description: str = ''
    order_type: str = 'config_change'
    priority: str = 'medium'
    status: str = 'draft'
    assigned_initial_reviewer_id: str = ''
    assigned_initial_reviewer_username: str = ''
    assigned_final_approver_id: str = ''
    assigned_final_approver_username: str = ''
    command_template: dict = {}
    target_devices: list = []
    commands: list = []
    rollback_plan: str = ''
    risk_level: str = 'low'
    scheduled_start: str = ''
    scheduled_end: str = ''
    authorization_exempt: bool = False
    control_sheet: dict = {}


class ChangeOrderUpdate(BaseModel):
    title: Optional[str] = None
    incident_id: Optional[str] = None
    description: Optional[str] = None
    order_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    approver_id: Optional[str] = None
    approver_username: Optional[str] = None
    assigned_initial_reviewer_id: Optional[str] = None
    assigned_initial_reviewer_username: Optional[str] = None
    assigned_final_approver_id: Optional[str] = None
    assigned_final_approver_username: Optional[str] = None
    command_template: Optional[dict] = None
    target_devices: Optional[list] = None
    commands: Optional[list] = None
    rollback_plan: Optional[str] = None
    risk_level: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    authorization_exempt: Optional[bool] = None
    control_sheet: Optional[dict] = None
    actual_start: Optional[str] = None
    actual_end: Optional[str] = None
    result_summary: Optional[str] = None
    result_detail: Optional[dict] = None
    rejected_reason: Optional[str] = None
