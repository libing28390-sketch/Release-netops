# Nexora blob storage

Nexora keeps PostgreSQL metadata separate from PAM recordings and configuration
snapshot blobs.  The provider is selected at deployment time:

```text
STORAGE_BACKEND=local   # default, no extra service
STORAGE_BACKEND=s3      # S3-compatible endpoint, such as SeaweedFS
```

There is no runtime fallback from `s3` to `local`.  A failed upload is recorded
as `storage_status=ERROR` and retried by the existing APScheduler worker. PAM
recordings use an explicit local spool while a session is active; the spool is
not a second final storage backend.

## Local mode

The local provider stores new objects below `STORAGE_LOCAL_ROOT` and keeps the
legacy `backup/` and `data/pam_recordings/` paths readable for old rows. The
legacy paths are not exposed to business code for new objects.

## SeaweedFS mode

The Docker Compose profile provides a single-node `weed mini` service:

```powershell
$env:STORAGE_BACKEND = "s3"
$env:S3_ENDPOINT_URL = "http://seaweedfs:8333"
$env:S3_ACCESS_KEY_ID = "replace-with-a-real-access-key"
$env:S3_SECRET_ACCESS_KEY = "replace-with-a-real-secret-key"
docker compose --profile object-storage up -d
```

The endpoint is internal to the Compose network. Do not publish port 8333 to
the public interface. Replace the example credentials and pin the image version
for a production deployment.

## Legacy migration

Migration is explicit and resumable. It does not delete the old files:

```powershell
python backend/scripts/migrate_storage_objects.py --dry-run
python backend/scripts/migrate_storage_objects.py --limit 100
```

The command migrates only PAM recordings and configuration snapshots. Knowledge
documents, report exports, ticket attachments, and other artifact classes are
outside this first storage boundary.
