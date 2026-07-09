# Plan: Rack Batch Import, Export, and Power Input Fix

This plan details the technical steps to resolve the number input issue for rack power/U-height and to implement Excel-based batch import/export/template functionalities for racks.

## User Review Required

> [!IMPORTANT]
> The batch import and export features will be implemented on the client side using the pre-installed `xlsx` (SheetJS) library. This ensures high performance, client-side validation, and avoids adding additional server-side dependencies.

---

## Proposed Changes

### Backend

#### [MODIFY] [racks.py](file:///e:/data/netsops/backend/api/racks.py)
- Import `List` from `typing`.
- Add a new endpoint `POST /api/racks/batch` accepting `List[RackCreate]` that loops through each rack payload and calls [create_rack](file:///e:/data/netsops/backend/services/rack_service.py#L48).
- Ensure atomic error reporting so that the user knows exactly which row failed if a constraint is violated.

---

### Frontend

#### [MODIFY] [index.tsx](file:///e:/data/netsops/src/pages/RackManagement/index.tsx)
- **Power and U-height Input Fix**:
  - Update `onChange` handlers for `power_capacity_watts` and `total_u` to allow empty string values (`''`) temporarily while the user is typing or backspacing.
  - Sanitize and default these fields to valid integers (e.g. `total_u || 42`, `power_capacity_watts || 0`) inside `saveRack` before sending the payloads.
- **Excel Import / Export / Template**:
  - Import `* as XLSX from 'xlsx'` and `FileText`, `Upload` Lucide icons.
  - Add `fileInputRef` to select Excel files.
  - Implement `handleDownloadTemplate()` to generate and download an Excel template sheet.
  - Implement `handleExport()` to compile and download all currently filtered racks as an Excel sheet.
  - Implement `handleImport()` to parse the uploaded Excel file using SheetJS and call `POST /api/racks/batch` on the backend.
  - Place template, export, and import buttons next to the "New Rack" button in the PageHero actions.

---

## Verification Plan

### Automated Tests
- Add a new unit test in [test_racks_new_fields.py](file:///e:/data/netsops/backend/tests/test_racks_new_fields.py) targeting `api_batch_create_racks` to verify atomic import.
- Run `pytest` to ensure all tests pass.

### Manual Verification
- Deploy to local dev server and test:
  1. Input custom numbers in "Max Power (W)" and "Total U" and verify backspacing doesn't force a reset to 0.
  2. Download the template Excel file and ensure headers match.
  3. Edit the template and import multiple racks.
  4. Export the racks list and verify data accuracy in the exported spreadsheet.
