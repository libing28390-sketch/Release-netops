from fastapi import APIRouter

from api.tickets.routes import router as tickets_router
from api.tickets.service_routes import router as service_tickets_router

router = APIRouter()
router.include_router(tickets_router)
router.include_router(service_tickets_router)

__all__ = ["router", "tickets_router", "service_tickets_router"]
