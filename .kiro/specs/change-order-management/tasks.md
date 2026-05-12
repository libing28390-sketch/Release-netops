# Implementation Plan — change-order-management Bugfix

> **Methodology**: Exploration-first (write tests BEFORE fix). All property tests are written as Hypothesis-style PBTs and run against `backend/` via `pytest`. Frontend PBTs (where applicable) use `fast-check` + Vitest. Tests that need to fail on unfixed code are marked `xfail(strict=True)` → flip to strict-pass after the fix lands.
>
> Notation: `P1`..`P7` refer to Correctness Properties in `design.md §Correctness Properties`. Requirement IDs `2.1`..`2.16` refer to Expected Behavior clauses in `bugfix.md`; `3.1`..`3.11` refer to Preservation clauses.

---

## Phase A — Exploration (write exploration tests BEFORE any fix)

- [x] 1. Write bug condition exploration test — cluster 1.1 (template enforcement)
  - **Property 1: Bug Condition** — Manual / empty-template submission accepted on unfixed code
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **GOAL**: Surface counterexamples that prove `POST /api/change-orders` with `command_template == {}`, `mode == 'manual'`, empty `scenario_id`, or empty `preview.execute` is accepted when `status != 'draft'`
  - **Scoped PBT Approach**: strategy generates `command_template ∈ {{}, {mode:'manual', commands:['shutdown']}, {mode:'template', scenario_id:'', preview:{execute:[]}}, {mode:'template', scenario_id:'s-x', variables:{}, preview:{execute:[]}}}` × `status ∈ {'initial_review','final_review','approved'}`
  - Assert the exploration expectation: handler should reject (HTTP 400) for all such inputs once fixed
  - Also exercise the frontend `ChangeOrderTab.tsx` fallback branch `commandMode === 'template' && !scenarioId && devicePlatform != ''` via a Vitest fast-check property (assert the built payload does not carry `scenario_id == devicePlatform`)
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (HTTP 200 returned / payload built silently) → proves the bug exists
  - Document counterexamples found (shortest failing input per branch)
  - _Bug_Condition: `C1(input)` in `design.md §Bug Details` — input is Create/Update with `target_status != 'draft'` AND (`command_template` empty OR `mode == 'manual'` OR `scenario_id == ''` OR `preview.execute == []`)_
  - _Validates: Property 1 (design)_
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write bug condition exploration test — cluster 1.2 (control sheet missing)
  - **Property 1: Bug Condition** — Control-sheet-less order accepted through `initial_review` / `implementing` on unfixed code
  - **CRITICAL**: This test MUST FAIL on unfixed code
  - Strategy generates `CreateRequest(target_status ∈ {'initial_review','final_review','approved','implementing','completed','rolled_back'})` with no `control_sheet` field (schema does not yet expose it) and drives `POST /change-orders` → `POST /change-orders/{id}/transition` to `implementing` without any attachment upload
  - Assert fixed expectation: HTTP 400 on submission that lacks `control_sheet.*` required fields, and HTTP 400 on `transition → implementing` when `change_order_control_sheet_attachments` is empty
  - Also exercise `GET /change-orders/{id}` after `completed` on a historical row: fixed version MUST still return the order with a banner field `control_sheet_missing: true`, but not crash
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (HTTP 200, no control_sheet persisted, no attachment enforcement) → proves the bug exists
  - Document counterexamples found
  - _Bug_Condition: `C2(input)` — missing/incomplete `control_sheet` at non-draft submission, or zero attachments on enter-`implementing`_
  - _Validates: Property 2 (design)_
  - _Requirements: 1.4, 1.5, 1.6_

- [x] 3. Write bug condition exploration test — cluster 1.3 (approver dedup / permission group)
  - **Property 1: Bug Condition** — POST bypass via empty `change_groups_json`, PUT bypass of dedup, transition hijack of final approver
  - **CRITICAL**: These tests MUST FAIL on unfixed code
  - **Scoped PBT Approach**: generate three focused properties:
    - (a) `POST /change-orders` with `assigned_initial_reviewer_id = U` where `U.change_groups_json = '[]'` → fixed must 400
    - (b) Create a legal order, then `PUT /change-orders/{id}` with `assigned_initial_reviewer_id = existing.requester_id` (and separately with `assigned_initial_reviewer_id == assigned_final_approver_id`) → fixed must 400 on each
    - (c) Create a legal order in `initial_review`, then `POST /transition` to `final_review` with `body.assigned_final_approver_id = requester_id` or `= current initial_reviewer_id` or `= Operator-role user outside final_approver group` → fixed must 400 and order state MUST NOT change
  - Assert persistence delta: on failure, `change_orders` row MUST be byte-identical to pre-request state
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: All three sub-properties FAIL (unfixed code accepts the bypass) → proves the bug exists
  - Document counterexamples per sub-property
  - _Bug_Condition: `C3(input)` — `assignees_rule_violated(input)` from `_resolve_assignment_user` short-circuit, PUT/transition paths not reusing `_validate_assignment_rules`_
  - _Validates: Property 3 (design)_
  - _Requirements: 1.7, 1.8, 1.9_

- [x] 4. Write bug condition exploration test — cluster 1.4 (state machine + reject reset)
  - **Property 1: Bug Condition** — Terminal-state transition permissive + stale reviewer/approver after reject→draft
  - **CRITICAL**: This test MUST FAIL on unfixed code (reject-reset branch); the terminal-state branch may already behave correctly via `.get(..., set())` fallback — lock it in as an explicit contract
  - Strategy generates:
    - (a) Any order in `completed` / `rolled_back` / `cancelled` and attempts transition to each other status → fixed must 400 `Invalid transition`
    - (b) Any order reaching `initial_review` → `rejected` → `draft` (or `final_review` → `rejected` → `draft`) with non-empty `initial_reviewer_username` / `final_approver_username` / `result_detail.initial_review_at` / `result_detail.approved_at` → re-read after the `→ draft` transition, assert all six fields are cleared, only `rejected_reason` + timeline event remain
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: (b) FAILS (stale reviewer/approver retained); (a) may pass on unfixed code but is brittle — assert both for contract lock-in
  - Document counterexamples (e.g., `order X after reject→draft still carries initial_reviewer_username='alice'`)
  - _Bug_Condition: `C4(input)` — TransitionRequest from terminal state OR reject→draft where persisted row retains prior-round approver fields_
  - _Validates: Properties 4 and 5 (design)_
  - _Requirements: 1.10, 1.11, 1.12_

- [x] 5. Write bug condition exploration test — cluster 1.5 (view filter semantics)
  - **Property 1: Bug Condition** — `my_drafts` / `my_todo` / `group_todo` return rows that violate the contract; dual-role rows leak into two views
  - **CRITICAL**: This test MUST FAIL on unfixed code on at least one sub-property
  - Strategy seeds `N ∈ [20, 80]` orders with random requester / assigned reviewer / assigned approver / status distributions (including dirty cases where `requester_username == assigned_initial_reviewer_username`), then asserts:
    - (i) `my_drafts=U` must return only rows where `status == 'draft' AND requester_username == U`
    - (ii) `my_todo=U` must return rows partitioned into the three buckets from Property 6; each returned row carries a `todo_kind` label; assert no row outside the contracted union
    - (iii) `group_todo=G` with `initial_reviewer ∈ G` must return only rows where `status == 'initial_review' AND assigned_initial_reviewer_id IN (NULL, '')`
    - (iv) For any order with `requester_username == assigned_*_username`, fixed create/update MUST have rejected that combination so the order does not exist
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: (ii) FAILS (no `todo_kind` label), (iv) FAILS (dirty orders can exist); (i) / (iii) may pass on unfixed code — lock in as explicit contract
  - Document counterexamples
  - _Bug_Condition: `C5(input)` — ListRequest whose result violates the view contract, or dual-role row in any view_
  - _Validates: Property 6 (design)_
  - _Requirements: 1.13, 1.14, 1.15, 1.16_

---

## Phase B — Preservation baseline (write preservation PBTs BEFORE any fix)

- [x] 6. Write preservation property tests — §3.1 / §3.2 main lifecycle
  - **Property 2: Preservation** — BG numbering + draft→initial_review→final_review→approved→implementing→completed stays working
  - **IMPORTANT**: Follow observation-first methodology
  - Observe on UNFIXED code:
    - `POST /change-orders` with legal payload (ignoring new fields) returns `order_number` matching `^BG\d{8}\d{4}$`
    - Full happy-path sequence through `api_transition_change_order` writes `actual_start` / `actual_end` and emits timeline events in the canonical order
  - Write PBTs: for all `n ∈ [1, 50]` orders created within one day, numbers are unique + strictly increasing; for all legal transition sequences, every step returns 200 and persists the expected `status` + `result_detail_json` fields
  - Run on UNFIXED code → **EXPECTED OUTCOME**: PBTs PASS (baseline captured)
  - _Preservation_Ref: `bugfix.md §3.1, §3.2`; `design.md §Preservation Requirements`_
  - _Validates: Property 7 (design)_
  - _Requirements: 3.1, 3.2_

- [x] 7. Write preservation property tests — §3.3 / §3.4 / §3.5 / §3.6 authorization
  - **Property 2: Preservation** — Existing RBAC branches for initial_reviewer / final_approver / requester / Administrator are unchanged
  - **IMPORTANT**: Observation-first
  - Observe on UNFIXED code:
    - Initial reviewer (role != Viewer) can `initial_review → final_review` / `→ rejected`
    - Final approver (role == Administrator) can `final_review → approved` / `→ rejected` / `→ initial_review`
    - Requester or Administrator can drive `approved → implementing` / `→ completed` / `→ failed` / `→ rollback_in_progress`
    - Administrator can `DELETE /api/change-orders/{id}` regardless of owner
  - Write PBTs: generate `(role, actor_relation_to_order, current_status, target_status)` tuples across the full space; assert response code matches the observed baseline for every tuple
  - Run on UNFIXED code → **EXPECTED OUTCOME**: PBTs PASS
  - _Preservation_Ref: `bugfix.md §3.3–§3.6`_
  - _Validates: Property 7 (design)_
  - _Requirements: 3.3, 3.4, 3.5, 3.6_

- [x] 8. Write preservation property tests — §3.7 / §3.8 list filters + i18n
  - **Property 2: Preservation** — `assignee / requester / search / priority / status / order_type / created_* / completed_* / scheduled_*` pagination unchanged; Chinese / English field display unchanged
  - **IMPORTANT**: Observation-first
  - Observe on UNFIXED code: for a seeded fixture of 200 orders, call `GET /api/change-orders?assignee=…&priority=…&…` across random parameter combinations; record response body hash
  - Write PBT: generate random query-param tuples from the whitelisted set, assert response set equality + pagination metadata equality on fixed code
  - For i18n: render a fixture detail page under `lang=zh` and `lang=en` via a Vitest component test; snapshot both; assert both contain the full legacy field set
  - Run on UNFIXED code → **EXPECTED OUTCOME**: PBTs PASS (baseline captured as golden response set)
  - _Preservation_Ref: `bugfix.md §3.7, §3.8`_
  - _Validates: Property 7 (design)_
  - _Requirements: 3.7, 3.8_

- [x] 9. Write preservation property tests — §3.9 / §3.10 / §3.11 templates / bookmarks / validate-ticket
  - **Property 2: Preservation** — `/api/change-order-templates` CRUD, `/api/change-orders/{id}/bookmark`, `/api/change-orders-bookmarks`, `/api/change-orders/validate-ticket/{order_number}` contracts untouched
  - **IMPORTANT**: Observation-first
  - Observe on UNFIXED code:
    - Template CRUD round-trip (POST → GET → LIST → DELETE) on random payloads
    - Bookmark toggle idempotency: `POST bookmark` twice yields same membership set
    - `validate-ticket`: for status ∈ {`approved`, `implementing`} within scheduled window → valid; else → invalid
  - Write PBTs asserting each invariant
  - Run on UNFIXED code → **EXPECTED OUTCOME**: PBTs PASS
  - _Preservation_Ref: `bugfix.md §3.9–§3.11`_
  - _Validates: Property 7 (design)_
  - _Requirements: 3.9, 3.10, 3.11_

---

## Phase C — Data model & shared refactors (backend-only, blocks 14 / 15 and informs 12 / 13 / 16)

- [x] 10. Data model migrations for control sheet

  - [x] 10.1 Add `change_orders.control_sheet_json` column (idempotent)
    - Edit `backend/database.py`: call `ensure_column('change_orders', 'control_sheet_json', "TEXT NOT NULL DEFAULT '{}'")` during startup migration
    - New installs: include the column in the `CREATE TABLE change_orders` statement
    - _Design_Ref: `design.md §Data Model Changes → change_orders`_
    - _Requirements: 2.4_

  - [x] 10.2 Create `change_order_control_sheet_attachments` table
    - Edit `backend/database.py`: add `CREATE TABLE IF NOT EXISTS change_order_control_sheet_attachments (...)` with FK to `change_orders(id) ON DELETE CASCADE` and index `idx_control_sheet_attachments_order`
    - _Design_Ref: `design.md §Data Model Changes → change_order_control_sheet_attachments`_
    - _Requirements: 2.5_

  - [x] 10.3 Update `_row_to_dict` and service read paths for backward-compat defaults
    - Edit `backend/services/change_order_service.py::_row_to_dict`: deserialize `control_sheet_json` (default `{}`) and attach `control_sheet_attachments` summary list via a join against the new table
    - Legacy rows (empty `command_template_json`) deserialize to `{}` without crashing; add unit test guarding that
    - _Design_Ref: `design.md §Data Model Changes → command_template_json 语义强化`_
    - _Requirements: 2.4, 2.6, 3.8_

- [x] 11. Shared validator & constant refactor (no behavior change on its own)

  - [x] 11.1 Fix `_resolve_assignment_user` short-circuit bug
    - Edit `backend/api/change_orders.py::_resolve_assignment_user`: change `if groups and 'initial_reviewer' not in groups` → `if 'initial_reviewer' not in groups` (and same for `final_approver`), so empty `change_groups_json` is rejected
    - Return `HTTPException(400, '用户未加入 initial_reviewer / final_approver 权限组')`
    - _Design_Ref: `design.md §Fix Implementation 1.3 → _resolve_assignment_user`_
    - _Bug_Condition: `C3` — empty groups accepted as approver_
    - _Validates: Property 3_
    - _Requirements: 2.7_

  - [x] 11.2 Introduce `_validate_assignment_rules(conn, *, requester_id, payload, current_order=None, stage_hint=None)`
    - Edit `backend/api/change_orders.py`: add new helper that centralizes (i) `assigned_initial_reviewer_id != requester_id`, (ii) `assigned_final_approver_id != requester_id`, (iii) `assigned_initial_reviewer_id != assigned_final_approver_id` (when both non-empty), (iv) delegation to `_resolve_assignment_user` for group/role membership
    - Raise `HTTPException(400, ...)` with distinct messages per branch ("申请人不能作为初审人", "初审人与终审人不能相同", "用户未加入对应权限组")
    - Do NOT call this helper from any handler yet — wiring happens in task 12.1
    - _Design_Ref: `design.md §Fix Implementation 1.3 → _validate_assignment_rules`_
    - _Validates: Property 3_
    - _Requirements: 2.7, 2.8, 2.9_

  - [x] 11.3 Make `ALLOWED_TRANSITIONS` terminals explicit
    - Edit `backend/api/change_orders.py::ALLOWED_TRANSITIONS`: add explicit `'rolled_back': set()`, `'completed': set()`, `'cancelled': set()`; keep `'rejected': {'draft','cancelled'}` for the reopen path; retain legacy `'pending'` / `'executing'` entries verbatim
    - Add a module-level assertion (test-time) that every value in `ALLOWED_STATUSES` is a key of `ALLOWED_TRANSITIONS`
    - _Design_Ref: `design.md §Fix Implementation 1.4 → ALLOWED_TRANSITIONS`_
    - _Validates: Property 4_
    - _Requirements: 2.12_

  - [x] 11.4 Extract `_build_group_todo_conditions(groups) -> (where, params)`
    - Edit `backend/services/change_order_service.py`: pull the `status='initial_review' AND assigned_initial_reviewer_id IN (NULL,'')` / `status='final_review' AND assigned_final_approver_id IN (NULL,'')` fragment out of `list_change_orders` and reuse it from `get_summary` so both stay in lock-step
    - Add docstring documenting the contract from `design.md §View Filter Semantics`
    - _Design_Ref: `design.md §Fix Implementation 1.5 → _build_group_todo_conditions`_
    - _Validates: Property 6_
    - _Requirements: 2.14_

---

## Phase D — Cluster fixes (wired in staged-rollout order: 1.3 → 1.4 → 1.1 → 1.2 → 1.5)

### Stage 1 — backend-only fixes (safe to ship without frontend changes)

- [x] 12. Fix for cluster 1.3 — approver dedup & permission-group enforcement across POST / PUT / transition

  - [x] 12.1 Wire `_validate_assignment_rules` into all three write paths
    - `api_create_change_order`: replace the 3 scattered `if` checks with one call to `_validate_assignment_rules(conn, requester_id=user['user_id'], payload=payload)`
    - `api_update_change_order`: after `_normalize_assignment_payload`, call `_validate_assignment_rules(conn, requester_id=existing.requester_id, payload=payload, current_order=existing)`
    - `api_transition_change_order`: when `new_status == 'final_review' AND body.assigned_final_approver_id` is present, merge `existing + body` into a synthetic payload and call `_validate_assignment_rules(..., stage_hint='final')`; if it raises, return the 400 BEFORE any `UPDATE` statement runs (guard with a transaction savepoint)
    - _Design_Ref: `design.md §Fix Implementation 1.3 → 3. api_create_change_order` & `5. api_transition_change_order`_
    - _Bug_Condition: `C3` — all three bypass paths closed_
    - _Expected_Behavior: Property 3 (design) — `∀ write-path, invariants I1..I5 hold or HTTP 4xx returned and state unchanged`_
    - _Validates: Property 3_
    - _Requirements: 2.7, 2.8, 2.9_

  - [x] 12.2 Enforce "requester cannot review/approve own order" at transition time
    - `api_transition_change_order`: when `new_status IN {'initial_review','final_review','approved','rejected'}`, assert `actor.user_id != existing.requester_id`; otherwise return HTTP 403
    - _Design_Ref: `design.md §Fix Implementation 1.3 → 6_
    - _Validates: Property 3, Property 6 (dual-role lock-down)_
    - _Requirements: 2.9, 2.15_

  - [x] 12.3 Verify bug condition exploration test for cluster 1.3 now passes
    - **Property 1: Expected Behavior** — Approver dedup / permission-group
    - **IMPORTANT**: Re-run the SAME test from task 3 — do NOT write a new test
    - The exploration test already encodes the fixed expectation (HTTP 400 on all bypass vectors)
    - **EXPECTED OUTCOME**: Test PASSES (bug fixed)
    - _Validates: Property 3_
    - _Requirements: 2.7, 2.8, 2.9_

  - [x] 12.4 Verify preservation tests 7 (§3.3–§3.6) still pass
    - **Property 2: Preservation** — Authorization branches unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 7 — do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS (no regression on legitimate reviewer / approver / requester / Administrator flows)
    - _Requirements: 3.3, 3.4, 3.5, 3.6_

- [x] 13. Fix for cluster 1.4 — state-machine terminals + reject→draft field reset

  - [x] 13.1 Clean up approver residue on reject→draft
    - `api_transition_change_order`: when `new_status == 'draft' AND current_status IN {'initial_review','final_review','rejected'}`, add to the `updates` dict: `initial_reviewer_id=''`, `initial_reviewer_username=''`, `final_approver_id=''`, `final_approver_username=''`, `approver_id=''`, `approver_username=''`; pop `initial_review_at` and `approved_at` from `result_detail`; keep `rejected_reason` and the timeline event
    - Ensure the cleanup happens in the same transaction as the status update
    - _Design_Ref: `design.md §Fix Implementation 1.4 → 3_
    - _Bug_Condition: `C4` — reject→draft leaves stale approver fields_
    - _Expected_Behavior: Property 5 (design) — after successful reject→draft, all six fields are empty and two timestamps are popped_
    - _Validates: Property 5_
    - _Requirements: 2.11_

  - [x] 13.2 Document "创建中" as frontend-only transient state
    - Update `design.md` cross-refs and `src/pages/ChangeOrderTab.tsx` / `src/App.tsx` status label strings to stop using "创建中" as a backend status; standardize on the six-phase lexicon from 2.10
    - No code behavior change; pure lexicon alignment
    - _Design_Ref: `design.md §Fix Implementation 1.4 → 2_
    - _Requirements: 2.10_

  - [x] 13.3 Verify bug condition exploration test for cluster 1.4 now passes
    - **Property 1: Expected Behavior** — Terminal transitions rejected + reject-reset clean
    - **IMPORTANT**: Re-run the SAME test from task 4 — do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Validates: Properties 4 and 5_
    - _Requirements: 2.10, 2.11, 2.12_

  - [x] 13.4 Verify preservation tests 6 (§3.1–§3.2) still pass
    - **Property 2: Preservation** — Main lifecycle unaffected
    - **IMPORTANT**: Re-run the SAME tests from task 6 — do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 3.1, 3.2_

### Stage 2 — new fields / frontend steps (requires data-model tasks 10.x landed)

- [x] 14. Fix for cluster 1.1 — scenario-based command template enforced

  - [x] 14.1 Backend template enforcement in create / update / transition
    - `api_create_change_order` / `api_update_change_order`: when `payload.status IN {'initial_review','final_review','approved','implementing','completed'}`, require `command_template` to exist with `mode == 'template'`, non-empty `scenario_id`, and non-empty `preview.execute`; else `HTTPException(400, '提交初审前必须选择场景化命令模板并渲染出可执行命令')`
    - `_build_command_template_snapshot`: assert `scenario_id != ''` in all paths (today it is conditional)
    - `api_transition_change_order`: when moving `draft → initial_review`, re-check the same assertion against the persisted snapshot
    - Gate the enforcement on `FEATURE_TEMPLATE_REQUIRED` flag (see task 19.1) so Stage 2 can be toggled independently of Stage 1
    - _Design_Ref: `design.md §Fix Implementation 1.1 → 1–2_
    - _Bug_Condition: `C1`_
    - _Expected_Behavior: Property 1 (design) — every non-draft persisted order carries a non-empty `preview.execute` snapshot_
    - _Validates: Property 1_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 14.2 Frontend — remove silent fallback branch and expose variable errors
    - Edit `src/pages/ChangeOrderTab.tsx`: delete the `commandMode === 'template' && !scenarioId` fallback that synthesizes an empty template from `devicePlatform`; replace with a disabled submit button + toast "请先选择场景并填写必填变量"
    - Surface backend 400 error messages verbatim (or via i18n keys) in the create/edit form
    - _Design_Ref: `design.md §Fix Implementation 1.1 → 3_
    - _Requirements: 2.1, 2.3_

  - [x] 14.3 Frontend — four-stage review view (pre_check / execute / post_check / rollback)
    - Edit `src/pages/ChangeOrderTab.tsx` detail + review panels: render `command_template.preview.{pre_check,execute,post_check,rollback}` as four labeled sections, alongside `scenario_name`, `platform`, and the `variables` table
    - _Design_Ref: `design.md §Fix Implementation 1.1 → 4_
    - _Requirements: 2.2_

  - [x] 14.4 Verify bug condition exploration test for cluster 1.1 now passes
    - **Property 1: Expected Behavior** — Manual / empty-template submissions rejected
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Validates: Property 1_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 14.5 Verify preservation tests 9 (§3.9 template CRUD) still pass
    - **Property 2: Preservation** — `/api/change-order-templates` CRUD untouched
    - **IMPORTANT**: Re-run the SAME tests from task 9 — do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 3.9_

- [x] 15. Fix for cluster 1.2 — change control sheet fields + upload

  - [x] 15.1 Backend — `control_sheet` field accepted by create / update
    - Extend `ChangeOrderCreate` / `ChangeOrderUpdate` pydantic models with a `control_sheet` structured field (per `design.md §Data Model Changes → control_sheet_json`)
    - `change_order_service.create_change_order` / `update_change_order`: JSON-serialize the field into `change_orders.control_sheet_json`
    - `_row_to_dict`: already covered by task 10.3 — verify readout in integration test
    - _Design_Ref: `design.md §Fix Implementation 1.2 → 5_
    - _Bug_Condition: `C2`_
    - _Expected_Behavior: Property 2 (design)_
    - _Validates: Property 2_
    - _Requirements: 2.4_

  - [x] 15.2 Backend — new endpoint `POST /api/change-orders/{order_id}/control-sheet`
    - Add multipart/form-data handler in `backend/api/change_orders.py`; accept `file` (pdf/doc/docx/xlsx, ≤ 20 MiB) + optional `note`
    - Persist into `change_order_control_sheet_attachments`; emit `log_audit_event(event_type='change_order.control_sheet_uploaded', ...)`
    - Authorization: requester / implementer / Administrator; order `status IN {'approved','implementing','completed','rolled_back'}` (mirror `design.md §API Surface Changes`)
    - MIME whitelist, reject binaries like `application/x-msdownload`
    - _Design_Ref: `design.md §API Surface Changes → 新增`_
    - _Validates: Property 2_
    - _Requirements: 2.5_

  - [x] 15.3 Backend — transition enforcement of control-sheet completeness
    - `api_transition_change_order`: when `new_status == 'initial_review'`, require the 9 structured fields to be non-empty (per 2.4); when `new_status == 'implementing'`, additionally require ≥ 1 row in `change_order_control_sheet_attachments` for the order
    - Gate behind `FEATURE_CONTROL_SHEET` flag (task 19.1)
    - _Design_Ref: `design.md §API Surface Changes → 扩展 transition`_
    - _Requirements: 2.4, 2.5_

  - [x] 15.4 Frontend — control-sheet step in create / edit wizard
    - Edit `src/pages/ChangeOrderTab.tsx`: add a "变更控制表" step with the 9 structured inputs (time window picker, user picker ×2, IP list, four multi-line blocks, rollback plan); wire to the new backend field
    - Gate visibility behind the `FEATURE_CONTROL_SHEET` flag
    - _Design_Ref: `design.md §Fix Implementation 1.2 → UI`_
    - _Requirements: 2.4_

  - [x] 15.5 Frontend — detail / timeline / export rendering of control sheet + attachments
    - Render structured fields in the detail page, attachment list with download link, and timeline entries for `change_order.control_sheet_uploaded`
    - Export view (CSV / print) includes control-sheet fields per `bugfix.md 2.6`
    - _Design_Ref: `design.md §Fix Implementation 1.2 → UI`_
    - _Requirements: 2.6_

  - [x] 15.6 Verify bug condition exploration test for cluster 1.2 now passes
    - **Property 1: Expected Behavior** — Control-sheet enforcement at non-draft submission and at `→ implementing`
    - **IMPORTANT**: Re-run the SAME test from task 2 — do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Validates: Property 2_
    - _Requirements: 2.4, 2.5, 2.6_

  - [x] 15.7 Verify preservation tests 6 / 9 still pass
    - **Property 2: Preservation** — Main lifecycle + bookmarks / templates / validate-ticket unchanged
    - **IMPORTANT**: Re-run the SAME tests from tasks 6 and 9 — do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 3.1, 3.2, 3.9, 3.10, 3.11_

### Stage 3 — view-filter UX polish

- [x] 16. Fix for cluster 1.5 — view filter semantics aligned with contract

  - [x] 16.1 `my_drafts` strict filter + doc
    - `change_order_service.list_change_orders`: keep `requester_username = ? AND status = 'draft'`; add docstring that rejected rows live in `my_todo`
    - _Design_Ref: `design.md §Fix Implementation 1.5 → 1_
    - _Validates: Property 6_
    - _Requirements: 2.16_

  - [x] 16.2 `my_todo` returns `todo_kind` bucket labels
    - `list_change_orders`: after the existing UNION that builds the `my_todo` rows, annotate each row with `todo_kind ∈ {'review', 'implement', 'follow_up', 'draft'}` per the mapping in `design.md §Fix Implementation 1.5 → 2`
    - Exclude the `review` bucket entry when `requester_username == U` (reinforced by task 12.2)
    - _Validates: Property 6_
    - _Requirements: 2.13_

  - [x] 16.3 `group_todo` via shared helper; align `get_summary`
    - Wire `list_change_orders` and `get_summary` both through `_build_group_todo_conditions` (task 11.4); add PBT that both return identical WHERE fragments for the same input
    - _Validates: Property 6_
    - _Requirements: 2.14_

  - [x] 16.4 Frontend — tab labels "待我审核 / 待我实施 / 待我修改"
    - `src/pages/ChangeOrderTab.tsx`: split the "个人待办" tab into three sub-sections keyed on `todo_kind`; apply i18n both zh/en
    - Gate behind Stage-3 feature flag (task 19.2) for rollback safety
    - _Design_Ref: `design.md §Fix Implementation 1.5 → 2_
    - _Requirements: 2.13_

  - [x] 16.5 Verify bug condition exploration test for cluster 1.5 now passes
    - **Property 1: Expected Behavior** — View filters honor the contract + no dual-role rows
    - **IMPORTANT**: Re-run the SAME test from task 5 — do NOT write a new test
    - **EXPECTED OUTCOME**: Test PASSES
    - _Validates: Property 6_
    - _Requirements: 2.13, 2.14, 2.15, 2.16_

  - [x] 16.6 Verify preservation tests 8 still pass
    - **Property 2: Preservation** — List / i18n contracts intact
    - **IMPORTANT**: Re-run the SAME tests from task 8 — do NOT write new tests
    - **EXPECTED OUTCOME**: Tests PASS
    - _Requirements: 3.7, 3.8_

---

## Phase E — Fix-checking PBTs (one PBT per correctness property)

- [x] 17. Fix-checking property tests (run on FIXED code)

  - [x] 17.1 Property P1 — command-template enforcement PBT
    - Generate `(command_template ∈ {empty, manual, template-no-scenario, template-no-vars, template-valid}) × (status ∈ {'draft','initial_review','final_review','approved'})`
    - Assert acceptance matrix from `design.md §Testing Strategy → Property-Based Tests → P1`
    - _Validates: Property 1_
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 17.2 Property P2 — control-sheet enforcement PBT
    - Generate `(control_sheet ∈ {missing, partial, complete}) × (attachments_count ∈ {0, 1, k}) × (status ∈ transition targets)`
    - Assert fields required at `initial_review`, attachments required at `implementing`
    - _Validates: Property 2_
    - _Requirements: 2.4, 2.5, 2.6_

  - [x] 17.3 Property P3 — approver rule PBT across POST / PUT / transition
    - Generate `(requester, reviewer, approver)` ∈ `{same, pairwise-different, empty-group, viewer-role, non-admin-approver}`
    - Assert POST / PUT / transition responses are equivalent (same 400 message taxonomy) for the same tuple
    - _Validates: Property 3_
    - _Requirements: 2.7, 2.8, 2.9, 2.15_

  - [x] 17.4 Property P4 — state-machine PBT
    - Enumerate `(from, to) ∈ ALLOWED_STATUSES²`; assert `to ∈ ALLOWED_TRANSITIONS[from] ⇔ HTTP 200`; assert terminals `{'completed','rolled_back','cancelled'}` always 400 on any non-self transition
    - _Validates: Property 4_
    - _Requirements: 2.10, 2.12_

  - [x] 17.5 Property P5 — reject→draft cleanup PBT
    - Generate orders with arbitrary `(initial_reviewer, final_approver, approver)` combinations at any of `{'initial_review','final_review','rejected'}`; drive a `→ draft` transition; assert the six fields are empty and `result_detail.{initial_review_at,approved_at}` popped, while `rejected_reason` retained
    - _Validates: Property 5_
    - _Requirements: 2.11_

  - [x] 17.6 Property P6 — view contract PBT
    - Seed `N ∈ [50, 200]` random orders; for all `U`, assert `my_drafts=U`, `my_todo=U`, `group_todo=G` return rows matching the WHERE contracts in `design.md §View Filter Semantics`
    - Assert `¬∃ order` where `requester_username == assigned_initial_reviewer_username OR assigned_final_approver_username`
    - _Validates: Property 6_
    - _Requirements: 2.13, 2.14, 2.15, 2.16_

  - [x] 17.7 Property P7 — preservation PBT (fixed vs. unfixed parity)
    - For inputs where `NOT isBugCondition(input)`, snapshot the fixed handler's response (status code, body modulo new-and-defaulted fields, DB diff, audit events) and compare against the baseline captured in tasks 6–9
    - Strategy: generate inputs via the same generators as tasks 6–9 but filtered by `NOT C`
    - _Validates: Property 7_
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

---

## Phase F — Integration & cross-cutting

- [x] 18. Integration tests

  - [x] 18.1 End-to-end main path
    - Operator creates an order in template mode → fills control sheet → submits to `initial_review` → initial reviewer promotes to `final_review` (optionally switching final approver) → Administrator approves → requester drives `approved → implementing` after uploading a control-sheet attachment → marks `completed`
    - Assert timeline events, audit log entries, and detail-page rendering (zh + en) match `design.md §State Machine` + `§API Surface Changes`
    - _Validates: Properties 1, 2, 3, 4, 6, 7_
    - _Requirements: 2.1–2.9, 3.1–3.8_

  - [x] 18.2 Reject-and-resume path
    - Order goes to `initial_review` → `rejected` → reopen to `draft` → re-submit with new reviewer/approver → `final_review` → `approved` → `completed`
    - Assert between the reopen and resubmit, the six reviewer/approver fields are empty, `result_detail.{initial_review_at,approved_at}` popped, and `rejected_reason` retained (encoded on the first reject)
    - _Validates: Properties 3, 4, 5_
    - _Requirements: 2.11, 2.12_

  - [x] 18.3 Cross-view consistency
    - Seed four accounts: U1 (requester), U2 (initial reviewer), U3 (final approver), U4 (same group as U2 but not assigned); drive an order through several phases; at each phase snapshot `my_todo` / `group_todo` / `my_drafts` / `my_participated` for all four accounts
    - Assert no order appears in two views that would indicate a dual-role leak; assert `todo_kind` labels are stable
    - _Validates: Property 6_
    - _Requirements: 2.13, 2.14, 2.15, 2.16_

- [x] 19. Feature flags & staged rollout

  - [x] 19.1 Introduce backend + frontend feature flags
    - Backend: `FEATURE_TEMPLATE_REQUIRED` and `FEATURE_CONTROL_SHEET` env-driven booleans consumed in `backend/api/change_orders.py` (gate enforcement in tasks 14.1 / 15.3)
    - Frontend: mirror flags in `src/pages/ChangeOrderTab.tsx` (task 14.2 disabled-submit, task 15.4 control-sheet step, task 16.4 tab split)
    - Both flags default `ON` in production config and `OFF` in the staging rollback toggle
    - _Design_Ref: `design.md §Migration / Rollout → 前端灰度`_
    - _Requirements: 2.1–2.6, 2.13_

  - [x] 19.2 Staged deployment sequence
    - Sequence: Stage 1 (clusters 1.3 + 1.4, backend-only, no flag needed) → Stage 2 (clusters 1.1 + 1.2 with flags ON) → Stage 3 (cluster 1.5 UI labels)
    - Each stage requires tasks in the corresponding Phase D / Phase F sub-sections to be green
    - Document the release order in the project release notes
    - _Design_Ref: `design.md §Migration / Rollout → 分步上线`_

  - [x] 19.3 Post-release probes
    - Add a 24-hour probe job that queries `my_todo` / `group_todo` / `my_drafts` for a sampled set of users and asserts Property 6 invariants hold on production data
    - Route probe failures to the existing alerting channel
    - _Design_Ref: `design.md §Migration / Rollout → 发布后验证`_
    - _Requirements: 2.13, 2.14, 2.16_

- [x] 20. One-off migration script for dirty historical data
  - Write `backend/scripts/migrate_change_order_dual_role.py`:
    - Scan `change_orders` for rows where `requester_username == assigned_initial_reviewer_username` OR `requester_username == assigned_final_approver_username`
    - Print a report (order_number, requester, reviewer/approver, status)
    - With `--apply`: null out the offending `assigned_*_id` / `assigned_*_username` fields, log `log_audit_event(event_type='change_order.dual_role_migration_cleanup', actor='system')`, and keep the original values in `result_detail.migration_notes` for forensic trace
    - Dry-run by default; require explicit `--apply` flag
  - Run on a staging DB snapshot before production; attach report to the release ticket
  - _Design_Ref: `design.md §Migration / Rollout → 3 对存量脏数据`_
  - _Validates: Property 6 (no dual-role rows remain post-migration)_
  - _Requirements: 2.15_

---

## Phase G — Checkpoint

- [x] 21. Checkpoint — Ensure all tests pass
  - Run full pytest suite (including Phase A exploration tests — now passing, Phase B preservation tests, Phase E fix-checking PBTs, Phase F integration tests)
  - Run full frontend test suite (Vitest) including fast-check properties for task 1 and component tests for tasks 14.3 / 15.4 / 15.5 / 16.4
  - Walk through the Regression Prevention Checklist in `design.md §Regression Prevention Checklist` (§3.1–§3.11) and tick each item
  - If any test fails, diagnose root cause and ask before patching around it
  - Confirm feature flag defaults match the staged-rollout plan (task 19.2)
  - Confirm the dirty-data migration (task 20) has been applied to staging and the report is clean

---

## Task Dependency Graph

```
Phase A (exploration tests, run on UNFIXED code)
  1  2  3  4  5           ← all independent, all MUST fail on unfixed
         │  │  │
Phase B (preservation baseline, run on UNFIXED code)
  6  7  8  9              ← all independent, all MUST pass on unfixed

Phase C (backend-only refactors — no external behavior change)
  10.1 ─┐
  10.2 ─┼─► 10.3
        │
  11.1 ─┤
  11.2 ─┼─► (consumed by 12.1, 12.2, 14.1, 15.3)
  11.3 ─┤    (consumed by 13.1, 17.4)
  11.4 ─┘    (consumed by 16.3, 17.6)

Phase D — Stage 1 (backend only; ship first)
  11.x ──► 12.1 ─► 12.2 ─► 12.3 (verify task 3) ─► 12.4 (verify task 7)
  11.3 ──► 13.1 ─► 13.2 ─► 13.3 (verify task 4) ─► 13.4 (verify task 6)

Phase D — Stage 2 (new fields + frontend; ship after Stage 1 observation)
  10.x + 11.x + 12.x ──► 14.1 ─► 14.2 ─► 14.3 ─► 14.4 (verify task 1) ─► 14.5 (verify task 9)
  10.x + 12.x         ──► 15.1 ─► 15.2 ─► 15.3 ─► 15.4 ─► 15.5 ─► 15.6 (verify task 2) ─► 15.7 (verify tasks 6, 9)

Phase D — Stage 3 (UI polish; ship last)
  11.4 + 12.2 + 14.x + 15.x ──► 16.1 ─► 16.2 ─► 16.3 ─► 16.4 ─► 16.5 (verify task 5) ─► 16.6 (verify task 8)

Phase E (fix-checking PBTs — run after each cluster lands)
  12.x ──► 17.3
  13.x ──► 17.4, 17.5
  14.x ──► 17.1
  15.x ──► 17.2
  16.x ──► 17.6
  all   ──► 17.7

Phase F (cross-cutting)
  14.x + 15.x           ──► 18.1
  13.x + 12.x           ──► 18.2
  16.x + 12.2           ──► 18.3
  (flags) 19.1 ◄─── 14.1, 14.2, 15.3, 15.4, 16.4
  19.1 ──► 19.2 ──► 19.3
  12.2 (contract) ──► 20 (dirty-data migration; run on staging before Stage 1 prod ship)

Phase G
  all of 12–20 green ──► 21 (checkpoint)
```

**Critical paths:**
- Stage-1 ship: `11.1 → 11.2 → 11.3 → 12.1 → 12.2 → 13.1 → 12.3 → 12.4 → 13.3 → 13.4 → 18.2 → 20 (staging) → release`
- Stage-2 ship: `10.1 → 10.2 → 10.3 → 14.1 → 14.2 → 14.3 → 15.1 → 15.2 → 15.3 → 15.4 → 15.5 → 14.4 → 14.5 → 15.6 → 15.7 → 17.1 → 17.2 → 18.1 → 19.1 → 19.2 → release`
- Stage-3 ship: `11.4 → 16.1 → 16.2 → 16.3 → 16.4 → 16.5 → 16.6 → 17.6 → 18.3 → 19.3 → release`

---

## Property → Task → Requirement matrix

| Property | Exploration | Fix-Checking | Preservation affected | Implementation tasks | Requirements |
|---|---|---|---|---|---|
| P1 command template | 1 | 17.1 | 9 (§3.9) | 14.1, 14.2, 14.3 | 2.1, 2.2, 2.3 |
| P2 control sheet | 2 | 17.2 | 6, 9 (§3.1, §3.2, §3.9–§3.11) | 10.1, 10.2, 10.3, 15.1, 15.2, 15.3, 15.4, 15.5 | 2.4, 2.5, 2.6 |
| P3 approver rules | 3 | 17.3 | 7 (§3.3–§3.6) | 11.1, 11.2, 12.1, 12.2 | 2.7, 2.8, 2.9, 2.15 |
| P4 state machine | 4 | 17.4 | 6 (§3.1, §3.2) | 11.3 | 2.10, 2.12 |
| P5 reject cleanup | 4 | 17.5 | 6, 7 (§3.1–§3.6) | 13.1 | 2.11 |
| P6 view filters | 5 | 17.6 | 8 (§3.7, §3.8) | 11.4, 12.2, 16.1, 16.2, 16.3, 16.4, 20 | 2.13, 2.14, 2.15, 2.16 |
| P7 preservation | — | 17.7 | 6, 7, 8, 9 (§3.1–§3.11) | (regression only) | 3.1–3.11 |
