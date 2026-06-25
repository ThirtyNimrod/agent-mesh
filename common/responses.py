import json
from enum import Enum
from typing import Any, Callable, Dict, List

class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"

def paginate(items: List[Any], total: int, offset: int) -> Dict[str, Any]:
    count = len(items)
    has_more = total > offset + count
    return {
        "total": total,
        "count": count,
        "offset": offset,
        "items": items,
        "has_more": has_more,
        "next_offset": (offset + count) if has_more else None
    }

def render(payload: Any, fmt: ResponseFormat, to_markdown: Callable[[Any], str]) -> str:
    """
    Renders payload as a JSON string or using the provided markdown generator.
    """
    if fmt == ResponseFormat.JSON:
        return json.dumps(payload, indent=2, default=str)
    return to_markdown(payload)
