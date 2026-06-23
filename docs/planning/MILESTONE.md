# Milestones

The delivery plan for `agent-mesh`, M0 → M6. Each milestone has a goal, deliverables, exit criteria (testable), and a rough effort estimate. Effort is given in focused half-day units (a "session" ≈ 3–4 hours of solo work); treat as relative sizing, not a commitment.

> Dependency rule: M0 first; M1/M2/M3 can proceed in parallel afterward; M4 needs all three; M5 then M6.

---

## Milestone overview

| ID | Milestone | Depends on | Effort | Headline outcome |
|---|---|---|:--:|---|
| **M0** | Scaffold & shared helpers | — | 1 | Repo skeleton; `common/` importable |
| **M1** | `memory-server` | M0 | 2–3 | Vector memory over MCP, persistent |
| **M2** | `file-bridge-server` | M0 | 2 | Pluggable conversion over MCP |
| **M3** | `prompt-audit-server` | M0 | 2 | Call logging + stats + anomalies |
| **M4** | Orchestrator | M1, M2, M3 | 3–4 | One-command pipeline + cost report |
| **M5** | Docker Compose mesh | M4 | 2 | `docker compose up` runs everything |
| **M6** | Tests, evals, polish | M5 | 3 | Green tests, eval suites, docs done |

Total rough sizing: **15–17 sessions**. Parallelizing M1–M3 compresses wall-clock if more than one person contributes.

---

## M0 — Scaffold & shared helpers

**Goal:** a clean repo skeleton and the shared utilities that stop later duplication.

**Deliverables**
- Directory tree per README.
- `common/config.py` (env-driven `Settings`), `common/responses.py` (format + pagination), `common/errors.py` (error envelope).
- `requirements.txt`, `.env.example`, `examples/sample.md`.
- License + NOTICE (clean-room IP statement).

**Exit criteria**
- `python -c "import common.config, common.responses, common.errors"` succeeds.
- `.env.example` documents every variable the code reads.

**Risks/notes:** keep `common/` framework-agnostic (no MCP/LangChain imports) so all components can use it.

---

## M1 — `memory-server`

**Goal:** persistent, searchable vector memory exposed as MCP tools.

**Deliverables**
- `servers/memory_store.py` (embed via Ollama, FAISS `IndexIDMap(IndexFlatIP)`, SQLite CRUD, index rebuild-from-SQLite).
- `servers/memory_server.py` (`memory_add`/`search`/`list`/`delete` with Pydantic + annotations).
- stdio + Streamable HTTP entrypoints.

**Exit criteria** (maps to FR-MEM-*)
- All four tools callable via MCP Inspector over HTTP.
- Search returns sensible cosine-ranked results; `min_score`/`limit` honored.
- `memory_list` paginates correctly (`has_more`, `next_offset`).
- Data survives a container/process restart; deleting `memory.faiss` triggers a clean rebuild from SQLite on next start.
- `NFR-PERF-1` (search < 50 ms over ≤10k) and `NFR-PERF-2` (embed < 300 ms) met on the reference machine.

**Risks/notes:** FAISS↔NumPy ABI mismatch is the classic install snag — validate the pair and freeze.

---

## M2 — `file-bridge-server`

**Goal:** convert documents to clean text via a pluggable converter, exposed as MCP tools.

**Deliverables**
- `servers/converters/` — `Converter` protocol, registry, and reference converters (pandoc, PyMuPDF, passthrough).
- `servers/file_bridge_server.py` (`filebridge_convert_file`/`list_formats`/`preview_output`), path sanitization.

**Exit criteria** (maps to FR-FILE-*)
- `.md`→`html`, `.pdf`→`text`, `.txt`→`text` all work on sample inputs.
- `filebridge_list_formats` reflects exactly the registered converters.
- Unsupported pair returns a structured error listing supported pairs.
- Directory-traversal attempt on `source_path` is rejected.
- **Pluggability proven:** a stub private converter registered in `servers/converters/` shows up in `list_formats` with no change to the tool surface (FR-FILE-4 / acceptance #8).

**Risks/notes:** the pandoc binary must be present in the image; document it in the Dockerfile.

---

## M3 — `prompt-audit-server`

**Goal:** record every LLM call and turn the log into stats, cost, and anomaly flags.

**Deliverables**
- `servers/audit_store.py` (`calls` table, `log`, `stats` with cost block, z-score `anomalies`).
- `servers/prompt_audit_server.py` (`audit_log_call`/`get_stats`/`flag_anomaly`).

**Exit criteria** (maps to FR-AUD-*)
- A logged call round-trips and appears in `get_stats`.
- `get_stats` cost matches the configured price table; scoping by `run_id`/`since` works.
- `flag_anomaly` flags an injected outlier (e.g. a 5× latency record) and not normal records.
- Audit DB persists across restart.

**Risks/notes:** define the quality-score contract (set by the orchestrator) before M4 so the schema is stable.

---

## M4 — Orchestrator

**Goal:** the demo agent that ties the mesh together and produces a cost report.

**Deliverables**
- `agent/clients.py` (`MultiServerMCPClient` to all three servers; `ChatOllama`).
- `agent/audited.py` (LLM-call wrapper → `audit_log_call`, real token counts from `usage_metadata`).
- `agent/quality.py` (v1 heuristic scorer; optional v2 judge flag).
- `agent/orchestrator.py` (deterministic `StateGraph` pipeline; optional `--react`; CLI).

**Exit criteria** (maps to FR-ORCH-*)
- One command runs ingest→convert→extract→store→summarize→report and prints a summary **and** a cost/quality report.
- Audit token counts equal Ollama's reported counts for the same calls (acceptance #6).
- `--react` runs the autonomous variant over the same tools.
- Graceful degradation: a failed conversion yields a recorded error, not a crash.
- `NFR-PERF-3`: end-to-end on the sample < 30 s.

**Risks/notes:** the 4B model may emit imperfect structured output in `extract` — the node retries once with a stricter prompt, then degrades to storing raw text. Confirm the adapter's transport key (`"streamable_http"` vs `"http"`) for the installed version.

---

## M5 — Docker Compose mesh

**Goal:** the whole mesh up with one command, on the reference hardware.

**Deliverables**
- Per-service slim Dockerfiles (lean deps; pandoc in file-bridge).
- `docker-compose.yml` (3 servers + orchestrator, healthchecks, volumes, `extra_hosts`).
- Host-Ollama wiring documented (`OLLAMA_HOST=0.0.0.0:11434`).

**Exit criteria** (maps to FR-X-1, NFR-REL-3, acceptance #1)
- `docker compose up --build` → three healthy servers + orchestrator runs the demo.
- Containers reach host Ollama via `host.docker.internal`.
- Peak VRAM under target with both models loaded (acceptance #9 / NFR-PERF-4).
- Each server independently reachable by the MCP Inspector when a port is published.

**Risks/notes:** the host must set `OLLAMA_HOST`; otherwise containers can't reach Ollama — call this out prominently in SETUP.

---

## M6 — Tests, evaluations, polish

**Goal:** confidence and presentation quality for a public repo.

**Deliverables**
- Unit + integration + e2e tests (pytest/asyncio; MCP in-memory transport for unit).
- `evals/` — ≥10 read-only Q&A per server, run by the harness.
- `requirements.lock`, `ruff`/`mypy` clean, example outputs in the README.
- Final pass on all docs.

**Exit criteria** (maps to acceptance #3, #5, #7, #10)
- All tests green; each server's eval suite passes.
- Quality checklist in `TESTING_AND_EVALUATION.md` fully ticked.
- A fresh clone + model pull reaches a working demo using only the README/SETUP.

---

## Stretch / post-v1 backlog

Tracked but explicitly out of v1 (see `ARCHITECTURE.md` §12):

| Item | Why later |
|---|---|
| OAuth 2.1 on HTTP endpoints | Only needed before remote exposure; localhost demo doesn't require it |
| Second replica per server | Stateless design already supports it; not needed at one-laptop scale |
| Qdrant/pgvector backend | FAISS+SQLite is sufficient until the corpus grows large |
| Streaming responses to client | The pipeline is batch; streaming adds complexity without demo value |
| LLM-as-judge quality (v2) on by default | Costs an extra call per step; keep opt-in |
| Web UI / dashboard for audit stats | CLI report is enough to showcase governance |

---

## Tracking suggestion

Mirror these milestones as GitHub milestones/issues; the README's status checklist is the at-a-glance view. Each acceptance criterion above is phrased to be directly checkable, so they double as the issue's "definition of done."
