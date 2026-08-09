# ING-007 walkthrough

1. `parse_and_clean_document` calls the ING-006 byte-bounded parser.
2. HTML is re-read from the same in-memory bytes by an attribute-aware
   standard-library state machine. Executable, hidden, navigation, header,
   footer, aside, form, ad and other non-body regions are skipped.
3. Remaining blocks keep parser locators and semantic types such as heading,
   paragraph, list item and code. Removed regions record only tag, reason and
   source line/column; body text is not recorded in audit metadata.
4. A document that becomes empty is marked `empty_after_cleaning` with a
   stable warning, so later publication can quarantine it.
5. HTML without a body element is treated as a fragment. If original HTML
   bytes are not available, the service fails closed with
   `CLEAN_HTML_RAW_REQUIRED`.
6. Markdown/TXT/PDF pass through the same `CleanedDocument` contract with no
   region removals. No network or filesystem access is available to the
   cleaner.

Focused verification is in
`backend/tests/ai/test_ing007_content_cleaning.py`.
