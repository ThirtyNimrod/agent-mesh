import json
from typing import Any, List

def score(
    messages: List[Any],
    resp: Any,
    step: str,
    expect: str = "text",
    latency_ms: int = 0
) -> float:
    """
    Computes a deterministic quality score [0.0, 1.0] for an LLM response.
    Based on four signals: non_empty (30%), length_in_band (25%), format_valid (30%), latency_ok (15%).
    """
    content = getattr(resp, "content", "") or ""
    content_stripped = content.strip()
    
    # 1. non_empty signal (Weight: 0.30)
    non_empty_score = 0.0
    if content_stripped:
        refusals = ["i apologize", "as an ai", "i cannot", "sorry, but", "error:"]
        lower_content = content_stripped.lower()
        if not any(ref in lower_content for ref in refusals):
            non_empty_score = 1.0
            
    # 2. length_in_band signal (Weight: 0.25)
    length_score = 0.0
    char_len = len(content_stripped)
    if step == "extract":
        # Extract step key points length expectation
        if 50 <= char_len <= 8000:
            length_score = 1.0
    elif step == "summarize":
        # Summarize step output expectations
        if 100 <= char_len <= 4000:
            length_score = 1.0
    else:
        # Default fallback
        if char_len > 0:
            length_score = 1.0

    # 3. format_valid signal (Weight: 0.30)
    format_score = 0.0
    if expect == "json":
        try:
            # Strip markdown json block wrappers if the model generated them
            cleaned = content_stripped
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            json.loads(cleaned)
            format_score = 1.0
        except Exception:
            format_score = 0.0
    else:
        # Plain text
        format_score = 1.0

    # 4. latency_ok signal (Weight: 0.15)
    # Target < 250ms per generated token, or absolute latency < 15 seconds
    latency_score = 1.0
    um = getattr(resp, "usage_metadata", None) or {}
    tokens_out = um.get("output_tokens", 0)
    
    if tokens_out > 0 and latency_ms > 0:
        ms_per_token = latency_ms / tokens_out
        if ms_per_token > 350.0:  # slow generation
            # Decay score down to 0
            latency_score = max(0.0, 1.0 - (ms_per_token - 350.0) / 350.0)
    elif latency_ms > 15000:  # took more than 15s without usage metadata
        latency_score = 0.0

    # Calculate weighted average
    total_score = (
        (non_empty_score * 0.30) +
        (length_score * 0.25) +
        (format_score * 0.30) +
        (latency_score * 0.15)
    )
    return round(total_score, 4)
