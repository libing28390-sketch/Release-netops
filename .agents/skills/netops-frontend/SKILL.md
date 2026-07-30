---
name: netops-frontend
description: Implement and review Nexora NetOps React 19 and TypeScript pages, components, hooks, contexts, Zustand stores, routing, dashboards, and API-driven interactions. Use for changes under src or for frontend contracts affected by backend work.
---

# NetOps Frontend

## Workflow

1. Locate the route in `src/App.tsx`, navigation entry, page, hooks, stores, and shared types involved.
2. Keep data fetching and mutations in hooks or stores; keep rendering and local interaction in components.
3. Reuse existing layout, modal, pagination, notification, theme, and localization patterns.
4. Update `src/types.ts` or domain-local `types.ts` when an API contract changes.
5. Handle loading, empty, error, permission-denied, and narrow-screen states.
6. For device, backup, task, log, alert, topology, or other growing datasets, read [references/large-data-ui.md](references/large-data-ui.md) before choosing the view, pagination, filtering, search, or detail-loading strategy.

## Conventions

- Use the existing React 19, Vite, Tailwind/CSS, Lucide, Recharts, D3, and Motion stack.
- Do not add a new UI framework or state library without explicit approval.
- Preserve Chinese and English translations through the existing i18n helpers.
- Keep destructive operations behind confirmation and surface backend error details safely.
- Prefer domain-local components when a page is already split into a folder.

## Verification

Run `npm run lint` for TypeScript validation and `npm run build` for integration. Exercise important interaction flows in the browser when behavior changes.
