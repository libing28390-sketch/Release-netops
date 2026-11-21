# ING-006 walkthrough

```text
bytes + filename + MIME
          |
          v
DocumentParserRegistry.detect_format
          |
   +------+------+------+------+
   | HTML | Markdown | TXT | PDF |
   +------+------+------+------+
          |
          v
same ParsedDocument {format, blocks, metadata, parser, status, warnings}
          |
          v
ING-007 cleaning -> ING-008 security -> metadata/chunk/publication stages
```

The registry is deliberately not a sanitizer or publisher. It gives later
stages one stable hand-off and fails closed on format, size, encoding and magic
errors.

See [ING-006 Evidence](../knowledge-engine-v2/evidence/ING-006.md) and the
[ING-006 contract](../knowledge-engine-v2/architecture/ING-006-DOCUMENT-PARSER-CONTRACT.yaml).
