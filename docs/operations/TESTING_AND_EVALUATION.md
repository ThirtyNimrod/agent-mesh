# Testing & Evaluation

How `agent-mesh` is verified: a test pyramid for correctness, the MCP Inspector for manual wire-level checks, an MCP-style evaluation harness for "can an LLM actually use these tools," and a final quality checklist.

---

## 1. Test pyramid

```
        ▲  E2E: full pipeline against the sample (few, slow)
       ---
      ──────  Integration: each server over Streamable HTTP (some)
     ──────────
    ──────────────  Unit: store/converter/stats logic (many, fast)
```

### 1.1 Unit tests (fast, no network)

Test the pure logic directly, and tools via MCP's **in-memory transport** (no HTTP, no containers).

Current unit test files and what they cover:

| File | Coverage |
|---|---|
| `tests/test_memory.py` | `add`/`search` ranking; `delete` removes from both stores; rebuild-from-SQLite produces correct neighbors |
| `tests/test_audit.py` | `stats` aggregation (counts, averages, p95); `cost_block` matches price table; `z_anomalies` flags planted outlier |
| `tests/test_filebridge.py` | `_safe_path` rejects `../` traversal; passthrough converter; `all_pairs()` registry |
| `tests/test_converters.py` | All converter engines; `markdown->text` works **without pandoc**; registry `find`/`all_pairs`; pandoc tests auto-skipped if binary absent |
| `tests/test_orchestrator_utils.py` | `parse_text` (plain string, JSON, MCP content-block list, empty); `parse_points` (JSON, fenced, bullet fallback); `parse_memory_id` (string, content block, missing key) |

```python
# example: in-memory tool test (pytest-asyncio)
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect
import servers.memory_server as srv

@pytest.mark.asyncio
async def test_memory_add_then_search(tmp_path, monkeypatch):
    # point DB/index at tmp_path, stub embed() to a deterministic vector
    async with connect(srv.mcp._mcp_server) as session:
        await session.call_tool("memory_add", {"params": {"text": "alpha beta"}})
        res = await session.call_tool("memory_search", {"params": {"query": "alpha", "limit": 1}})
        assert "alpha beta" in res.content[0].text
```

> Stub the Ollama embedding call in unit tests with a deterministic fake vector so tests are hermetic and don't require a running model.

### 1.2 Integration tests (real wire, real backends)

Bring up one server over Streamable HTTP (or via compose) and exercise it through a real MCP client.

- Connect with `streamablehttp_client(".../mcp")` → `ClientSession` → `initialize()` → `call_tool`.
- **memory:** persistence across a restart (write, restart container, read); delete `memory.faiss`, restart, confirm rebuild.
- **file-bridge:** convert a real `.pdf`/`.md`; confirm `list_formats` matches the registry.
- **audit:** log → `get_stats` → `flag_anomaly` round-trip with a planted slow call.

### 1.3 End-to-end test (the demo)

Run the orchestrator against `examples/sample.md` (requires Ollama + models) and assert:
- a non-empty `summary` is produced;
- ≥1 memory was stored (`memory_ids` non-empty);
- audit token counts **equal** Ollama's reported counts for the same calls (acceptance #6);
- the report contains both local and notional-cloud cost;
- wall-clock < 30 s on the reference machine (NFR-PERF-3).

Mark E2E with a `@pytest.mark.e2e` so it can be skipped in environments without a GPU/Ollama.

---

## 2. MCP Inspector (manual, wire-level)

The Inspector exercises tools exactly as a remote client would.

```bash
# publish a server port temporarily (see compose notes), then:
npx @modelcontextprotocol/inspector
# In the UI: transport = "Streamable HTTP", URL = http://localhost:8001/mcp
```

Use it to: confirm advertised tool schemas/annotations, try valid + invalid inputs, and verify error envelopes are actionable. (Requires Node; optional but recommended before publishing.)

---

## 3. Evaluation harness (can an LLM use the tools?)

Beyond unit correctness, MCP servers should be evaluated on whether a model can **accomplish realistic tasks** with them. Each server gets an `evals/<server>.xml` suite of ≥10 question/answer pairs.

Each question must be:
- **Independent** — not relying on other questions.
- **Read-only** — only non-destructive tools.
- **Complex** — needs multiple tool calls / real exploration.
- **Realistic** — a task a human would actually want.
- **Verifiable** — a single answer checkable by string comparison.
- **Stable** — the answer won't change over time.

Format:
```xml
<evaluation>
  <qa_pair>
    <question>After loading the three architecture notes, which server is described as the source of truth for memory? Answer with the server name.</question>
    <answer>SQLite</answer>
  </qa_pair>
  <!-- ≥10 pairs -->
</evaluation>
```

**Process per server** (seed it with deterministic fixtures first):
1. **Inventory** the server's tools.
2. **Explore** with read-only calls to learn what data/answers exist.
3. **Author 10 questions** whose answers you verify by solving them yourself.
4. **Run** the suite: a small driver loads tools via `MultiServerMCPClient`, gives the model each question, and string-compares the model's final answer to the expected one.

Per-server seeds:
- **memory:** pre-load a known set of memories; ask retrieval questions ("which memory has tag X and the highest similarity to …").
- **file-bridge:** ship fixture files; ask conversion/preview questions ("what is the first heading after converting fixture A to text?").
- **audit:** pre-load a fixed `calls` dataset; ask stats/anomaly questions ("which run has the highest average output tokens?").

---

## 4. Quality checklist (gate before "done")

Adapted from MCP best practices; all must pass.

### Tool configuration
- [ ] Every tool has a service-prefixed snake_case name (`memory_add`, `filebridge_convert_file`, `audit_log_call`).
- [ ] Every tool declares annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) and they match real behavior.
- [ ] Every tool input is a Pydantic `BaseModel` with typed, **described**, constrained `Field`s.
- [ ] Docstrings describe behavior and the output schema for dict/JSON returns.

### Behavior
- [ ] Data tools support `response_format` = `markdown` (default) and `json`.
- [ ] List tools paginate (`limit`/`offset`, `has_more`, `next_offset`, `total`).
- [ ] Errors are returned **inside results** with a suggested next step (no protocol-level crashes).
- [ ] Destructive/idempotent semantics hold (`memory_delete` idempotent; deleting a missing id is a no-op success).

### Implementation quality
- [ ] Shared logic (config, formatting, pagination, errors) lives in `common/`; no copy-paste across tools (NFR-MAINT-1).
- [ ] All I/O is `async`; HTTP/embedding calls use proper timeouts.
- [ ] Server images depend only on what they need (no LangChain in servers, no FAISS in orchestrator).
- [ ] Type hints throughout; module constants in UPPER_CASE.

### Security
- [ ] File paths sanitized; file-bridge only reads inside the allow-listed dir.
- [ ] No secrets/hosts hard-coded; all via env/`.env`.
- [ ] Server ports unpublished by default.

### System / runtime
- [ ] `python servers/<x>_server.py --stdio` starts (smoke test).
- [ ] `docker compose up --build` → three healthy servers + orchestrator runs the demo.
- [ ] Memory persists across restart; FAISS rebuilds from SQLite when deleted.
- [ ] Audit token counts match Ollama; `flag_anomaly` catches a planted outlier.
- [ ] Peak VRAM under target with both models loaded.

---

## 5. CI suggestion

A minimal GitHub Actions workflow can run the **unit** layer on every push (hermetic — embedding/LLM calls stubbed, no GPU needed). Integration/E2E run locally or on a self-hosted runner with Ollama + a GPU, since they need real inference. Lint (`ruff`) and type-check (`mypy`) gate alongside unit tests.
