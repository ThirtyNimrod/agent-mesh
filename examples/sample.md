# agent-mesh Project Summary

The `agent-mesh` system is a containerized microservice network built to demonstrate the Model Context Protocol (MCP) in action. It connects three independent MCP servers with a central LangGraph agent that processes document pipelines.

## System Topology
The system consists of the following components running locally on a private Docker Compose network:
1. **Memory Server**: Uses a FAISS vector database alongside a SQLite relational store to remember important concepts.
2. **File Bridge Server**: Acts as an interface to convert documents from PDF, HTML, docx, or markdown into clean plain text.
3. **Prompt Audit Server**: Persists trace logs of every LLM call, analyzing token usage, calculating latencies, and flag-marking abnormal execution spikes (using standard Z-scores).

## Core Decisions
- **Local Ollama Model**: To respect memory limits (8 GB GPU), the primary reasoning model is `qwen3.5:4b`, and the embedding model is `nomic-embed-text`. Both run natively on the host rather than in containers to leverage hardware acceleration easily.
- **Deterministic Routing**: The LangGraph pipeline follows a predefined node sequence (`ingest` -> `convert` -> `extract` -> `store` -> `summarize` -> `report`) to ensure high reliability from the smaller 4B model.
