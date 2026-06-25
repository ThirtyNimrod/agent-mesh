# Setup & Run Guide

This is the hands-on runbook for getting `agent-mesh` running. It targets the reference environment (a Windows laptop with an NVIDIA GPU) but calls out the Linux/macOS differences where they matter. For *why* the pieces fit together this way, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## 1. Reference environment

The defaults in this repo are tuned for this machine, but nothing here is exotic — any box with a recent GPU (or even CPU-only, more slowly) will work.

| Component | Reference value | Notes |
|---|---|---|
| OS | Windows 10/11 | WSL2 enabled (Docker Desktop backend) |
| CPU | Intel i7-9750H (6c/12t) | Fine for the servers + embeddings |
| RAM | 16 GB | Comfortable; ~6–8 GB used under load |
| GPU | RTX 2070 Max-Q, **8 GB VRAM** | Holds `llama3.2:latest` (~3.4 GB) + embeddings with headroom |
| Model store | `D:\.ollama\models` | Custom path via `OLLAMA_MODELS` |

> **VRAM budget.** `llama3.2:latest` at Q4_K_M needs roughly 3.4 GB plus a bit for context; `nomic-embed-text` is ~275 MB. You stay well under 8 GB, leaving room for the desktop. Thinking mode is off by default on the small Qwen3.5 models, which keeps latency down.

---

## 2. Prerequisites

1. **Ollama** — install the native host app from <https://ollama.com>. Do **not** run Ollama inside Docker; it runs on the host so it can use the GPU directly.
2. **Docker Desktop** — with the **WSL2 backend** enabled on Windows. The 3 servers and the orchestrator run as containers.
3. **Git** — to clone the repo.
4. *(Optional)* **Python 3.11+** on the host — only needed for [dev mode](#dev-mode-stdio) (running a server directly without Docker) and for the MCP Inspector.

---

## 3. Configure Ollama (host)

Two environment variables matter. Set them at the OS level so they persist and so Ollama picks them up on restart.

**a) Custom model directory** — point Ollama at `D:\.ollama\models`:

```powershell
setx OLLAMA_MODELS "D:\.ollama\models"
```

**b) Listen on all interfaces** — by default Ollama binds to `127.0.0.1`, which containers can't reach. Bind it to `0.0.0.0` so the compose network can connect via `host.docker.internal`:

```powershell
setx OLLAMA_HOST "0.0.0.0:11434"
```

> `setx` writes the variable permanently but does **not** affect already-open shells. **Fully quit and restart Ollama** (and any terminal) afterward so the new values take effect. On macOS/Linux, set the same variables in your shell profile (`export OLLAMA_HOST=0.0.0.0:11434`) and restart the Ollama service.

Verify Ollama is up and reachable on the LAN interface:

```powershell
ollama list                       # should run without error
curl http://localhost:11434/api/tags    # should return JSON
```

---

## 4. Pull the models (one time)

```bash
ollama pull llama3.2:latest          # ~3.4 GB — the reasoning model
ollama pull nomic-embed-text    # ~275 MB — embeddings for memory-server
```

Confirm both appear in `ollama list`. They'll be stored under your `OLLAMA_MODELS` path.

---

## 5. Configure the repo

```bash
git clone <your-fork-url> agent-mesh
cd agent-mesh
cp .env.example .env
```

Open `.env` and skim it. The defaults match this guide; the most likely things you'd touch are the price table (`PRICE_IN_PER_1M` / `PRICE_OUT_PER_1M`) and the service ports if `8001–8003` collide with something already running.

---

## 6. Launch

```bash
docker compose up --build
```

What happens:

1. Three server images build and start (`memory-server`, `file-bridge-server`, `prompt-audit-server`), each waiting until its healthcheck passes.
2. Once all three are healthy, the `orchestrator` starts and runs the demo pipeline against `examples/sample.md`.
3. You get a summary plus a cost/quality report in the logs.

To run the pipeline again, or against your own file:

```bash
docker compose run --rm orchestrator python -m agent.orchestrator --input examples/sample.md
# or point --input at any file you mount into the orchestrator
```

Shut everything down with `Ctrl-C`, then `docker compose down` (add `-v` to also wipe the memory/audit volumes for a clean slate).

---

## Dev mode (no Docker)

You don't need Docker to run the full mesh locally. Two options:

### Option A — start/stop scripts (recommended)

The repo ships PowerShell scripts that start all three servers as background processes, save their PIDs, and write logs to `logs/`.

```powershell
# Start all three servers (hidden background processes)
.\start-servers.ps1

# Or with minimized windows so you can see their output
.\start-servers.ps1 -Visible

# Stop all three
.\stop-servers.ps1
```

`.bat` wrappers (`start-servers.bat`, `stop-servers.bat`) are provided for double-click convenience — they call the PS1 scripts with `-ExecutionPolicy Bypass` so no policy change is needed.

Each server writes its own timestamped log file to `logs/` (e.g. `logs/2026-06-25_14-30-00_memory_server.log`). The `logs/` directory is gitignored.

**Prerequisites for this path:** Python `.venv` set up, and in `.env` set `OLLAMA_URL=http://localhost:11434` (the default `host.docker.internal` address is only reachable from inside Docker).

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Then run the orchestrator:

```bash
python -m agent.orchestrator --input examples/sample.md
```

### Option B — single server over stdio (MCP Inspector / Claude Desktop)

Each server also speaks **stdio**, which desktop MCP clients expect.

```bash
# For bare-metal runs, set OLLAMA_URL=http://localhost:11434 in .env first
python -m servers.memory_server --stdio
```

Then attach the **MCP Inspector**:

```bash
npx @modelcontextprotocol/inspector python -m servers.memory_server --stdio
```

The Inspector lets you list each tool, see its input schema, and invoke it — the fastest way to sanity-check a tool contract while you're building. See [`TESTING_AND_EVALUATION.md`](TESTING_AND_EVALUATION.md) for how the automated evals exercise these same tools.

> To inspect a server while it's running **in Docker** over HTTP instead, uncomment that service's `ports:` block in `docker-compose.yml`, bring it up, and point the Inspector at `http://localhost:<port>/mcp`.

---

## Troubleshooting

**Containers can't reach Ollama / connection refused on `host.docker.internal`.** The usual cause is `OLLAMA_HOST` still bound to `127.0.0.1`. Confirm you set it to `0.0.0.0:11434` *and* restarted Ollama. Test from inside a running container: `docker compose exec orchestrator python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags').status)"`. On Linux, the `extra_hosts: ["host.docker.internal:host-gateway"]` entries (already in the compose file) are what make that hostname resolve.

**`host.docker.internal` doesn't resolve at all (older Linux Docker).** Make sure you're using the provided `docker-compose.yml` unmodified — it includes the `extra_hosts` mapping. As a fallback you can use the host's LAN IP in `OLLAMA_URL`.

**Out of VRAM / model won't load.** Close other GPU-heavy apps. `llama3.2:latest` should fit 8 GB comfortably; if you swapped in a larger model, drop back down. You can watch usage with `nvidia-smi`.

**Port already in use (`8001`/`8002`/`8003`).** Change the relevant `*_PORT` in `.env`. Note these are in-network ports; they're only exposed to your host if you uncomment a `ports:` block.

**`faiss-cpu` / NumPy import or ABI error in `memory-server`.** This pair is version-sensitive. Use a known-good combination (a recent `faiss-cpu` with `numpy>=1.26`) and, once it works, freeze it: `pip freeze > requirements.lock`.

**`pypandoc` can't find pandoc.** Markdown (`.md`) and plain text (`.txt`) files are converted by a built-in pure-Python converter that does **not** need pandoc. Pandoc is only required for `.docx`, `.html`, and `.rst` inputs. If you need those formats, install pandoc separately (`winget install JohnMacFarlane.Pandoc` on Windows, or `pypandoc.download_pandoc()` from Python) and it will be picked up automatically.

**The orchestrator starts before the servers are ready.** It shouldn't — the `depends_on … condition: service_healthy` gates it on the healthchecks. If you edited the compose file, make sure those conditions are intact.

---

## Next steps

- Skim [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the build order and code skeletons.
- See [`SERVER_SPECS.md`](SERVER_SPECS.md) for the exact tool contracts.
- Track progress against [`MILESTONES.md`](MILESTONES.md).
