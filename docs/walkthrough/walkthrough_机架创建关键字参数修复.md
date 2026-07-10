# Walkthrough: Fix Rack Creation Keyword Argument Error

## 1. Issue Description

When creating a new rack, the application failed with the following traceback/error:
`create_rack() got an unexpected keyword argument 'rack_name'`

### Root Cause
The FastAPI POST router [api_create_rack](file:///e:/data/netsops/backend/api/racks.py#L73-L81) receives a payload validating against the [RackCreate](file:///e:/data/netsops/backend/schemas/schemas.py#L351-L375) schema. It then unpacks all values using `**body.model_dump()` and forwards them to [create_rack](file:///e:/data/netsops/backend/services/rack_service.py).
However, [create_rack](file:///e:/data/netsops/backend/services/rack_service.py) did not have `**kwargs` or parameter mappings for the new fields (such as `rack_name`, `room_name`, etc.) in its signature, which triggered a Python `TypeError` for unexpected keyword arguments.

---

## 2. Changes Implemented

### Service Layer Update
Modified [create_rack](file:///e:/data/netsops/backend/services/rack_service.py) to:
1. Accept `**kwargs` at the end of the function signature.
2. Synchronize and populate both legacy and new fields (e.g., `rack_name` and `name`, `remarks` and `description`, etc.).
3. Explicitly insert all new schema fields (like `current_power_w`, `power_utilization`, `max_weight_kg`, `current_weight_kg`, `cooling_zone`) into the database if provided.

### Testing Updates
Added tests in [test_racks_new_fields.py](file:///e:/data/netsops/backend/tests/test_racks_new_fields.py):
1. `test_create_rack_with_new_fields_and_kwargs` - Verifies that the service function handles unexpected keyword arguments and maps fields correctly.
2. `test_api_create_rack_endpoint` - Directly validates the POST router [api_create_rack](file:///e:/data/netsops/backend/api/racks.py#L73) by simulating payload unpacking from the Pydantic schema.

---

## 3. Verification & Test Results

The specific tests pass successfully:
```powershell
.\.venv\Scripts\pytest backend\tests\test_racks_new_fields.py
```
**Output:**
```
collected 3 items

backend\tests\test_racks_new_fields.py ...                               [100%]

============================== 3 passed in 2.77s ==============================
```

A full test run of the backend is executed to verify that no regressions have been introduced:
```powershell
.\.venv\Scripts\pytest
```
**Output:**
```
======================= 348 passed in 162.48s (0:02:42) =======================
```
