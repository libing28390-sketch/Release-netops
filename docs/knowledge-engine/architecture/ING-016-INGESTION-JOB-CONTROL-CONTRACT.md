# ING-016 Ingestion Job Control Contract

ING-016 closes the operator control-plane boundary around the existing ING-001
state machine. Progress is a server-derived read model. Cancellation is
cooperative: an unclaimed queued job can be acknowledged immediately, while a
running worker must acknowledge at a safe point. Retry never rewinds a terminal
failure in place; it creates a new queued child attempt and keeps the failed
parent and its structured error evidence.

The API is tenant-scoped and uses the dedicated `knowledge_import` permissions
for list/detail/error reads, cancellation, and retry. Error responses contain
only allowlisted codes and safe messages. The implementation remains
process-local until the DB-011 durable Import Job/lease migration is enabled;
V1 reindex rows and generic network-operation jobs are untouched.
