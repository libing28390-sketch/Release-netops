---
name: netops-release
description: Prepare and review Nexora NetOps releases across Vite builds, FastAPI runtime, Windows desktop packaging, Docker, Nginx, Ubuntu scripts, environment configuration, and GitHub Actions. Use for deployment, packaging, versioning, CI, and release-readiness work.
---

# NetOps Release

## Workflow

1. Identify the target: Windows desktop, native Ubuntu, Docker Compose, or CI release artifact.
2. Inspect the relevant workflow and its actual inputs. Read package/Vite, backend startup, environment, Docker/Nginx or desktop configuration only when the selected release path depends on them.
3. Confirm frontend assets, API base paths, WebSockets, static-file serving, database migration order, and writable data paths.
4. Run the quality gate before packaging.
5. Validate secrets are placeholders in tracked examples and real secrets are not committed.
6. Document deployment-impacting environment variables and compatibility changes.

## Constraints

- Production uses PostgreSQL.
- Preserve existing Windows, Docker, and Ubuntu paths unless the request narrows support.
- Treat `.env` as cross-platform data in release scripts: normalize LF/CRLF values before invoking Docker or PostgreSQL, and verify both line-ending forms when changing configuration parsing.
- Do not publish, push tags, deploy, or alter live infrastructure without explicit authorization.
- Keep version values consistent across package, backend version, packaging metadata, and release workflow.

## Verification

Choose checks using netops-quality-gate and the actual affected release path. Run lint/build when frontend output or deployment assets are affected; for filtering-only changes, verify configuration syntax, cleanup and forbidden-path behavior for each target, and relevant release contracts. Formal release candidates still require the full release gate. For packaging changes, validate the target artifact or provide the precise unverified constraint. Avoid duplicate checks by assigning shared verification to one executor.
