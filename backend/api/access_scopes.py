from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.rbac import require_role
from services.access_scope_service import list_user_scopes, replace_user_scopes


router = APIRouter()


class ScopeItem(BaseModel):
    resource_type: str
    scope_type: str
    scope_id: str = ''
    actions: list[str] = Field(default_factory=list)


class ScopeReplace(BaseModel):
    scopes: list[ScopeItem] = Field(default_factory=list)


@router.get('/users/{user_id}/resource-scopes')
def read_user_resource_scopes(user_id: str, _user=require_role('Administrator')):
    return {'items': list_user_scopes(user_id)}


@router.put('/users/{user_id}/resource-scopes')
def update_user_resource_scopes(user_id: str, body: ScopeReplace, user=require_role('Administrator')):
    try:
        return {'items': replace_user_scopes(
            user_id, [item.model_dump() for item in body.scopes],
            changed_by=user.get('username', 'system'),
        )}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
