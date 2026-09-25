---
name: netops-seaweedfs
description: Use when changing Nexora's SeaweedFS-backed S3 storage, Docker Compose deployment, health checks, persistence, object migration, or backup and recovery guidance.
---

# SeaweedFS in Nexora

Use SeaweedFS through the project's S3 storage provider contract. Keep advice and changes aligned with the deployed image and the current repository configuration.

## Project integration

- Nexora currently runs SeaweedFS as an optional single-node `weed mini` service under the Compose `object-storage` profile. The application uses the S3 API through `backend/services/storage_service.py`; it does not call Master, Filer, or Volume APIs directly. Do not redesign it as a distributed cluster unless the request includes that architecture change.
- Before changing configuration, inspect `docker-compose.yml`, `.env.example`, `scripts/deploy-docker.sh`, `backend/services/storage_service.py`, and the relevant storage tests. The current image uses the mutable `latest` tag, so identify the actual running tag/digest and `weed version` before relying on version-specific behavior.
- In the Compose network, the endpoint is `http://seaweedfs:8333`; `localhost` from the backend container points back to that container. Keep endpoint, bucket, and object key/prefix as separate values. The application uses S3 V4 signing and path-style addressing; preserve the existing client contract unless compatibility work explicitly requires a change.
- Direct Compose use requires the `object-storage` profile. The deployment script selects it for S3 mode and preserves non-placeholder credentials. Provider credentials are encrypted in the database using `CREDENTIAL_ENCRYPTION_KEY`; keep that key stable and never print credentials, full connection strings, or raw provider errors.
- Objects are stored by bucket/key and associated with a provider in application metadata. The `config` and `pam` usage bindings use separate key prefixes. Changing the default provider affects new writes only; existing object references remain bound to their stored provider. Do not silently fall back to local storage or imply that switching providers migrates existing objects.
- The SeaweedFS data is persisted in the `nexora-seaweedfs-data` Docker volume mounted at `/data`. Do not remove, prune, recreate, or relocate it as routine troubleshooting. The current Compose service has no healthcheck, and the backend does not wait for SeaweedFS readiness; startup can precede S3 availability.
- The application's `/api/storage/status` check uses S3 `ListObjectsV2`. It checks endpoint access, credentials, bucket visibility, and list permission; it is not a full upload/download test or a SeaweedFS cluster-health check. The current configuration does not enforce a bucket-wide capacity quota; disk availability follows the Docker data filesystem.

## Changes and operations

- Diagnose S3 failures by separating service DNS/port and proxy routing, TLS, SigV4 credentials/signing, bucket existence and list permission, then object-specific access. Distinguish access denied, missing bucket/object, timeout, and unavailable service. Preserve the existing safe error filtering in API responses and logs.
- For an external S3 provider, verify the bucket and required permissions before connecting; this application does not create the bucket. Confirm supported S3 operations against the exact SeaweedFS release. S3-compatible does not mean every AWS API or policy behavior is identical.
- Before moving objects, inspect `backend/scripts/migrate_storage_objects.py`. Use its dry-run and limit options as appropriate, keep the source objects, and verify the destination and application references. Perform migration only when the user requested it; a provider-setting change alone is not migration authorization.
- Before upgrades, storage maintenance, or disaster-recovery changes, define and validate a backup/restore path for the deployed `weed mini` mode. Consider both object contents and the filer namespace/metadata required to address them. Do not assume replication, a Docker volume lifecycle operation, or a metadata-only snapshot alone is a complete backup. Never run destructive storage commands without explicit authorization and a recoverable plan.
- Check the exact release's official docs, release notes, and security advisories before changing authentication, authorization, S3 policy behavior, or image versions. Do not copy sample credentials or assume that an S3 client sending signed requests proves that the server has authentication enabled.

## Validation

- For storage-service behavior, run the focused tests in `backend/tests/storage/test_storage_service.py`.
- For Compose, deployment-profile, or environment changes, run `backend/tests/release/test_deploy_docker_storage_contract.py`. If changing proxy bypass for the SeaweedFS service, also run `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`.
- These checks are primarily mocked or static contracts; they do not prove a live SeaweedFS upload/download. For compatibility or upgrade work, report separately whether contract tests and an authorized S3 end-to-end check were completed.
- Use `netops-backend` for API/storage-service contract changes, `netops-release` for deployment changes, and `netops-quality-gate` to select focused repository checks.

## Official references

Use the documentation and code for the deployed release when they differ from the moving wiki or `master` branch:

- [SeaweedFS README and architecture](https://github.com/seaweedfs/seaweedfs#architecture)
- [Components](https://github.com/seaweedfs/seaweedfs/wiki/Components)
- [`weed mini` quick start](https://github.com/seaweedfs/seaweedfs/wiki/Quick-Start-with-weed-mini)
- [Docker Compose for S3](https://github.com/seaweedfs/seaweedfs/wiki/Docker-Compose-for-S3)
- [Amazon S3 API and compatibility](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)
- [Filer stores](https://github.com/seaweedfs/seaweedfs/wiki/Filer-Stores)
- [Data backup](https://github.com/seaweedfs/seaweedfs/wiki/Data-Backup)
- [Asynchronous content backup](https://github.com/seaweedfs/seaweedfs/wiki/Async-Backup) and [filer metadata backup](https://github.com/seaweedfs/seaweedfs/wiki/Async-Filer-Metadata-Backup)
- [System metrics](https://github.com/seaweedfs/seaweedfs/wiki/System-Metrics)
- [Releases](https://github.com/seaweedfs/seaweedfs/releases) and [security advisories](https://github.com/seaweedfs/seaweedfs/security/advisories)
