---
name: netops-ai-knowledge
description: Build, debug, and review Nexora NetOps AI, RAG ingestion pipelines, knowledge base collections, vector embeddings, Security Vault redaction, prompt templates, and multi-provider LLM gateways. Use for changes under backend/ai, backend/api/knowledge_*, knowledge services, or frontend AI views.
---

# NetOps AI & Knowledge Base (RAG)

## Workflow

1. Trace the complete AI request lifecycle: user input / document source -> Security Vault redaction -> Chunking & Metadata Extraction -> pgvector / pg_trgm retrieval -> Multi-provider Gateway -> Response formatting.
2. Maintain strict separation between AI orchestration (`backend/ai/`), ingestion pipelines (`backend/services/ingestion_*`), knowledge APIs (`backend/api/knowledge_*`), and frontend AI components (`src/pages/ai/`).
3. Ensure all external document fetching uses `safe_outbound_http.py` with strict SSRF protection and timeout controls.
4. Verify embedding dimensions and distance metrics match the active PostgreSQL vector configuration (`pgvector` cosine/L2 or `pg_trgm` fallback).
5. Always test fallback paths when upstream LLM providers return 429, timeout, or circuit-breaker trips.

## Mandatory Security & RAG Conventions

- **Security Vault Zero-Leakage**: Plaintext passwords, enable secrets, SNMP community strings, private keys, and user tokens must NEVER be sent to external LLM providers. Always invoke `VaultService` / token masking before prompt construction and log emission.
- **Multi-Provider Resilience**:
  - All LLM interactions must route through `backend/ai/gateway/` or provider adapters (`deepseek`, `openai`, `qwen`, `ollama`, `azure_openai`).
  - Respect provider concurrency limits (`AI_PROVIDER_MAX_CONCURRENCY`), tenant concurrency (`AI_TENANT_MAX_CONCURRENCY`), and user concurrency (`AI_USER_MAX_CONCURRENCY`).
  - Circuit breakers must trip on consecutive failure thresholds (`AI_CIRCUIT_FAILURE_THRESHOLD`) and enforce cooldown periods (`AI_CIRCUIT_COOLDOWN_SECONDS`).
- **PostgreSQL Vector & Retrieval**:
  - Vector storage and similarity searches must strictly target PostgreSQL (`pgvector` / `pg_trgm`), respecting transaction isolation.
  - Chunking pipelines must enforce idempotent ingestion leases (`ingestion_job_lease_service.py`) and content deduplication hashes.
  - Retrieval caching must respect TTL and tenant/role-based access controls.
- **Official Catalog & Source Ingestion**:
  - When importing vendor official templates or documentation, validate source URLs against allowed schemes (HTTPS only, no RFC1918 private IPs unless explicitly whitelisted).
  - Clean and normalize extracted text using `document_content_cleaning.py` and `document_metadata_extraction.py`.

## Boundaries

- Core LLM client abstractions, prompt templates, and security interceptors belong in `backend/ai/`.
- Ingestion jobs, document parsers, and catalog sync logic belong in `backend/services/`.
- Knowledge HTTP endpoints belong in `backend/api/knowledge_*.py`.
- Frontend conversational UI, collection management, and evaluation dashboards belong in `src/pages/ai/`.

## Safety and Verification

- Run focused AI tests: `pytest backend/tests/ -k "ai or knowledge"`.
- Validate prompt masking with test fixtures containing synthetic credentials to ensure zero unmasked secrets escape.
- Verify token budgeting and circuit breaker state transitions under simulated network failures.
