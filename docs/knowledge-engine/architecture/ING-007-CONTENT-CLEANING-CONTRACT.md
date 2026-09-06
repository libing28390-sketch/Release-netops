# ING-007 content-cleaning contract

ING-007 is the boundary between structural parsing and knowledge extraction.
It consumes the bounded `ParsedDocument` from ING-006 and emits a
`CleanedDocument` with the same format/text/block shape plus cleaner identity,
status, warnings and auditable removed-region records.

For HTML, the cleaner requires the original bytes in addition to the parsed
document. This is intentional: a flattened block list no longer contains the
`hidden`, `aria-hidden`, CSS, class, role or element information needed to
remove non-body content safely. Missing bytes therefore fail with
`CLEAN_HTML_RAW_REQUIRED` instead of silently publishing uncleaned HTML.

The standard-library HTML state machine drops executable regions (`script`,
`style`, `template`, `noscript`, frames and embedded/canvas content), head,
navigation/header/footer/aside/form/menu/dialog regions, hidden attributes and
CSS, and common advertising or boilerplate markers. Comments are ignored.
`main`, `article`, headings, paragraphs, lists and preformatted code remain
available as typed blocks with line/column locators. Bodyless vendor fragments
are supported; content left empty is returned as `empty_after_cleaning` and is
not a publication decision.

Markdown, TXT and PDF retain their parsed blocks under the same result shape;
the stage records zero removed regions and an explicit cleaner identity. No
network, filesystem or persistence operation is performed. Raw bytes are
never logged or stored by this service. Prompt-injection detection,
metadata/entity resolution, chunking and publication remain later stages.

Rollback is an operational routing decision: disable the cleaner and route
only to the existing quarantined/V1 path. The system must not publish
uncleaned HTML as a normal knowledge document.
