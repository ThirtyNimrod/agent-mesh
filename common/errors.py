import json
from typing import Any

def tool_error(message: str, **extra: Any) -> str:
    """
    Returns a JSON string representing a structured, non-raising tool error.
    """
    return json.dumps({"isError": True, "error": message, **extra}, indent=2)
