# ING-006 document parser contract

ING-006 introduces one `DocumentParserRegistry` and one `ParsedDocument` shape
for HTML, Markdown, TXT, JSON, YAML, CSV, XML, config text, PDF and DOCX. Every parser receives bounded bytes and
returns format, text, structural blocks, metadata, parser identity, status and
warnings. The serialized contract omits text unless a caller explicitly asks
for it, reducing accidental response leakage.

The HTML adapter uses the standard library and emits structural blocks while
marking that ING-007 content cleaning is still required. Markdown reuses the
existing Front Matter parser, TXT/config normalizes UTF-8 line endings, JSON /
YAML / XML / CSV validate and normalize structured content, and PDF/DOCX use
bounded binary adapters. JSON/YAML can additionally use the explicit
`nexora-knowledge-document` envelope to carry metadata and body separately.
A PDF with valid magic but no extractable text is `degraded`, never silently
claimed as rich text.

Format mismatch, empty/oversized bytes, invalid UTF-8/control bytes, malformed
Front Matter, malformed structured content, invalid custom envelopes and
invalid PDF/DOCX magic fail with stable safe codes. The adapter
layer has no HTTP, socket or filesystem input and does not decide trust,
publication, prompt injection or metadata authority.
