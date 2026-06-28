# Tests

This folder holds the `agent-mesh` test suite. It's organized as a small test
pyramid: a broad base of **offline unit tests** that run anywhere with no
servers or model, a thin layer of **integration tests** that check the servers
over HTTP, and a single **end-to-end test** that runs the whole pipeline.

For the testing *philosophy* (why the pyramid is shaped this way, the MCP
in-memory transport, the evaluation suites in `evals/`), see
[`../docs/operations/TESTING_AND_EVALUATION.md`](../docs/operations/TESTING_AND_EVALUATION.md).
This file is the practical "what's here and how do I run it" reference.

---

## What each test file covers

| File | Covers | Needs |
|---|---|---|
| `test_memory.py` | `memory-server` store: add + semantic search (with metadata/tags), delete (including idempotent re-delete), and rebuilding the FAISS index from SQLite after the index file is removed. Embeddings are replaced with a deterministic mock, so results are stable. | Offline |
| `test_audit.py` | `prompt-audit-server` store: `log_call` + `get_stats` math (token sums/averages, latency total/avg/p95, quality avg/min, and notional cloud-cost calculation against a fixed price table) and z-score anomaly detection catching a latency outlier. | Offline |
| `test_converters.py` | The converter registry (`find`, `all_pairs`, case-sensitivity, unknown pairs), the passthrough converter (text/markdown/raw bytes), and Markdown→text stripping of headers, bold, links, and inline code. Pandoc cases (markdown→html, html→text) **auto-skip** if the pandoc binary isn't installed. | Offline (pandoc optional) |
| `test_filebridge.py` | `file-bridge-server` path sandboxing (`_safe_path` resolves valid paths and rejects `../` traversal), the passthrough converter, and that the format registry advertises the expected pairs. | Offline |
| `test_orchestrator_utils.py` | The orchestrator's response-parsing helpers — `parse_text`, `parse_points`, and `parse_memory_id` — across plain strings, JSON shapes, MCP content-block lists, code-fenced output, bullet fallbacks, and malformed input. | Offline |
| `test_integration.py` | Each server answers over Streamable HTTP on its configured port (`8001`/`8002`/`8003`). Marked `integration`. **Skips automatically** if a server isn't running. | Servers running |
| `test_e2e.py` | The full LangGraph pipeline via `run_pipeline(...)`: ingest → convert → extract → store → summarize → audit. Marked `e2e` (async). **Skips automatically** unless Ollama *and* all three servers are reachable. Runs against `examples/sample.md`. | Servers + Ollama |

`conftest.py` just puts the repo root on `sys.path` and initializes logging; it
defines no shared fixtures. The per-test isolation (temp databases, mocked
embeddings) lives inside each unit-test file via `tmp_path` and `monkeypatch`.

---

## Environment matrix

| Layer | Servers up? | Ollama up? | Deterministic? | Typical runtime |
|---|---|---|---|---|
| Unit (`test_memory`, `test_audit`, `test_converters`, `test_filebridge`, `test_orchestrator_utils`) | No | No | Yes | seconds |
| Integration (`test_integration`) | Yes | No | Yes | seconds |
| End-to-end (`test_e2e`) | Yes | Yes | No (real model output) | tens of seconds |

The key design point: **integration and e2e tests skip rather than fail** when
their environment isn't available. That means a plain `pytest` run is always
safe — you'll get green unit tests plus a few "skipped" lines if the servers or
Ollama aren't running.

---

## Running the tests

First, set up a virtualenv with the test dependencies (this installs `pytest`
and `pytest-asyncio`, which the async e2e test needs):

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
```

Run commands from the **repo root**.

**Everything (safe — integration/e2e self-skip if their env is down):**

```bash
pytest
```

**Just the offline unit tests** (fast, deterministic, no servers or model):

```bash
pytest -m "not integration and not e2e"
```

**Integration tests** — start the servers first, then run the marker:

```powershell
.\start-servers.ps1
pytest -m integration
.\stop-servers.ps1
```

**End-to-end test** — needs the model pulled (`ollama pull llama3.2:latest`),
Ollama running, and the servers up:

```powershell
# (Ollama running on the host)
.\start-servers.ps1
pytest -m e2e
.\stop-servers.ps1
```

**A single file or test, with verbose output:**

```bash
pytest tests/test_audit.py
pytest tests/test_audit.py::test_log_and_stats -v
```

> **pandoc note:** the pandoc-dependent cases in `test_converters.py` skip
> automatically if pandoc isn't on your system. The Markdown→text path is
> pure-Python and always runs, so the converter suite is meaningful without it.

---

## Sample files

The sample inputs live in [`../examples/`](../examples). **The unit and
integration tests don't use them** — those tests mock embeddings or pass
in-memory bytes. The samples matter in two places: the e2e test, and running the
orchestrator yourself.

| File | Format | Converter it exercises |
|---|---|---|
| `examples/sample.md` | Markdown | Markdown→text (pure-Python, no pandoc) — this is the file `test_e2e.py` runs |
| `examples/sample.txt` | Plain text | Passthrough (text→text) |
| `examples/report.pdf` | PDF | PDF→text via PyMuPDF |

Together they cover the three "real" ingestion paths the file-bridge handles, so
running the pipeline on each is the quickest way to confirm conversion works end
to end on your machine.

### Running the pipeline on each sample

With the servers and Ollama up, point the orchestrator at any sample (the
`--input` flag; it defaults to `examples/sample.md`):

```powershell
.\start-servers.ps1

.venv\Scripts\python -m agent.orchestrator --input examples\sample.md
.venv\Scripts\python -m agent.orchestrator --input examples\sample.txt
.venv\Scripts\python -m agent.orchestrator --input examples\report.pdf

.\stop-servers.ps1
```

Each run prints a summary, the facts stored in memory, and a cost/quality
report. The orchestrator copies whatever file you pass into the file-bridge's
sandbox automatically, so you can also point `--input` at your own `.md`,
`.txt`, or `.pdf`.

`test_e2e.py` is hard-wired to `examples/sample.md`; to put a different format
through the *automated* e2e path, either change that path in the test or — more
simply — run the orchestrator directly on the sample as shown above.