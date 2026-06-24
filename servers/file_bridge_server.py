import os
import sys
import base64
from pathlib import Path
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP
from common.config import settings
from common.responses import ResponseFormat, render
from common.errors import tool_error
import servers.converters as conv

# Initialize FastMCP instance
mcp = FastMCP("file_bridge_mcp", stateless_http=True, json_response=True)

def _safe_path(p: str) -> Path:
    """Resolves and validates paths to prevent directory traversal outside allowed files_dir."""
    s = settings()
    root = Path(s.files_dir).resolve()
    # Create files_dir if it doesn't exist
    root.mkdir(parents=True, exist_ok=True)
    
    full = (root / p).resolve()
    if not str(full).startswith(str(root)):
        raise ValueError("path escapes allowed directory")
    return full

@mcp.tool(
    name="filebridge_convert_file",
    annotations={
        "title": "Convert file",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def filebridge_convert_file(
    to_format: Annotated[str, Field(min_length=1, description="Target format (e.g. text, markdown, html)")],
    source_path: Annotated[str | None, Field(default=None, description="Path under allowed directory")] = None,
    source_b64: Annotated[str | None, Field(default=None, description="Base64 encoded source data")] = None,
    from_format: Annotated[str | None, Field(default=None, description="Source format; inferred if omitted")] = None,
    response_format: Annotated[ResponseFormat, Field(default=ResponseFormat.MARKDOWN, description="Output format")] = ResponseFormat.MARKDOWN
) -> str:
    """Convert input bytes/file from one format to another and return result."""
    try:
        # Validate mutual exclusivity of source inputs
        if (source_path is None) == (source_b64 is None):
            return tool_error("Exactly one of source_path or source_b64 must be provided.")

        data = b""
        inferred_from = from_format

        if source_path is not None:
            try:
                safe_fp = _safe_path(source_path)
            except ValueError as ve:
                return tool_error(str(ve))
                
            if not safe_fp.is_file():
                return tool_error(f"File not found: {source_path}")
                
            data = safe_fp.read_bytes()
            if not inferred_from:
                inferred_from = safe_fp.suffix.lstrip(".").lower()
        else:
            # Decode source_b64
            try:
                data = base64.b64decode(source_b64)
            except Exception:
                return tool_error("Invalid base64 encoding for source_b64.")
            if not inferred_from:
                return tool_error("from_format is required when source_b64 is provided.")

        # Normalize format name (e.g. md -> markdown, txt -> text)
        if inferred_from == "md":
            inferred_from = "markdown"
        if inferred_from == "txt":
            inferred_from = "text"
            
        target_fmt = to_format
        if target_fmt == "md":
            target_fmt = "markdown"
        if target_fmt == "txt":
            target_fmt = "text"

        # Search registry for compatible converter
        converter = conv.find(inferred_from, target_fmt)
        if not converter:
            return tool_error(
                f"Unsupported conversion {inferred_from} -> {target_fmt}.",
                supported=conv.all_pairs(),
                suggestion="Call filebridge_list_formats to see all supported pairs."
            )

        # Convert
        out_bytes = converter.convert(data, inferred_from, target_fmt)

        # Detect if it's text or binary
        is_text_target = target_fmt in ("text", "markdown", "html")
        
        payload = {
            "from": inferred_from,
            "to": target_fmt,
            "bytes_out": len(out_bytes),
            "text": None,
            "output_path": None
        }

        if is_text_target:
            payload["text"] = out_bytes.decode("utf-8", errors="ignore")
        else:
            # For binary files, write to output directory and return path
            s = settings()
            out_filename = f"converted_{inferred_from}_to_{target_fmt}_{hash(out_bytes) & 0xffffffff}"
            # map suffix
            suffix = f".{target_fmt}" if target_fmt != "text" else ".txt"
            if target_fmt == "markdown":
                suffix = ".md"
            out_filename += suffix
            
            out_path = Path(s.files_dir) / out_filename
            out_path.write_bytes(out_bytes)
            payload["output_path"] = out_filename

        def to_markdown(p):
            if p["text"] is not None:
                return p["text"]
            return f"Binary output written to `{p['output_path']}` ({p['bytes_out']} bytes)."

        return render(payload, response_format, to_markdown)
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="filebridge_list_formats",
    annotations={
        "title": "List formats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def filebridge_list_formats() -> str:
    """List supported conversion pairs and active converter names."""
    try:
        converter_names = sorted(list({c.name for c in conv.REGISTRY}))
        pairs = conv.all_pairs()
        payload = {
            "converters": converter_names,
            "pairs": pairs
        }
        return render(payload, ResponseFormat.JSON, lambda p: f"Supported converters: {p['converters']}\nPairs: {p['pairs']}")
    except Exception as e:
        return tool_error(str(e))

@mcp.tool(
    name="filebridge_preview_output",
    annotations={
        "title": "Preview output",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def filebridge_preview_output(
    to_format: Annotated[str, Field(min_length=1, description="Target format")],
    source_path: Annotated[str | None, Field(default=None, description="Path under allowed directory")] = None,
    source_b64: Annotated[str | None, Field(default=None, description="Base64 encoded source data")] = None,
    from_format: Annotated[str | None, Field(default=None, description="Source format; inferred if omitted")] = None,
    max_chars: Annotated[int, Field(default=1000, ge=1, le=20000, description="Preview length")] = 1000
) -> str:
    """Convert and return only the first max_chars of the result, for cheap inspection."""
    try:
        # We reuse the convert logic and then slice
        # Let's perform convert (always using JSON response for extraction)
        res_json_str = await filebridge_convert_file(
            to_format=to_format,
            source_path=source_path,
            source_b64=source_b64,
            from_format=from_format,
            response_format=ResponseFormat.JSON
        )
        import json
        res_data = json.loads(res_json_str)
        if "isError" in res_data and res_data["isError"]:
            return res_json_str

        # If it returned an output path instead of inline text
        if res_data["text"] is None:
            payload = {
                "from": res_data["from"],
                "to": res_data["to"],
                "preview": f"[Binary target output path: {res_data['output_path']}]",
                "truncated": False
            }
        else:
            text = res_data["text"]
            truncated = len(text) > max_chars
            preview = text[:max_chars]
            payload = {
                "from": res_data["from"],
                "to": res_data["to"],
                "preview": preview,
                "truncated": truncated
            }

        return render(payload, ResponseFormat.JSON, lambda p: f"Preview ({p['from']} -> {p['to']}):\n{p['preview']}\nTruncated: {p['truncated']}")
    except Exception as e:
        return tool_error(str(e))

if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run()
    else:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = settings().file_bridge_port
        mcp.run(transport="streamable_http")
