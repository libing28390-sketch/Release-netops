# DB-007 OS and Software Structure

## Contract summary

Operating-system family, generation, release train, and software version are
orthogonal to product identity. The indexed fields are `kb_os_family`,
`kb_os_generation`, `kb_release_train`, and `kb_software_version`; a document
may also expose `cli_platform` in its retrieval metadata. `train_match` and
`release_match` are applicability checks, not authorization checks.

Unknown values are represented as `UNKNOWN` and require review. The legacy
`ai_document` projection and `intent_parser.py` remain compatibility paths
until the catalog migration is active.

## Security and rollback

Tenant scope and ACL are evaluated independently of software version. A
rollback disables the new catalog projection and preserves original V1
metadata; it never rewrites a document's asserted version.

## Final conclusion

The DB-007 fields, UNKNOWN behavior, tenant boundary, `ai_document`, parser,
V1, and 回滚 evidence are present.

Final Conclusion: PASS
