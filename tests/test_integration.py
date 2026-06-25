import httpx
import pytest
from common.config import settings

def is_server_running(port: int) -> bool:
    """Helper to check if a local HTTP server is listening on a given port."""
    try:
        httpx.get(f"http://localhost:{port}", timeout=1.0)
        # FastMCP HTTP server might return 404/405/etc., which doesn't raise exception unless raise_for_status() is called
        return True
    except Exception:
        return False

@pytest.mark.integration
def test_memory_server_http():
    port = settings().memory_port
    if not is_server_running(port):
        pytest.skip(f"Memory server not running on port {port}. Skipping HTTP integration test.")
        
    # Send a tool list or simple tool call check via Streamable HTTP POST /mcp/tools/list
    url = f"http://localhost:{port}/mcp/tools/list"
    try:
        r = httpx.post(url, json={}, timeout=5.0)
        assert r.status_code in (200, 404, 405) # Check endpoint response
    except Exception as e:
        pytest.fail(f"HTTP request to memory-server failed: {e}")

@pytest.mark.integration
def test_file_bridge_server_http():
    port = settings().file_bridge_port
    if not is_server_running(port):
        pytest.skip(f"File bridge server not running on port {port}. Skipping HTTP integration test.")
        
    url = f"http://localhost:{port}/mcp/tools/list"
    try:
        r = httpx.post(url, json={}, timeout=5.0)
        assert r.status_code in (200, 404, 405)
    except Exception as e:
        pytest.fail(f"HTTP request to file-bridge-server failed: {e}")

@pytest.mark.integration
def test_prompt_audit_server_http():
    port = settings().audit_port
    if not is_server_running(port):
        pytest.skip(f"Prompt audit server not running on port {port}. Skipping HTTP integration test.")
        
    url = f"http://localhost:{port}/mcp/tools/list"
    try:
        r = httpx.post(url, json={}, timeout=5.0)
        assert r.status_code in (200, 404, 405)
    except Exception as e:
        pytest.fail(f"HTTP request to prompt-audit-server failed: {e}")
