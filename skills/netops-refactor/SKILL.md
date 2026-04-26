# NetOps App Refactor Skill

## Purpose
Safely split `src/App.tsx` into hooks/utils/pages while keeping behavior stable.

## When to Use
- Large `App.tsx` maintenance
- Repeated state/effect extraction
- Runtime regressions after refactor

## Workflow
1. Identify one isolated block (state+effects or pure helpers).
2. Move to `src/hooks/*` or `src/utils/*`.
3. Keep public names stable in `App.tsx`.
4. Run `npm run build`.
5. Continue with next isolated block.

## Guardrails
- Do not change API payload contracts during refactor.
- Avoid broad rewrites; keep each patch focused.
- Validate after every extraction step.
