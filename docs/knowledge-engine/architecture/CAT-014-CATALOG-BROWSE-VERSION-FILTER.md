# CAT-014 Product Catalog Browsing and Version Filtering

CAT-014 extends the CAT-013 read-only management page with the complete Vendor → Family → Series → Model browsing path and an exact, case-insensitive software-version filter. The version filter matches only the reviewed `primary_version` and `compatibility_version` values from the catalog seed; it cannot reinterpret a release as a product identity or select a network driver.

The catalog endpoint accepts the bounded `software_version` query parameter and applies the filter at the service boundary. The page shows both version values in each result row, displays the current hierarchy filters, and provides a single clear action. Empty results are valid and remain visibly tied to the active filters. No persistence, write route, migration, or V1 metadata mutation is introduced.
