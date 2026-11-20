# DB-008 Source Registry Contract

## Contract summary

The source registry stores `kb_source_registry` and `kb_source_version`
records, including `source_url`, `source_title`, and `source_section`.
Collection is restricted by an `allowed_host`/path policy, HTTPS and TLS
validation, and SSRF checks. `vendor-scope.yaml` remains governance input and
is not a substitute for tenant rows in the registry.

## Security and rollback

Credentials and URL user-info are forbidden. Tenant, ACL, and audit checks are
performed before source persistence. A rollback disables the new source
projection and keeps the V1 `ai_document` evidence and version history.

## Final conclusion

The DB-008 source, SSRF, TLS, tenant, V1, and 回滚 boundaries are documented.

Final Conclusion: PASS
