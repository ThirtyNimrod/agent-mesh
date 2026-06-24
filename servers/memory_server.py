import sys
import httpx
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from common.config import settings
from common.responses import ResponseFormat, render
from common.errors import tool_error
import servers.memory_store as store

# Create FastMCP server instance
mcp = FastMCP("memory_mcp", stateless_http=True, json_response=True)

@mcp.tool(
    name="memory_add",
    annotations={
        "title": "Add memory",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def memory_add(
    text: Annotated[str, Field(min_length=1, max_length=20000, description="Content to remember")],
    metadata: Annotated[dict | None, Field(default=None, description="Arbitrary JSON metadata")] = None,
    tags: Annotated[list[str] | None, Field(default=None, max_items=20, description="Optional tags")] = None
) -> str:
    """Embed and persist a memory; returns its id and creation time."""
    try:
        rec = store.add(text, metadata or {}, tags or [])
        return render(
            rec,
            ResponseFormat.JSON,
            lambda p: f"Stored memory #{p['id']}."
        )
    except httpx.HTTPError:
        return tool_error(f"Embedding model '{settings().embed_model}' unreachable; check OLLAMA_URL.")
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="memory_search",
    annotations={
        "title": "Search memories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def memory_search(
    query: Annotated[str, Field(min_length=1, max_length=4000, description="Search text")],
    limit: Annotated[int, Field(default=5, ge=1, le=50, description="Max results")] = 5,
    min_score: Annotated[float, Field(default=0.0, ge=0.0, le=1.0, description="Drop results below this cosine score")] = 0.0,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="Output format")] = ResponseFormat.MARKDOWN
) -> str:
    """Return the most similar memories to a query, ranked by cosine similarity."""
    try:
        results = store.search(query, limit=limit, min_score=min_score)
        payload = {
            "query": query,
            "count": len(results),
            "results": results
        }
        
        def to_markdown(p):
            if not p["results"]:
                return f"No memories found matching query: \"{p['query']}\" with min_score {min_score}."
            lines = [f"### Search Results for \"{p['query']}\" (Found: {p['count']}):"]
            for idx, item in enumerate(p["results"], start=1):
                tags_str = ", ".join(f"`{t}`" for t in item["tags"]) if item["tags"] else "None"
                lines.append(f"{idx}. **Memory #{item['id']}** (Score: {item['score']:.4f})")
                lines.append(f"   - **Tags:** {tags_str}")
                lines.append(f"   - **Text:** {item['text']}")
            return "\n".join(lines)
            
        return render(payload, response_format, to_markdown)
    except httpx.HTTPError:
        return tool_error(f"Embedding model '{settings().embed_model}' unreachable; check OLLAMA_URL.")
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="memory_list",
    annotations={
        "title": "List memories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def memory_list(
    limit: Annotated[int, Field(default=20, ge=1, le=100, description="Page size")] = 20,
    offset: Annotated[int, Field(default=0, ge=0, description="Skip count")] = 0,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="Output format")] = ResponseFormat.MARKDOWN
) -> str:
    """Paginated listing of stored memories."""
    try:
        payload = store.list_memories(limit=limit, offset=offset)
        
        def to_markdown(p):
            if not p["items"]:
                return f"No memories found (Total: {p['total']})."
            lines = [f"### Stored Memories (Total: {p['total']}, Showing: {p['count']}, Offset: {p['offset']}):"]
            for item in p["items"]:
                tags_str = ", ".join(f"`{t}`" for t in item["tags"]) if item["tags"] else "None"
                lines.append(f"- **Memory #{item['id']}** (Created: {item['created_at']})")
                lines.append(f"  - **Tags:** {tags_str}")
                lines.append(f"  - **Text:** {item['text']}")
            return "\n".join(lines)
            
        return render(payload, response_format, to_markdown)
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="memory_delete",
    annotations={
        "title": "Delete memory",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def memory_delete(
    memory_id: Annotated[int, Field(ge=1, description="Id to delete")]
) -> str:
    """Remove a memory from SQLite and the FAISS index by id; idempotent."""
    try:
        deleted = store.delete_memory(memory_id)
        payload = {"id": memory_id, "deleted": deleted}
        
        def to_markdown(p):
            if p["deleted"]:
                return f"Successfully deleted memory #{p['id']}."
            else:
                return f"Memory #{p['id']} not found (no-op)."
                
        return render(payload, ResponseFormat.JSON, to_markdown)
    except Exception as e:
        return tool_error(str(e))

if __name__ == "__main__":
    store.init_db()
    store.init_index()
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = settings().memory_port
        mcp.run(transport="streamable_http")
