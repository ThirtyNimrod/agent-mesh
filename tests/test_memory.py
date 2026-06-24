import os
import pytest
import numpy as np
from common.config import settings
import servers.memory_store as store

@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    """Sets up temporary database and index paths for isolated testing."""
    db_file = str(tmp_path / "memory.db")
    index_file = str(tmp_path / "memory.faiss")
    
    # Override settings using monkeypatch
    monkeypatch.setattr(settings(), "memory_db", db_file)
    monkeypatch.setattr(settings(), "memory_index", index_file)
    
    def mock_embed(text: str) -> np.ndarray:
        # Return a deterministic unit vector based on the words in the text (bag-of-words style)
        v = np.zeros(settings().embed_dim, dtype="float32")
        words = text.lower().split()
        for w in words:
            h = hash(w) & 0xfff
            v[h % settings().embed_dim] = 1.0
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        return v
        
    monkeypatch.setattr(store, "embed", mock_embed)
    
    # Initialize DB and index
    store.init_db()
    store.init_index()
    
    yield
    
    # Cleanup global index state
    store._index = None

def test_add_and_search():
    # Add memories
    rec1 = store.add("The quick brown fox jumps over the lazy dog", {"source": "fox"}, ["animals"])
    rec2 = store.add("Artificial Intelligence is transforming code automation", {"source": "ai"}, ["tech"])
    
    assert rec1["id"] == 1
    assert rec2["id"] == 2
    
    # Search
    results = store.search("fox", limit=5, min_score=0.1)
    assert len(results) >= 1
    assert results[0]["id"] == 1
    assert "fox" in results[0]["text"]
    assert results[0]["tags"] == ["animals"]
    assert results[0]["metadata"] == {"source": "fox"}

def test_delete():
    store.add("Memory to be deleted", {}, [])
    assert len(store.list_memories(limit=10)["items"]) == 1
    
    # Delete it
    success = store.delete_memory(1)
    assert success is True
    
    # Verify deletion
    assert len(store.list_memories(limit=10)["items"]) == 0
    
    # Idempotent delete
    success_retry = store.delete_memory(1)
    assert success_retry is False

def test_rebuild_index(tmp_path, monkeypatch):
    # Add memory
    store.add("Important concept", {}, ["key"])
    
    # Verify it searches successfully
    assert len(store.search("concept", limit=1)) == 1
    
    # Delete the FAISS index file and clear global cache to trigger rebuild on next init
    store._index = None
    if os.path.exists(settings().memory_index):
        os.remove(settings().memory_index)
        
    # Reinitialize index: this should rebuild from SQLite database
    store.init_index()
    
    # Search should still succeed
    res = store.search("concept", limit=1)
    assert len(res) == 1
    assert res[0]["text"] == "Important concept"
