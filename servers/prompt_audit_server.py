import sys
from typing import Annotated, Literal
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from common.config import settings
from common.responses import ResponseFormat, render
from common.errors import tool_error
import servers.audit_store as store

# Initialize FastMCP instance
mcp = FastMCP("prompt_audit_mcp", stateless_http=True, json_response=True)

@mcp.tool(
    name="audit_log_call",
    annotations={
        "title": "Log call",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def audit_log_call(
    run_id: Annotated[str, Field(min_length=1, description="Pipeline run correlator")],
    step: Annotated[str, Field(min_length=1, description="Logical step name")],
    model: Annotated[str, Field(min_length=1, description="Model identifier")],
    tokens_in: Annotated[int, Field(ge=0, description="Input tokens (real, from Ollama)")],
    tokens_out: Annotated[int, Field(ge=0, description="Output tokens (real, from Ollama)")],
    latency_ms: Annotated[int, Field(ge=0, description="Call latency in milliseconds")],
    quality_score: Annotated[float | None, Field(default=None, ge=0.0, le=1.0, description="Optional quality score")] = None,
    metadata: Annotated[dict | None, Field(default=None, description="Optional caller metadata")] = None
) -> str:
    """Persist one LLM-call record to SQLite; returns the record id."""
    try:
        rec_id = store.log_call(
            run_id=run_id,
            step=step,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            quality_score=quality_score,
            metadata=metadata
        )
        return render({"id": rec_id}, ResponseFormat.JSON, lambda p: f"Logged call #{p['id']}.")
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="audit_get_stats",
    annotations={
        "title": "Get stats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def audit_get_stats(
    run_id: Annotated[str | None, Field(default=None, description="Scope to one run")] = None,
    since: Annotated[str | None, Field(default=None, description="Only calls after this ISO-8601 time")] = None,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="Output format")] = ResponseFormat.MARKDOWN
) -> str:
    """Aggregate calls (optionally scoped to a run or time window) and compute costs."""
    try:
        stats = store.get_stats(run_id=run_id, since=since)
        
        def to_markdown(p):
            lines = ["## LLM Audit Statistics Report"]
            scope = p["scope"]
            scope_desc = []
            if scope["run_id"]:
                scope_desc.append(f"Run ID: `{scope['run_id']}`")
            if scope["since"]:
                scope_desc.append(f"Since: `{scope['since']}`")
            if scope_desc:
                lines.append(f"**Scope:** {', '.join(scope_desc)}")
            else:
                lines.append("**Scope:** All records")
            
            lines.append(f"\n- **Total Calls:** {p['calls']}")
            
            t = p["tokens"]
            lines.append(f"- **Tokens Consumed:** {t['total']} total (In: {t['in']}, Out: {t['out']})")
            lines.append(f"  - *Average per Call:* {t['avg_in']} In, {t['avg_out']} Out")
            
            lat = p["latency_ms"]
            lines.append(f"- **Latency (ms):** Total: {lat['total']}, Avg: {lat['avg']}, P95: {lat['p95']}")
            
            q = p["quality"]
            lines.append(f"- **Response Quality:** Avg Score: {q['avg']:.4f}, Min Score: {q['min']:.4f}")
            
            cost = p["cost"]
            lines.append(f"- **Cost Evaluation:**")
            lines.append(f"  - **Local Compute:** {cost['local']['compute_seconds']} GPU seconds ($0.0)")
            lines.append(f"  - **Notional Cloud Cost:** {cost['notional_cloud']['cost']:.4f} {cost['notional_cloud']['currency']} "
                         f"(at ${cost['notional_cloud']['in_rate_per_1m']}/1M in, ${cost['notional_cloud']['out_rate_per_1m']}/1M out)")
                         
            return "\n".join(lines)
            
        return render(stats, response_format, to_markdown)
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="audit_flag_anomaly",
    annotations={
        "title": "Flag anomalies",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def audit_flag_anomaly(
    metric: Annotated[Literal["latency_ms", "total_tokens"], Field(description="Metric to analyze")],
    k: Annotated[float, Field(default=3.0, ge=1.0, le=6.0, description="z-score threshold")] = 3.0,
    run_id: Annotated[str | None, Field(default=None, description="Optional run ID scope")] = None,
    window: Annotated[int | None, Field(default=None, ge=10, description="Recent records to consider")] = None
) -> str:
    """Return records whose z-score on the chosen metric exceeds k over the relevant history."""
    try:
        anomalies = store.get_anomalies(metric=metric, k=k, run_id=run_id, window=window)
        
        def to_markdown(p):
            if not p["anomalies"]:
                return f"No anomalies found for metric `{p['metric']}` with threshold k={p['k']} (Mean: {p['mean']}, Std: {p['std']})."
            
            lines = [f"### LLM Performance Anomalies Detected (Metric: `{p['metric']}`, k={p['k']})"]
            lines.append(f"Reference Mean: {p['mean']}, Std: {p['std']}\n")
            lines.append("| Call ID | Value | Z-Score | Run ID | Step | Model |")
            lines.append("|---|---|---|---|---|---|")
            for a in p["anomalies"]:
                lines.append(f"| {a['id']} | {a['value']} | {a['z']} | `{a['run_id']}` | `{a['step']}` | `{a['model']}` |")
            return "\n".join(lines)
            
        return render(anomalies, ResponseFormat.JSON, to_markdown)
    except Exception as e:
        return tool_error(str(e))

if __name__ == "__main__":
    store.init_db()
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = settings().audit_port
        mcp.run(transport="streamable_http")
