# CAT-013 Product Catalog Management Walkthrough

1. Open **AI Center → Product Catalog**.
2. Confirm the banner states `contract_only_read_only_seed`; no create/edit/delete action is shown.
3. Browse the six reviewed Huawei/Cisco model rows and filter by vendor, series, model, or status.
4. Open the Alias queue to inspect normalized aliases, conflict groups, and `draft` seed status.
5. Enter `CE68` in the dry-run resolver. It returns bounded Huawei candidates, requires clarification, and reports `driver_selection_allowed: false`.
6. Enter `C9300-48P`. It returns a unique candidate for inspection only; it does not select a driver or issue a command.
7. Verify a user from another tenant receives an empty catalog and an unknown dry-run result.

The protected page requires an authenticated session. Automated backend/API and production-build checks passed; the unauthenticated local browser session was recorded as an environment limitation in CAT-013 Evidence.
