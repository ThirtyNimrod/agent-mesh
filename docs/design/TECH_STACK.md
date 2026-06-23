# Tech Stack

Every technology in `agent-mesh`, why it was chosen, what was considered instead, and the version policy. Verified against the ecosystem as of **June 2026**.

---

## Summary table

| Layer | Choice | Version policy | Why |
|---|---|---|---|
| Language | **Python** | 3.12.x | Best-supported MCP SDK + FAISS/LangGraph all first-class in Python |
| MCP framework | **MCP Python SDK — `FastMCP`** (`from mcp.server.fastmcp import FastMCP`) | `mcp>=1.27,<2` | Official/canonical; decorator tools; auto schema from type hints; ships Streamable HTTP |
| Validation | **Pydantic v2** | `pydantic>=2.7,<3` | Native FastMCP integration; declarative input schemas |
| MCP transport | **Streamable HTTP** (stateless, JSON) | n/a | Required for multi-container topology; replaces deprecated SSE |
| Vector index | **FAISS** (`faiss-cpu`) | `faiss-cpu>=1.8,<2` | Mature, exact flat search, trivial to embed; no server to run |
| Metadata store | **SQLite** (stdlib `sqlite3`) | bundled | Zero-dependency durable store; source of truth for memory + audit |
| Embeddings | **Ollama `nomic-embed-text`** | model tag | Local, small (~275 MB), good quality; avoids pulling `torch` |
| LLM runtime | **Ollama** (host) | latest | Native GPU; already installed; OpenAI-compatible + native API |
| LLM model | **`qwen3.5:4b`** | model tag | Native tool-calling, 256K ctx, ~3.4 GB → fits 8 GB VRAM |
| Orchestration | **LangGraph** | `langgraph>=0.2` (pin after first run) | Stateful graph; deterministic pipeline + optional ReAct |
| LLM binding | **`langchain-ollama` (`ChatOllama`)** | `langchain-ollama>=0.2` | Surfaces real token counts; clean LangChain integration |
| MCP↔LangChain | **`langchain-mcp-adapters` (`MultiServerMCPClient`)** | `langchain-mcp-adapters>=0.1` | Loads MCP tools as LangChain tools across multiple servers |
| Doc conversion | **`pypandoc` + PyMuPDF** (reference) | see below | Public converters so the demo runs standalone; pluggable |
| Packaging | **Docker + Docker Compose** | Compose v2 | One-command mesh; isolates the 3 servers + orchestrator |
| Tests | **pytest + pytest-asyncio** | latest | Async tools need async tests |
| Inspector | **MCP Inspector** (`npx @modelcontextprotocol/inspector`) | latest | Manual tool exercising over the wire (Node, optional) |

> **Version policy in one line:** the MCP/Pydantic/FAISS pins are stable and asserted. The LangChain-family packages move quickly — the listed values are *lower bounds reflecting the APIs used*. Install latest, confirm the demo runs, then **freeze a lockfile** (`pip freeze > requirements.lock`) and pin from there. See [Versioning & pinning](#versioning--pinning).

---

## Component-by-component rationale

### Language: Python 3.12

The whole target ecosystem — MCP Python SDK, FAISS, LangGraph, `langchain-ollama` — is Python-first and best documented there. 3.12 is current-stable, fast, and supported by every dependency. (The MCP SDK has a TypeScript option that is excellent for some environments, but mixing languages here would add no value and split the codebase.)

### MCP framework: FastMCP from the official SDK

The official `mcp` package bundles **FastMCP**, which turns a typed Python function into a fully-described MCP tool (name, JSON input schema, annotations) with a single decorator. It supports both stdio and Streamable HTTP from one `mcp.run(...)` call.

- **Version:** the stable line is `mcp` v1.x (current ~1.28). v2 is in alpha and pre-releases are not auto-selected; we pin `mcp>=1.27,<2` to stay on stable and avoid a surprise v2 jump.
- **Considered:** the standalone **FastMCP** project (PrefectHQ/`jlowin`, now v3.x) is more feature-rich (nicer client, deploy helpers, first-class OAuth). It is a great choice if you later want managed deployment; for a minimal, canonical, dependency-light showcase the in-SDK FastMCP is the cleaner baseline. Swapping later is low-cost because the decorator API is nearly identical.
- **Considered:** FastAPI-MCP (wrap an existing FastAPI app) — only makes sense if you already have FastAPI routes; we don't.

### Validation: Pydantic v2

FastMCP reads Pydantic models to generate input schemas and to validate tool arguments before our code runs. v2 idioms throughout: `model_config = ConfigDict(...)`, `field_validator` + `@classmethod`, `model_dump()`. `extra='forbid'` and `str_strip_whitespace=True` keep inputs tight.

### Transport: Streamable HTTP, stateless, JSON

- **Why HTTP:** separate containers must be reachable over the network; stdio (subprocess-per-client) cannot span containers. (See `ARCHITECTURE.md` §2.)
- **Why stateless + `json_response=True`:** `MultiServerMCPClient` opens a fresh session per tool call, so stateless servers avoid session-not-found errors and scale to replicas with no affinity. JSON responses are simpler than SSE streaming, which we don't need.
- **SSE** is deprecated in favor of Streamable HTTP and is not used.

### Memory: FAISS + SQLite

- **FAISS (`faiss-cpu`)** gives exact nearest-neighbour search with zero infrastructure — it's a library, not a server. `IndexIDMap(IndexFlatIP)` on normalized vectors = cosine similarity, exact, and fast at laptop scale.
- **SQLite** stores the text + metadata and is the **source of truth**; the FAISS index is rebuildable from it. SQLite is in the stdlib — no extra dependency, fully durable, transactional.
- **Considered:** a dedicated vector DB (Qdrant/Chroma/pgvector). All are excellent but introduce another service to run and dwarf the need at this scale. The FAISS+SQLite combo is intentionally the smallest thing that is still production-shaped, and the source-of-truth split means migrating to Qdrant later is a contained change.
- **GPU FAISS** (`faiss-gpu`) is unnecessary here and notoriously finicky to install; CPU search over a small corpus is instant.
- **NumPy compatibility:** `faiss-cpu` ↔ NumPy ABI can bite. Pin a known-good pair (e.g. recent `faiss-cpu` with `numpy>=1.26`); validate on first install and freeze.

### Embeddings: Ollama `nomic-embed-text`

- Keeps embeddings **local** and reuses the Ollama runtime that's already serving the chat model — no second inference stack.
- ~275 MB, 768-dim, strong retrieval quality for its size, coexists with `qwen3.5:4b` in 8 GB VRAM.
- **Avoids `torch`/`sentence-transformers`** in the server image, keeping it lean.
- **Fallback:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU) is available behind a config flag for fully offline/no-Ollama embedding. The embedding **dimension is read from config** so the FAISS index always matches the active model.

### LLM runtime + model: Ollama, `qwen3.5:4b`

- **Why Ollama on the host:** native GPU on the RTX 2070, reuses the existing model cache at `D:\.ollama\models`, and is trivially reachable from containers via `host.docker.internal`. (See `ARCHITECTURE.md` §3.)
- **Why `qwen3.5:4b` specifically:**
  - **Native tool-calling** — required for the optional ReAct path and useful generally.
  - **256K context** — comfortably ingests converted documents.
  - **~3.4 GB (Q4_K_M, 4.66B params)** — fits in 8 GB VRAM with headroom for the embedding model.
  - **Thinking is off by default** for the small Qwen3.5 models — good for latency in a pipeline; can be enabled per-call if deeper reasoning is wanted.
- **Fits the hardware:** model (~3.4 GB) + embeddings (~0.3 GB) + KV cache leaves room on 8 GB. A 7B/8B model would also fit but with less margin and higher latency; 4B is the sweet spot for an interactive laptop demo.

### Orchestration: LangGraph (+ ChatOllama + MCP adapters)

- **LangGraph** models the pipeline as an explicit `StateGraph`, giving deterministic, testable, node-by-node control — the right tool given a 4B model that shouldn't free-plan a multi-step workflow. The same library's `create_react_agent` provides the optional autonomous variant.
- **`langchain-ollama` `ChatOllama`** is the binding to local Ollama and **exposes real token counts** (`prompt_eval_count`/`eval_count`) that the audit wrapper records.
- **`langchain-mcp-adapters` `MultiServerMCPClient`** connects to all three servers at once and converts their MCP tools into LangChain tools the graph can call:
  ```python
  client = MultiServerMCPClient({
      "memory":     {"url": "http://memory-server:8001/mcp",      "transport": "streamable_http"},
      "filebridge": {"url": "http://file-bridge-server:8002/mcp", "transport": "streamable_http"},
      "audit":      {"url": "http://prompt-audit-server:8003/mcp","transport": "streamable_http"},
  })
  tools = await client.get_tools()
  ```
  > The transport key is `"streamable_http"`; some adapter versions also accept the alias `"http"`. Confirm against your installed version.

### Doc conversion: pypandoc + PyMuPDF (reference, pluggable)

- **`pypandoc`** (needs the `pandoc` binary, installed in the file-bridge image) covers markdown/HTML/docx/rST conversions broadly.
- **PyMuPDF (`pymupdf`)** handles PDF→text extraction.
- Plain text passthrough for `.txt`.
- These exist so the public demo runs with no proprietary code. A private engine (e.g. *adla-badli*) implementing the documented `Converter` protocol drops in without touching the MCP surface. (See `ARCHITECTURE.md` §9.)

### Packaging: Docker Compose

One `docker compose up` brings up all three servers plus the orchestrator on a private network, with healthchecks and volumes for the SQLite/FAISS data. Compose is the lightest way to express "spin up the whole mesh," matches the requirement exactly, and keeps each server's dependencies isolated in its own image.

### Testing & inspection

- **pytest + pytest-asyncio** — tools are `async`, so tests are too. MCP's in-memory transport allows fast tool tests without spinning up HTTP.
- **MCP Inspector** (`npx @modelcontextprotocol/inspector`) — point it at `http://localhost:<port>/mcp` to exercise tools manually over the real wire. Requires Node; optional.

---

## Versioning & pinning

`requirements.txt` ships **annotated lower bounds**. The recommended flow:

1. `pip install -r requirements.txt`
2. Run the demo end-to-end (`docker compose up`, then the pipeline).
3. `pip freeze > requirements.lock` and commit the lock.
4. For reproducible images, the Dockerfiles install from the lock.

Why not hard-pin everything now? The MCP/Pydantic/FAISS lines are stable and pinned with ranges. The LangChain-family packages move quickly — the listed values are *lower bounds reflecting the APIs used*. Install latest, confirm the demo runs, then **freeze a lockfile** (`pip freeze > requirements.lock`) and pin from there. See [Versioning & pinning](#versioning--pinning).

---

## Dependency map (who needs what)

Keeping server images lean: the servers do **not** depend on LangChain, and the orchestrator does **not** depend on FAISS.

| Package | memory-server | file-bridge-server | prompt-audit-server | orchestrator |
|---|:--:|:--:|:--:|:--:|
| `mcp` (FastMCP) | ✅ | ✅ | ✅ | — |
| `pydantic` | ✅ | ✅ | ✅ | ✅ |
| `faiss-cpu`, `numpy` | ✅ | — | — | — |
| `ollama` (client, for embeddings) | ✅ | — | — | — |
| `pypandoc`, `pymupdf` | — | ✅ | — | — |
| `sqlite3` (stdlib) | ✅ | — | ✅ | — |
| `langgraph` | — | — | — | ✅ |
| `langchain-ollama` | — | — | — | ✅ |
| `langchain-mcp-adapters` | — | — | — | ✅ |
| `python-dotenv` | ✅ | ✅ | ✅ | ✅ |

This separation is why the implementation plan recommends **per-service requirements files** for Docker layer caching, with the top-level `requirements.txt` as the convenient "install everything for local dev" superset.
