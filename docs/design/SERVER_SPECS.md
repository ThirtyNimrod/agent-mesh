# Server Specifications

The tool contract for each MCP server: name, purpose, input schema (Pydantic fields), output, annotations, errors, and examples. Conventions follow MCP best practices — service-prefixed snake_case tool names, declared annotations, `markdown`/`json` response formats, pagination on list tools, and errors returned **inside** results.

Shared conventions:
- **Server names** (Python): `memory_mcp`, `file_bridge_mcp`, `prompt_audit_mcp`.
- **Endpoints** (Streamable HTTP): `/mcp` on ports `8001` / `8002` / `8003`.
- **`response_format`**: `markdown` (default, human-readable) or `json` (machine-readable) on data-returning tools.
- **Errors**: returned as result text with an error flag and a suggested next step; never raised as protocol errors.
- **Annotations legend**: RO = `readOnlyHint`, D = `destructiveHint`, I = `idempotentHint`, OW = `openWorldHint`.

---

## 1. `memory-server` (`memory_mcp`, :8001)

Persistent vector memory backed by FAISS (vectors) + SQLite (text/metadata). SQLite is the source of truth.

### Data model (SQLite `memories`)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Also the FAISS vector id (via `IndexIDMap`) |
| `text` | TEXT | The stored content |
| `metadata` | TEXT (JSON) | Arbitrary caller metadata |
| `tags` | TEXT (JSON array) | Optional tags |
| `created_at` | TEXT (ISO-8601) | UTC timestamp |

### Tool: `memory_add`

Embed `text` and store it; add its vector to the index.

**Annotations:** RO=false, D=false, I=false, OW=false

**Input (`MemoryAddInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `text` | str | min_len 1, max_len 20000 | Content to remember |
| `metadata` | dict | None | default `{}` | Arbitrary JSON metadata |
| `tags` | list[str] | None | max_items 20 | Optional tags |

**Output:** `{ "id": int, "created_at": str }` (json) / confirmation line (markdown).

**Errors:** embedding backend unreachable → `"Error: embedding model 'nomic-embed-text' unreachable at <url>. Check OLLAMA_HOST."`

**Example**

```json
// memory_add
{ "text": "agent-mesh exposes 3 MCP servers over Streamable HTTP.", "tags": ["architecture"] }
// → { "id": 17, "created_at": "2026-06-24T10:30:00Z" }
```

### Tool: `memory_search`

Return the most similar memories to a query.

**Annotations:** RO=true, D=false, I=true, OW=false

**Input (`MemorySearchInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `query` | str | min_len 1, max_len 4000 | Search text |
| `limit` | int | default 5, ge 1, le 50 | Max results |
| `min_score` | float | default 0.0, ge 0, le 1 | Drop results below this cosine score |
| `response_format` | enum | `markdown`|`json` | Output format |

**Output (json):**

```json
{
  "query": "...",
  "count": 2,
  "results": [
    { "id": 17, "score": 0.83, "text": "...", "metadata": {}, "tags": ["architecture"] }
  ]
}
```

**Errors:** empty index → returns `count: 0` with a note, not an error.

### Tool: `memory_list`

Paginated listing (no embedding needed).

**Annotations:** RO=true, D=false, I=true, OW=false

**Input (`MemoryListInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `limit` | int | default 20, ge 1, le 100 | Page size |
| `offset` | int | default 0, ge 0 | Skip count |
| `response_format` | enum | `markdown`|`json` | Output format |

**Output (json):** `{ "total": int, "count": int, "offset": int, "items": [...], "has_more": bool, "next_offset": int|null }`

### Tool: `memory_delete`

Remove a memory by id from SQLite and FAISS. Idempotent.

**Annotations:** RO=false, **D=true**, I=true, OW=false

**Input (`MemoryDeleteInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `memory_id` | int | ge 1 | Id to delete |

**Output:** `{ "id": int, "deleted": bool }` — deleting a missing id returns `deleted: false` with a note (still a success).

---

## 2. `file-bridge-server` (`file_bridge_mcp`, :8002)

Wraps a pluggable `Converter` behind MCP tools. Reference converters: pandoc (`pypandoc`) for doc/markdown/html/rst, PyMuPDF for PDF→text, passthrough for txt.

> Conversions are advertised dynamically from registered converters, so `filebridge_list_formats` is always accurate.

### Tool: `filebridge_convert_file`

Convert input bytes/file from one format to another.

**Annotations:** RO=true (does not modify source), D=false, I=true, OW=false

**Input (`ConvertFileInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `source_path` | str | None | — | Path under the allow-listed input dir (mutually exclusive with `source_b64`) |
| `source_b64` | str | None | — | Base64 of the source bytes |
| `from_format` | str | None | — | Source format; inferred from extension if omitted |
| `to_format` | str | min_len 1 | Target format (e.g. `text`, `markdown`, `html`) |
| `response_format` | enum | `markdown`|`json` | Output wrapper format |

**Validation:** exactly one of `source_path`/`source_b64`; `source_path` is sanitized and must resolve inside the allowed directory.

**Output (json):**

```json
{ "from": "pdf", "to": "text", "bytes_out": 5120,
  "text": "…converted text (if textual)…",
  "output_path": null }
```

Binary targets return `output_path` instead of inline `text`.

**Errors (structured, actionable):**

```json
{ "isError": true,
  "error": "Unsupported conversion pdf → docx.",
  "supported": [["pdf","text"],["markdown","html"], "..."],
  "suggestion": "Call filebridge_list_formats to see all supported pairs." }
```

### Tool: `filebridge_list_formats`

List supported conversion pairs.

**Annotations:** RO=true, D=false, I=true, OW=false

**Input:** none.

**Output (json):** `{ "converters": ["pandoc","pymupdf","passthrough"], "pairs": [["markdown","html"],["pdf","text"], "..."] }`

### Tool: `filebridge_preview_output`

Convert and return only the first `max_chars` — cheap inspection before a full convert/store.

**Annotations:** RO=true, D=false, I=true, OW=false

**Input (`PreviewInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `source_path` / `source_b64` | as above | one required | Source |
| `to_format` | str | min_len 1 | Target format |
| `max_chars` | int | default 1000, ge 1, le 20000 | Preview length |

**Output:** `{ "from": str, "to": str, "preview": str, "truncated": bool }`

### The `Converter` seam

```python
from typing import Protocol

class Converter(Protocol):
    name: str
    def supported(self) -> list[tuple[str, str]]: ...
    def convert(self, data: bytes, from_fmt: str, to_fmt: str) -> bytes: ...
```

Register a private engine (e.g. *adla-badli*) by adding a module to `servers/converters/` and including it in the registry. The tool surface above is unchanged; only `supported()`/`convert()` behavior differs.

---

## 3. `prompt-audit-server` (`prompt_audit_mcp`, :8003)

Logs every LLM call and computes stats, cost, and anomalies. SQLite-backed.

### Data model (SQLite `calls`)

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Record id |
| `run_id` | TEXT | Correlates calls from one pipeline run |
| `step` | TEXT | e.g. `extract`, `summarize`, `judge` |
| `model` | TEXT | e.g. `qwen3.5:4b` |
| `tokens_in` | INTEGER | From `prompt_eval_count` |
| `tokens_out` | INTEGER | From `eval_count` |
| `latency_ms` | INTEGER | Wall-clock around the call |
| `quality_score` | REAL | NULL | `[0,1]`, see ARCHITECTURE §6 |
| `metadata` | TEXT (JSON) | Optional |
| `created_at` | TEXT | ISO-8601 UTC |

### Tool: `audit_log_call`

Persist one call record.

**Annotations:** RO=false, D=false, I=false, OW=false

**Input (`LogCallInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `run_id` | str | min_len 1 | Pipeline run correlator |
| `step` | str | min_len 1 | Logical step name |
| `model` | str | min_len 1 | Model identifier |
| `tokens_in` | int | ge 0 | Input tokens (real, from Ollama) |
| `tokens_out` | int | ge 0 | Output tokens (real, from Ollama) |
| `latency_ms` | int | ge 0 | Call latency |
| `quality_score` | float | None | ge 0, le 1 | Optional quality score |
| `metadata` | dict | None | — | Optional |

**Output:** `{ "id": int }`

### Tool: `audit_get_stats`

Aggregate calls into a report, optionally scoped.

**Annotations:** RO=true, D=false, I=true, OW=false

**Input (`GetStatsInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `run_id` | str | None | — | Scope to one run |
| `since` | str | None | ISO-8601 | Only calls after this time |
| `response_format` | enum | `markdown`|`json` | Output format |

**Output (json):**

```json
{
  "scope": { "run_id": "run-abc", "since": null },
  "calls": 2,
  "tokens": { "in": 1240, "out": 320, "total": 1560,
              "avg_in": 620, "avg_out": 160 },
  "latency_ms": { "total": 3800, "avg": 1900, "p95": 2400 },
  "quality": { "avg": 0.91, "min": 0.88 },
  "cost": {
    "local": { "compute_seconds": 3.8, "currency_cost": 0.0 },
    "notional_cloud": { "in_rate_per_1m": 10.0, "out_rate_per_1m": 30.0,
                        "currency": "USD", "cost": 0.0220 }
  }
}
```

Rates come from the configured price table (`.env`), never hard-coded.

### Tool: `audit_flag_anomaly`

Flag statistical outliers on a metric.

**Annotations:** RO=true, D=false, I=true, OW=false

**Input (`FlagAnomalyInput`)**

| Field | Type | Constraints | Description |
|---|---|---|---|
| `metric` | enum | `latency_ms`|`total_tokens` | Metric to analyze |
| `k` | float | default 3.0, ge 1, le 6 | z-score threshold |
| `run_id` | str | None | — | Optional scope |
| `window` | int | None | ge 10 | Recent records to consider (default: all) |

**Output (json):**

```json
{ "metric": "latency_ms", "mean": 1900, "std": 120, "k": 3.0,
  "anomalies": [ { "id": 42, "value": 5400, "z": 29.2, "run_id": "run-xyz", "step": "summarize" } ] }
```

---

## Tool index (quick reference)

| Server | Tool | RO | D | I | OW |
|---|---|:--:|:--:|:--:|:--:|
| memory | `memory_add` | ✗ | ✗ | ✗ | ✗ |
| memory | `memory_search` | ✓ | ✗ | ✓ | ✗ |
| memory | `memory_list` | ✓ | ✗ | ✓ | ✗ |
| memory | `memory_delete` | ✗ | ✓ | ✓ | ✗ |
| file-bridge | `filebridge_convert_file` | ✓ | ✗ | ✓ | ✗ |
| file-bridge | `filebridge_list_formats` | ✓ | ✗ | ✓ | ✗ |
| file-bridge | `filebridge_preview_output` | ✓ | ✗ | ✓ | ✗ |
| audit | `audit_log_call` | ✗ | ✗ | ✗ | ✗ |
| audit | `audit_get_stats` | ✓ | ✗ | ✓ | ✗ |
| audit | `audit_flag_anomaly` | ✓ | ✗ | ✓ | ✗ |

> `openWorldHint` is false for all tools: each interacts only with local state or the local Ollama runtime, not the open internet.
