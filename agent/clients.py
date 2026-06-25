import os
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from common.config import settings

def make_client() -> MultiServerMCPClient:
    """Creates a MultiServerMCPClient to connect to the memory, filebridge, and audit servers."""
    s = settings()
    memory_url = os.getenv("MEMORY_URL", f"http://localhost:{s.memory_port}/mcp")
    filebridge_url = os.getenv("FILE_BRIDGE_URL", f"http://localhost:{s.file_bridge_port}/mcp")
    audit_url = os.getenv("AUDIT_URL", f"http://localhost:{s.audit_port}/mcp")
    
    return MultiServerMCPClient({
        "memory": {"url": memory_url, "transport": "streamable_http"},
        "filebridge": {"url": filebridge_url, "transport": "streamable_http"},
        "audit": {"url": audit_url, "transport": "streamable_http"}
    })

def make_llm() -> ChatOllama:
    """Creates a ChatOllama instance for LLM interactions."""
    s = settings()
    return ChatOllama(
        model=s.chat_model,
        base_url=s.ollama_url,
        temperature=0.2
    )
