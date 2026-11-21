# ING-005 enterprise SOP contract

Enterprise SOP input is a separate trust domain from official vendor
documentation. The multipart endpoint accepts one tenant-owned file and no
external URL. The server generates an internal, non-network source URI and
forces `source_type=enterprise`, `source_kind=enterprise`,
`trust_level=internal`, `document_kind=enterprise_sop`, and
`classification=INTERNAL`.

The file uses the ING-004 boundary for size, basename, type, PDF magic and
UTF-8 checks. The server computes the SHA-256 and records owner, department,
capture facts and a `tenant_owned_local_file_hash` proof under the immutable
Source Version metadata. An uploader cannot promote the document to PUBLIC or
OFFICIAL and cannot smuggle an external URL into the source identity.

The job is tenant-scoped and idempotent and stops at `fetched` with
`continuation_required=true`. No network request, parser, publication or V1
row rewrite happens in this task.
