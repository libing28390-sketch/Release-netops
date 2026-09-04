# CAT-002 Official Source Types

## Contract summary

V1 classifies official sources with explicit types: `official_url`,
`product_page`, `configuration_guide`, `command_reference`, `release_note`,
and version metadata. A source type identifies provenance and collection
handling; it is not authorization to write to a device. `DB-008` stores the
source registry and `CAT-003`/`CAT-004` enforce the downstream validation and
outbound security boundaries.

## Security and rollback

Source type and version are tenant-scoped metadata. Unknown or malformed
types remain pending review. Rollback disables the additive taxonomy while
retaining V1 source rows and their evidence.

## Final conclusion

The official URL, product page, configuration guide, command reference,
release note, version, DB-008, CAT-003, and V1 markers are explicitly
documented.

Final Conclusion: PASS
