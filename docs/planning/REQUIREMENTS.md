# Requirements

Functional and non-functional requirements for `agent-mesh`, the target environment, and acceptance criteria. Requirement IDs are stable references used elsewhere in the docs.

---

## 1. Scope

`agent-mesh` delivers three independent MCP servers (memory, file conversion, LLM auditing) and one LangGraph orchestrator that uses all three to run a document-processing pipeline locally against an Ollama model. Everything must come up with a single command and run on a single laptop with an 8 GB GPU.

**In scope:** the three servers, the orchestrator, Docker Compose packaging, tests, evaluation suites, documentation.

**Out of scope (this version):** authentication on HTTP endpoints, horizontal scaling, hosted/remote deployment, a UI beyond CLI output, a non-FAISS vector backend.

---

## 2. Target environment

The reference machine (all sizing and performance targets assume this):

| Resource | Spec |
|---|---|
| CPU | Intel Core i7-9750H @ 2.60 GHz (6C/12T) |
| RAM | 16 GB (≈15.8 GB usable) |
| GPU | NVIDIA GeForce RTX 2070 with Max-Q Design, 8 GB (≈7.9 GB usable) |
| OS | Windows (Docker Desktop + WSL2 backend) |
| LLM runtime | Ollama, native on host, models at `D:\.ollama\models` |
| Primary model | `qwen3.5:4b` (~3.4 GB, Q4_K_M) |
| Embedding model | `nomic-embed-text` (~275 MB) |

**Memory budget (VRAM):** model (~3.4 GB) + embeddings (~0.3 GB) + KV cache/overhead must remain under ~7.9 GB. This is the binding constraint and is satisfied with headroom by the chosen models.

---

## 3. Functional requirements

### 3.1 `memory-server` (FR-MEM)

| ID | Requirement |
|---|---|
| FR-MEM-1 | Expose `memory_add(text, metadata?, tags?)` — embed text, store text+metadata in SQLite, add vector to FAISS, return the new memory id. |
| FR-MEM-2 | Expose `memory_search(query, limit?, min_score?, response_format?)` — embed query, return top-k memories ranked by cosine similarity, each with id, text, score, metadata. |
| FR-MEM-3 | Expose `memory_list(limit?, offset?, response_format?)` — paginated listing of stored memories with `total`, `count`, `has_more`, `next_offset`. |
| FR-MEM-4 | Expose `memory_delete(memory_id)` — remove the memory from SQLite and the FAISS index by id; idempotent (deleting a missing id is a no-op success with a clear note). |
| FR-MEM-5 | SQLite is the source of truth; on startup, if the FAISS index is missing or unreadable, rebuild it from SQLite. |
| FR-MEM-6 | Embedding model and dimension are configurable; the index dimension must match the active embedding model. |
| FR-MEM-7 | Persist FAISS index and SQLite DB to configurable, volume-mounted paths so data survives container restarts. |

### 3.2 `file-bridge-server` (FR-FILE)

| ID | Requirement |
|---|---|
| FR-FILE-1 | Expose `filebridge_convert_file(source_path | source_b64, from_format?, to_format, response_format?)` — convert input to the target format and return the result (text inline, or a path for binary). |
| FR-FILE-2 | Expose `filebridge_list_formats()` — return the currently supported `(from, to)` conversion pairs, reflecting the registered converters. |
| FR-FILE-3 | Expose `filebridge_preview_output(source..., to_format, max_chars?)` — convert and return only the first `max_chars` of the result, for cheap inspection. |
| FR-FILE-4 | Conversion logic must sit behind a `Converter` protocol; the reference converter (pandoc/PyMuPDF/passthrough) ships so the repo runs standalone, and a private engine can be registered without changing the tool surface. |
| FR-FILE-5 | Reject unsupported `(from, to)` pairs with a structured, actionable error that lists supported pairs. |
| FR-FILE-6 | Only read files from an allow-listed input directory; sanitize paths against directory traversal. |

### 3.3 `prompt-audit-server` (FR-AUD)

| ID | Requirement |
|---|---|
| FR-AUD-1 | Expose `audit_log_call(run_id, step, model, tokens_in, tokens_out, latency_ms, quality_score?, metadata?)` — persist one LLM-call record to SQLite; return the record id. |
| FR-AUD-2 | Expose `audit_get_stats(run_id?, since?, response_format?)` — aggregate calls (optionally scoped to a run or time window): call count, total/avg tokens in/out, total/avg latency, avg quality, and a cost breakdown (local compute + notional cloud cost from the configured price table). |
| FR-AUD-3 | Expose `audit_flag_anomaly(metric, k?, scope?)` — return records whose z-score on the chosen metric (`latency_ms` or `total_tokens`) exceeds `k` (default 3.0) over the relevant history. |
| FR-AUD-4 | The cost price table (input/output rate per 1M tokens, currency) is configurable and never hard-coded. |
| FR-AUD-5 | Persist the audit DB to a configurable, volume-mounted path. |

### 3.4 Orchestrator (FR-ORCH)

| ID | Requirement |
|---|---|
| FR-ORCH-1 | Connect to all three servers via a single `MultiServerMCPClient` and load their tools. |
| FR-ORCH-2 | Run a deterministic LangGraph pipeline: ingest → convert → extract → store → summarize → report. |
| FR-ORCH-3 | Use `qwen3.5:4b` via `ChatOllama` for the `extract` and `summarize` steps only. |
| FR-ORCH-4 | Wrap every LLM call so that token counts, latency, and a quality score are logged to `prompt-audit-server` under a shared `run_id`. |
| FR-ORCH-5 | Produce a final output containing the summary plus a cost/quality report from `audit_get_stats(run_id)`. |
| FR-ORCH-6 | Be runnable in one command with a default sample input, and accept a `--input <path>` override. |
| FR-ORCH-7 | Provide an optional `--react` flag selecting the autonomous `create_react_agent` variant over the same tools. |
| FR-ORCH-8 | Degrade gracefully: a failed conversion or unreachable dependency yields a clear, recorded error rather than a crash. |

### 3.5 Cross-cutting / protocol (FR-X)

| ID | Requirement |
|---|---|
| FR-X-1 | All servers run over Streamable HTTP (stateless, JSON) for the compose deployment, and support a `--stdio` dev mode. |
| FR-X-2 | All tools use Pydantic input models with typed, described, constrained fields. |
| FR-X-3 | All tools declare annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). |
| FR-X-4 | Tools support `response_format` of `markdown` (default, human-readable) and `json` (machine-readable) where they return data. |
| FR-X-5 | List tools implement pagination (`limit`/`offset`, `has_more`, `next_offset`, `total`). |
| FR-X-6 | Tool errors are returned inside the result (actionable text + error flag), not raised as protocol-level failures. |
| FR-X-7 | All configuration (ports, Ollama URL, model names, DB/index paths, price table) comes from environment/`.env`; no secrets or hosts hard-coded. |

---

## 4. Non-functional requirements

### 4.1 Performance (on the reference machine)

| ID | Requirement | Target |
|---|---|---|
| NFR-PERF-1 | `memory_search` latency (excluding embedding) over ≤10k memories | < 50 ms |
| NFR-PERF-2 | Single embedding call (`nomic-embed-text`) | < 300 ms |
| NFR-PERF-3 | End-to-end demo pipeline on the bundled sample (2 LLM calls) | < 30 s wall-clock |
| NFR-PERF-4 | Peak VRAM with chat + embedding models loaded | < 7.0 GB |
| NFR-PERF-5 | Server cold start (container ready / healthcheck passing) | < 10 s each |

### 4.2 Reliability

| ID | Requirement |
|---|---|
| NFR-REL-1 | Memory and audit data survive container restarts (volume-mounted SQLite + FAISS). |
| NFR-REL-2 | FAISS index is recoverable from SQLite if lost. |
| NFR-REL-3 | Orchestrator waits for server healthchecks before running (no race on startup). |
| NFR-REL-4 | No single tool failure crashes a server process. |

### 4.3 Maintainability

| ID | Requirement |
|---|---|
| NFR-MAINT-1 | Each server ≤ ~150 LOC of core logic; shared code (config, response formatting, errors) lives in `common/`, not duplicated. |
| NFR-MAINT-2 | Full type hints; Pydantic for all inputs; no manual input validation. |
| NFR-MAINT-3 | Server images depend only on what they need (no LangChain in servers, no FAISS in orchestrator). |
| NFR-MAINT-4 | Reproducible builds via a committed lockfile. |

### 4.4 Security

| ID | Requirement |
|---|---|
| NFR-SEC-1 | Pydantic validation on all tool inputs; path sanitization in file-bridge. |
| NFR-SEC-2 | No secrets in source; configuration via environment. |
| NFR-SEC-3 | Server ports not published to the host except deliberately (e.g. for the Inspector). |
| NFR-SEC-4 | Documented path to add OAuth 2.1 before any remote exposure (deferred, not implemented). |

### 4.5 Portability

| ID | Requirement |
|---|---|
| NFR-PORT-1 | Runs on Windows (Docker Desktop/WSL2), and on Linux/macOS with the documented `host.docker.internal` handling. |
| NFR-PORT-2 | Works with any Ollama model exposing tool-calling; model name is configurable (`qwen3.5:4b` is the default/tested one). |

### 4.6 Documentation & IP

| ID | Requirement |
|---|---|
| NFR-DOC-1 | Each server documents every tool (schema, annotations, errors, ≥1 example). |
| NFR-DOC-2 | A one-command quickstart that works from a clean checkout (after model pull). |
| NFR-IP-1 | No proprietary source, data, prompts, schemas, or weights are present or required; only public dependencies and original code. |

---

## 5. Acceptance criteria (definition of done)

The project is "done" for v1 when **all** of the following hold:

1. `docker compose up --build` brings up three healthy servers and the orchestrator. *(FR-X-1, NFR-REL-3)*
2. The demo pipeline runs on the bundled sample in one command and prints a summary **and** a cost/quality report. *(FR-ORCH-2, FR-ORCH-5, NFR-PERF-3)*
3. Each server passes its own evaluation suite (≥10 Q&A per server) via the eval harness. *(see `TESTING_AND_EVALUATION.md`)*
4. Each server is independently usable from the MCP Inspector over Streamable HTTP. *(FR-X-1)*
5. Memory persists across a container restart, and the FAISS index rebuilds from SQLite when deleted. *(NFR-REL-1, NFR-REL-2)*
6. Token counts in audit records match Ollama's reported counts for the same calls. *(FR-AUD-1, FR-ORCH-4)*
7. `audit_flag_anomaly` flags an injected outlier (e.g. an artificially slow call). *(FR-AUD-3)*
8. A private converter implementing the `Converter` protocol can be registered and appears in `filebridge_list_formats` with **no change** to the MCP tool surface. *(FR-FILE-4)*
9. Peak VRAM stays under target with both models loaded. *(NFR-PERF-4)*
10. All tools declare Pydantic schemas + annotations; the quality checklist in `TESTING_AND_EVALUATION.md` passes. *(FR-X-2, FR-X-3)*

---

## 6. Assumptions & dependencies

- Ollama is installed on the host, the two models are pulled, and Ollama binds `0.0.0.0:11434` so containers can reach it.
- Docker Desktop (WSL2 backend) is available; `host.docker.internal` resolves to the host.
- The reference converter requires the `pandoc` binary (installed in the file-bridge image) and PyMuPDF.
- Network access is available at build time to install Python packages and the pandoc binary.
- A private conversion engine (if used) is supplied separately and is **not** required for the public demo.
