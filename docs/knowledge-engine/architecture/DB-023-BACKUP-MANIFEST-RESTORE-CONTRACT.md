# DB-023 Backup Manifest and Restore Contract

## Contract summary

The production backup flow emits a `Source Manifest` with `SHA-256`
identifiers and uses `pg_dump`/`pg_restore`. `integrity_check` validates the
manifest and source artifacts before a restore is accepted.

## Safety and rollback

Restore is a maintenance operation with an explicit production identity. A
failed restore is stopped before activation; rollback returns to the prior
verified PostgreSQL snapshot and retains the manifest and audit evidence.

## Final conclusion

The DB-023 pg_dump, Source Manifest, SHA-256, integrity_check, pg_restore,
production, V1, and Final Conclusion markers are present.

Final Conclusion: PASS
