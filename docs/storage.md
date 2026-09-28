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

Under the “Object Storage” menu, “File Browser” shows a selected profile's
bucket as a lazily loaded folder tree using S3 `ListObjectsV2` with a delimiter.
It shows object keys and copyable `s3://bucket/key` paths, along with the
configured endpoint. Configuration snapshots can be previewed and downloaded
as `.cfg` files through the authenticated application API. Large directories
are paged in batches of 100. Listing requires `ListBucket` permission; preview
and download require administrator access and the selected S3 provider to allow
object reads. The page does not generate presigned or anonymous download URLs.
“Storage Settings” manages provider profiles.

## Object encryption

New S3-backed configuration snapshots are stored as UTF-8 `.cfg` text without
application-level compression or encryption. Their default key layout is
`config/YYYY/MM/DD/<vendor>/<hostname>_<time>_<trigger>_<snapshot-id>.cfg`.
Local-provider configuration snapshots keep their existing application-level
encryption. PAM recordings are stored as their original bytes; Nexora does not
encrypt their contents before S3 upload. Existing `.cfg.gz` and `.cfg.enc`
snapshots remain in their original locations and are still decoded by the
application when previewed or downloaded. Keep `CREDENTIAL_ENCRYPTION_KEY`
stable while those historical objects remain.

With the default usage prefixes, PAM recording keys continue to use
`pam/YYYY/MM/<session-id>.<recording-extension>`; the config key prefix and
PAM recording layout remain independent.

S3 provider Access Key ID and Secret values remain encrypted in PostgreSQL with
AES-256-GCM using `CREDENTIAL_ENCRYPTION_KEY`; this protects provider
credentials, not object contents. Nexora does not set S3 server-side encryption
headers, so at-rest encryption for new objects depends on the S3 provider or
storage volume configuration. Use an HTTPS endpoint when traffic between the
application and S3 service must be protected with TLS.

## Legacy migration

Migration is explicit and resumable. It does not delete the old files:

```powershell
python backend/scripts/migrate_storage_objects.py --dry-run
python backend/scripts/migrate_storage_objects.py --limit 100
```

The command migrates only PAM recordings and configuration snapshots. Knowledge
documents, report exports, ticket attachments, and other artifact classes are
outside this first storage boundary.
