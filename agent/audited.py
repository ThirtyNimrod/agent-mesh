import time
import logging
from typing import Any, Dict, List
from agent.quality import score

logger = logging.getLogger(__name__)

async def audited_invoke(
    llm: Any,
    tools_by_name: Dict[str, Any],
    run_id: str,
    step: str,
    messages: List[Any],
    expect: str = "text"
) -> Any:
    """
    Wraps ChatOllama invocations to track response latency, compute quality metrics,
    and log call statistics to the prompt audit server.
    """
    t0 = time.perf_counter()
    try:
        resp = await llm.ainvoke(messages)
    except Exception as e:
        logger.error(f"LLM invocation failed at step {step}: {e}")
        raise e
        
    latency_ms = int((time.perf_counter() - t0) * 1000)
    
    # Extract usage metadata
    um = getattr(resp, "usage_metadata", None) or {}
    tin = um.get("input_tokens", 0)
    tout = um.get("output_tokens", 0)
    
    # If usage_metadata is missing, try response_metadata
    if tin == 0 or tout == 0:
        rm = getattr(resp, "response_metadata", None) or {}
        # Ollama sometimes provides prompt_eval_count / eval_count
        message_meta = rm.get("message", {})
        tin = rm.get("prompt_eval_count", message_meta.get("prompt_eval_count", 0))
        tout = rm.get("eval_count", message_meta.get("eval_count", 0))

    # Calculate quality score
    q = score(messages, resp, step, expect, latency_ms)
    
    # Log to audit server
    model_name = getattr(llm, "model", getattr(llm, "model_name", "unknown"))
    
    audit_args = {
        "run_id": run_id,
        "step": step,
        "model": model_name,
        "tokens_in": tin,
        "tokens_out": tout,
        "latency_ms": latency_ms,
        "quality_score": q
    }
    
    try:
        if "audit_log_call" in tools_by_name:
            await tools_by_name["audit_log_call"].ainvoke(audit_args)
        else:
            logger.warning("audit_log_call tool not found in toolset; skipping audit log.")
    except Exception as ae:
        # Graceful degradation for audit server failures
        logger.error(f"Failed to log call stats to audit-server: {ae}")
        print(f"Warning: Failed to log call stats to audit-server: {ae}")
        
    return resp
