# CHK-016 Offline Chunk experiment walkthrough

The experiment compares four named configurations against three fixed network
operations documents: `baseline_v2`, `balanced_network`,
`compact_retrieval`, and `structure_first`.  It records the corpus hash,
configuration hash, chunk/token distribution, Parent/Child and Neighbor
integrity, CLI/code-fence fidelity, version/source-locator completeness,
determinism fingerprint and bounded latency.

The current run passes every structural and lineage gate.  The report's
data-derived recommendation is `baseline_v2` for this small corpus; this
does not change the production default.  Compactness and quality should be
re-evaluated against a larger labeled corpus before a production rollout.

This is a pure in-memory QA experiment.  It does not connect to PostgreSQL or
SQLite, does not call an embedding provider, and creates no persistent rows.
PostgreSQL remains the only persistence acceptance backend for database tasks.
