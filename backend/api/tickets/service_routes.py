from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from core.rbac import require_role
from database import get_db_connection
from api.tickets.service_schemas import (
    ServiceCatalogItemCreate,
    ServiceCatalogVersionCreate,
    ServiceRequestAction,
    ServiceRequestChangeOrderLink,
    ServiceRequestCreate,
    TicketSlaPolicyCreate,
    TicketWorkCalendarCreate,
)
from services import service_request_service as service


router = APIRouter()


@router.get("/tickets")
def api_list_unified_tickets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    type: str = Query(default="all", max_length=40),
    status: str = Query(default="", max_length=40),
    search: str = Query(default="", max_length=200),
    my_todo: bool = Query(default=False),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        result = service.list_unified_tickets(
            conn, user, page=page, page_size=page_size,
            source_type=type, status=status, search=search, my_todo=my_todo,
        )
        return {"success": True, "data": result["items"], "total": result["total"], "page": page, "page_size": page_size}
    finally:
        conn.close()


@router.get("/tickets/summary")
def api_get_ticket_summary(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        return {"success": True, "data": service.get_ticket_summary(conn, user, from_date=from_date, to_date=to_date)}
    finally:
        conn.close()


@router.get("/service-catalog")
def api_list_service_catalog(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        include_inactive = user.get("role") == "Administrator" or user.get("role_profile") == "System Administrator"
        return {"success": True, "data": service.list_service_catalog(conn, user, include_inactive=include_inactive)}
    finally:
        conn.close()


@router.post("/service-catalog")
def api_create_service_catalog_item(body: ServiceCatalogItemCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = service.create_catalog_item(conn, user, key=body.key, name=body.name, description=body.description)
        conn.commit()
        return {"success": True, "data": result}
    except BaseException as exc:
        conn.rollback()
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="目录标识已存在") from exc
        raise
    finally:
        conn.close()


@router.post("/service-catalog/{item_id}/versions")
def api_publish_service_catalog_version(item_id: str, body: ServiceCatalogVersionCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = service.publish_catalog_version(
            conn, item_id, user,
            request_schema=body.request_schema,
            requires_approval=body.requires_approval,
            assignment_group_id=body.assignment_group_id,
            approval_group_id=body.approval_group_id,
            fulfillment_instructions=body.fulfillment_instructions,
            acceptance_criteria=body.acceptance_criteria,
            sla_policy_version_id=body.sla_policy_version_id,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/ticket-work-calendars")
def api_list_ticket_work_calendars(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": service.list_work_calendars(conn, user)}
    finally:
        conn.close()


@router.post("/ticket-work-calendars")
def api_create_or_version_ticket_work_calendar(body: TicketWorkCalendarCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = service.create_or_version_work_calendar(
            conn, user, calendar_id=body.id, name=body.name,
            timezone_name=body.timezone, schedule=body.schedule, holidays=body.holidays,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/ticket-sla-policies")
def api_list_ticket_sla_policies(user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": service.list_sla_policies(conn, user)}
    finally:
        conn.close()


@router.post("/ticket-sla-policies")
def api_create_or_version_ticket_sla_policy(body: TicketSlaPolicyCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = service.create_or_version_sla_policy(
            conn, user, policy_id=body.id, name=body.name, source_type=body.source_type,
            priority=body.priority, response_target_minutes=body.response_target_minutes,
            restore_target_minutes=body.restore_target_minutes,
            fulfillment_target_minutes=body.fulfillment_target_minutes,
            warning_before_minutes=body.warning_before_minutes,
            calendar_version_id=body.calendar_version_id,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException as exc:
        conn.rollback()
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="策略名称或版本已存在") from exc
        raise
    finally:
        conn.close()


@router.post("/service-requests")
def api_create_service_request(body: ServiceRequestCreate, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        result = service.create_service_request(
            conn, user, catalog_item_id=body.catalog_item_id,
            version=body.version, title=body.title, details=body.details,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/service-requests/{request_id}")
def api_get_service_request(request_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": service.get_service_request_detail(conn, request_id, user)}
    finally:
        conn.close()


@router.post("/service-requests/{request_id}/actions")
def api_service_request_action(request_id: str, body: ServiceRequestAction, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        result = service.perform_service_request_action(
            conn, request_id, user, action=body.action,
            assignment_group_id=body.assignment_group_id,
            assignee_id=body.assignee_id, reason=body.reason,
            summary=body.summary, evidence=body.evidence,
            change_order_number=body.change_order_number,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/service-requests/{request_id}/change-orders")
def api_link_change_order_to_service_request(
    request_id: str,
    body: ServiceRequestChangeOrderLink,
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        result = service.link_change_order_to_service_request(
            conn, request_id, user, change_order_number=body.change_order_number,
        )
        conn.commit()
        return {"success": True, "data": result}
    except BaseException as exc:
        conn.rollback()
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            # The service locks the request row, so a unique conflict indicates
            # a concurrent identical operation. Resolve idempotently here.
            result = service.link_change_order_to_service_request(
                conn, request_id, user, change_order_number=body.change_order_number,
            )
            conn.commit()
            return {"success": True, "data": result}
        raise
    finally:
        conn.close()


__all__ = ["router"]
