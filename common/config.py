import os
from functools import lru_cache
from pydantic import BaseModel, Field

# Load dotenv for local bare-metal executions
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class Settings(BaseModel):
    ollama_url: str = Field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"))
    chat_model: str = Field(default_factory=lambda: os.getenv("CHAT_MODEL", "llama3.2:latest"))
    embed_model: str = Field(default_factory=lambda: os.getenv("EMBED_MODEL", "nomic-embed-text"))
    embed_dim: int = Field(default_factory=lambda: int(os.getenv("EMBED_DIM", "768")))
    
    memory_db: str = Field(default_factory=lambda: os.getenv("MEMORY_DB", "/data/memory.db"))
    memory_index: str = Field(default_factory=lambda: os.getenv("MEMORY_INDEX", "/data/memory.faiss"))
    audit_db: str = Field(default_factory=lambda: os.getenv("AUDIT_DB", "/data/audit.db"))
    files_dir: str = Field(default_factory=lambda: os.getenv("FILES_DIR", "/data"))
    
    price_in_per_1m: float = Field(default_factory=lambda: float(os.getenv("PRICE_IN_PER_1M", "10.0")))
    price_out_per_1m: float = Field(default_factory=lambda: float(os.getenv("PRICE_OUT_PER_1M", "30.0")))
    price_currency: str = Field(default_factory=lambda: os.getenv("PRICE_CURRENCY", "USD"))
    
    memory_port: int = Field(default_factory=lambda: int(os.getenv("MEMORY_PORT", "8001")))
    file_bridge_port: int = Field(default_factory=lambda: int(os.getenv("FILE_BRIDGE_PORT", "8002")))
    audit_port: int = Field(default_factory=lambda: int(os.getenv("AUDIT_PORT", "8003")))

@lru_cache
def settings() -> Settings:
    return Settings()
