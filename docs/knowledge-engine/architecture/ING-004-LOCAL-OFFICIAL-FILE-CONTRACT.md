# ING-004 local official-file contract

ING-004 accepts one local file only through the multipart upload boundary. A
caller cannot provide a server filesystem path. The service reads at most 20 MB
in memory, rejects empty files, unsafe basenames, unsupported extensions,
content-type mismatches, invalid PDF magic and binary/non-UTF-8 text.

The upload is not trusted merely because it is local. The request must carry a
reviewed official URL, vendor, product family, primary/compatibility version
scope and terms decision. The URL is checked by the CAT-001/CAT-003 registry
gate before the ING-001 job is created. `evidence_url` is server-normalized and
must equal that canonical official URL.

The SHA-256, byte size, filename, detected type, capture actor/time, review
facts and source URL are generated or checked by the server and stored under
`source_version.metadata.provenance`. The source version uses the existing
immutable Source Registry boundary and a hash-only memory storage marker; the
API response, audit event and this task never contain the file body. A replay
uses tenant + source + content idempotency and does not create a second version.

The job stops at `fetched` with `continuation_required=true`; parsing, chunking,
embedding, indexing and publication are owned by later tasks.
