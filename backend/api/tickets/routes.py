from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.rbac import require_role
from database import get_db_connection
from api.tickets.schemas import (
    AssignmentGroupCreate,
    AssignmentGroupMemberCreate,
    AssignmentGroupUpdate,
    IncidentTicketAction,
)
from services import incident_ticket_service as tickets


router = APIRouter()


def _commit_or_rollback(conn, error: BaseException | None = None) -> None:
    if error is None:
        conn.commit()
    else:
        conn.rollback()


@router.get("/tickets/incidents")
def api_list_incident_tickets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    status: str = Query(default="", max_length=40),
    search: str = Query(default="", max_length=200),
    my_todo: bool = Query(default=False),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        result = tickets.list_tickets(
            conn,
            user,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            my_todo=my_todo,
        )
        return {"success": True, "data": result["items"], "total": result["total"]}
    finally:
        conn.close()


@router.post("/tickets/from-incident/{incident_id}")
def api_open_ticket_from_incident(incident_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        ticket, created = tickets.create_ticket_from_incident(conn, incident_id, user)
        conn.commit()
        return {"success": True, "data": ticket, "created": created}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/tickets/incidents/{ticket_id}")
def api_get_incident_ticket(ticket_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        detail = tickets.get_ticket_detail(conn, ticket_id, user)
        return {"success": True, "data": detail}
    finally:
        conn.close()


@router.post("/tickets/incidents/{ticket_id}/actions")
def api_incident_ticket_action(ticket_id: str, body: IncidentTicketAction, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        ticket = tickets.perform_ticket_action(
            conn,
            ticket_id,
            user,
            action=body.action,
            assignment_group_id=body.assignment_group_id,
            assignee_id=body.assignee_id,
            target_ticket_id=body.target_ticket_id,
            reason=body.reason,
            summary=body.summary,
            evidence=body.evidence,
        )
        conn.commit()
        return {"success": True, "data": ticket}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/ticket-assignment-groups")
def api_list_ticket_assignment_groups(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": tickets.list_assignment_groups(conn, user)}
    finally:
        conn.close()


@router.post("/ticket-assignment-groups")
def api_create_ticket_assignment_group(body: AssignmentGroupCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = tickets.create_assignment_group(conn, user, body.name, body.description)
        conn.commit()
        return {"success": True, "data": result}
    except BaseException as exc:
        conn.rollback()
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Assignment group name already exists") from exc
        raise
    finally:
        conn.close()


@router.put("/ticket-assignment-groups/{group_id}")
def api_update_ticket_assignment_group(group_id: str, body: AssignmentGroupUpdate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = tickets.update_assignment_group(
            conn,
            group_id,
            user,
            name=body.name,
            description=body.description,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException as exc:
        conn.rollback()
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="Assignment group name already exists") from exc
        raise
    finally:
        conn.close()


@router.delete("/ticket-assignment-groups/{group_id}")
def api_delete_ticket_assignment_group(group_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        tickets.delete_assignment_group(conn, group_id, user)
        conn.commit()
        return {"success": True, "data": {"id": group_id, "deleted": True}}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/ticket-assignment-groups/{group_id}/members")
def api_list_ticket_assignment_group_members(
    group_id: str,
    ticket_id: str | None = Query(default=None, min_length=1, max_length=120),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        return {
            "success": True,
            "data": tickets.list_assignment_group_members(conn, group_id, user, ticket_id=ticket_id),
        }
    finally:
        conn.close()


@router.post("/ticket-assignment-groups/{group_id}/members")
def api_add_ticket_assignment_group_member(group_id: str, body: AssignmentGroupMemberCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = tickets.add_assignment_group_member(conn, group_id, user, body.user_id)
        conn.commit()
        return {"success": True, "data": result}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/ticket-assignment-groups/{group_id}/members/{user_id}")
def api_remove_ticket_assignment_group_member(group_id: str, user_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        tickets.remove_assignment_group_member(conn, group_id, user, user_id)
        conn.commit()
        return {"success": True, "data": {"group_id": group_id, "user_id": user_id, "removed": True}}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "api_add_ticket_assignment_group_member",
    "api_create_ticket_assignment_group",
    "api_delete_ticket_assignment_group",
    "api_get_incident_ticket",
    "api_incident_ticket_action",
    "api_list_incident_tickets",
    "api_list_ticket_assignment_group_members",
    "api_list_ticket_assignment_groups",
    "api_open_ticket_from_incident",
    "api_remove_ticket_assignment_group_member",
    "api_update_ticket_assignment_group",
    "router",
]
