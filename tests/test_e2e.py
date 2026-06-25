import os
import httpx
import pytest
from common.config import settings
from agent.orchestrator import run_pipeline

def is_env_ready() -> bool:
    """Checks if the external environment (Ollama and HTTP servers) is ready for E2E testing."""
    s = settings()
    try:
        # Check Ollama
        r = httpx.get(f"{s.ollama_url}/api/tags", timeout=1.0)
        if r.status_code != 200:
            return False
            
        # Check MCP servers
        for port in [s.memory_port, s.file_bridge_port, s.audit_port]:
            httpx.get(f"http://localhost:{port}", timeout=1.0)
            
        return True
    except Exception:
        return False

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pipeline_e2e():
    """Runs the full orchestrator graph end-to-end if the local environment is running."""
    if not is_env_ready():
        pytest.skip(
            "Local environment (Ollama and MCP HTTP servers) is not fully active. "
            "Skipping end-to-end integration test."
        )
        
    sample_file = "examples/sample.md"
    assert os.path.exists(sample_file), f"Sample file {sample_file} must exist for E2E test."
    
    # Run the orchestrator pipeline
    try:
        await run_pipeline(sample_file, react=False)
    except Exception as e:
        pytest.fail(f"Pipeline end-to-end execution failed: {e}")
