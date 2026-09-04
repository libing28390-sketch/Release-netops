# DB-024 Capacity, Bloat, and Index Contract

## Contract summary

Capacity probes cover 10,000, 100,000, and 1,000,000-row scenarios. They
record `pg_total_relation_size`, `pg_indexes_size`, and dead/live row ratios
to distinguish table growth from index growth and bloat.

## Safety and rollback

The probe is read-only and PostgreSQL-specific. SQLite appears only as a
legacy comparison label in the capacity evidence, not as a CI fixture or
production persistence backend. Any index change is separately reviewed and
can be rolled back without deleting source rows.

## Final conclusion

The DB-024 10,000/100,000/1,000,000 scenarios, pg_total_relation_size,
pg_indexes_size, dead/live, SQLite comparison note, V1, and Final Conclusion
markers are documented.

Final Conclusion: PASS
