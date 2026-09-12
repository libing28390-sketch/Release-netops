from fastapi import APIRouter
from api.change_orders.helpers import is_template_required, is_control_sheet_enabled

# Define base feature flags at module namespace for test monkeypatching compatibility
FEATURE_TEMPLATE_REQUIRED = is_template_required()
FEATURE_CONTROL_SHEET = is_control_sheet_enabled()

# Import sub-routers
from api.change_orders.core import router as core_router
from api.change_orders.transition import router as transition_router
from api.change_orders.templates import router as templates_router
from api.change_orders.bookmarks import router as bookmarks_router
from api.change_orders.attachments import router as attachments_router

# Import Pydantic models for namespace compatibility
from api.change_orders.schemas import (
    TemplateValidateRequest,
    ChangeOrderCreate,
    ChangeOrderUpdate,
)

# Import helper constants and functions for namespace compatibility
from api.change_orders.helpers import (
    ALLOWED_STATUSES,
    ALLOWED_TRANSITIONS,
    STATUS_ZH,
    validate_variable_value,
    validate_template_parameters,
    get_pre_post_checks,
)

# Import core handler functions for namespace compatibility
from api.change_orders.core import (
    api_change_order_summary,
    api_list_change_orders,
    api_validate_change_ticket,
    api_get_change_order,
    api_get_change_order_timeline,
    api_validate_template,
    api_create_change_order,
    api_update_change_order,
    api_delete_change_order,
    api_get_attachment,
    api_delete_attachment,
)
from api.change_orders.transition import api_transition_change_order
from api.change_orders.templates import (
    api_save_as_template,
    api_list_templates,
    api_get_template,
    api_delete_template,
)
from api.change_orders.bookmarks import (
    api_toggle_bookmark,
    api_get_my_bookmarks,
)
from api.change_orders.attachments import (
    api_upload_control_sheet,
    api_upload_attachment,
)

# Instantiate a unified APIRouter for inclusion in main app
router = APIRouter()

router.include_router(core_router)
router.include_router(transition_router)
router.include_router(templates_router)
router.include_router(bookmarks_router)
router.include_router(attachments_router)
