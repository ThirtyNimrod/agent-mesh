import os
import json
import datetime
import sqlite3
import threading
import numpy as np
import faiss
import httpx
from common.config import settings

# Thread lock for FAISS operations (since FAISS index modification is not thread-safe)
_index_lock = threading.Lock()
_index: faiss.IndexIDMap | None = None

def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database. Creates parent directories if missing."""
    s = settings()
    db_path = s.memory_db
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                metadata TEXT,
                tags TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

def embed(text: str) -> np.ndarray:
    """Gets L2-normalized embedding vector from Ollama API."""
    s = settings()
    try:
        r = httpx.post(
            f"{s.ollama_url}/api/embeddings",
            json={"model": s.embed_model, "prompt": text},
            timeout=30.0
        )
        r.raise_for_status()
        emb_data = r.json()
        if "embedding" not in emb_data:
            raise ValueError(f"Ollama response does not contain 'embedding': {emb_data}")
        
        v = np.array(emb_data["embedding"], dtype="float32")
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        return v
    except Exception as e:
        # Wrap and raise for caller handling
        raise RuntimeError(f"Ollama embedding error: {e}") from e

def _new_index(dim: int) -> faiss.IndexIDMap:
    """Creates a new empty FAISS IndexIDMap with flat inner product index."""
    return faiss.IndexIDMap(faiss.IndexFlatIP(dim))

def init_index():
    """Loads FAISS index from disk or rebuilds it from SQLite if missing."""
    global _index
    s = settings()
    dim = s.embed_dim
    index_path = s.memory_index

    # Ensure parent directories exist
    index_dir = os.path.dirname(index_path)
    if index_dir:
        os.makedirs(index_dir, exist_ok=True)

    with _index_lock:
        if os.path.exists(index_path):
            try:
                _index = faiss.read_index(index_path)
                # Verify loaded index matches dimension
                if _index.d != dim:
                    raise ValueError(f"Loaded index dimension {_index.d} does not match settings dim {dim}")
                return
            except Exception as e:
                # If load fails, we will trigger rebuild
                pass
        
        # Rebuild index from SQLite
        _index = _new_index(dim)
        
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, text FROM memories").fetchall()
        
        if not rows:
            # Empty database, save empty index
            faiss.write_index(_index, index_path)
            return

        ids = []
        vectors = []
        for row in rows:
            try:
                v = embed(row["text"])
                ids.append(row["id"])
                vectors.append(v)
            except Exception:
                # Skip if embed fails during rebuild, but database remains source of truth
                continue
        
        if ids:
            ids_arr = np.array(ids, dtype="int64")
            v_arr = np.vstack(vectors).astype("float32")
            _index.add_with_ids(v_arr, ids_arr)
            faiss.write_index(_index, index_path)

def add(text: str, metadata: dict, tags: list[str]) -> dict:
    """Adds a memory to SQLite and FAISS. Returns database record information."""
    global _index
    s = settings()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Insert into SQLite to get the autoincrement ID
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (text, metadata, tags, created_at) VALUES (?, ?, ?, ?)",
            (text, json.dumps(metadata), json.dumps(tags), now_str)
        )
        conn.commit()
        memory_id = cursor.lastrowid

    # 2. Compute embedding vector
    v = embed(text)

    # 3. Add to FAISS Index and persist
    with _index_lock:
        if _index is None:
            init_index()
        
        v_arr = np.array([v], dtype="float32")
        ids_arr = np.array([memory_id], dtype="int64")
        _index.add_with_ids(v_arr, ids_arr)
        faiss.write_index(_index, s.memory_index)

    return {"id": memory_id, "created_at": now_str}

def search(query: str, limit: int = 5, min_score: float = 0.0) -> list[dict]:
    """Searches memories using FAISS and loads matches from SQLite."""
    global _index
    s = settings()
    
    with _index_lock:
        if _index is None:
            init_index()
        
        # If the index is empty, return early
        if _index.ntotal == 0:
            return []

    # Get query embedding vector
    v = embed(query)

    with _index_lock:
        # Search FAISS index
        scores, ids = _index.search(np.array([v], dtype="float32"), limit)

    matched_ids = []
    id_to_score = {}
    for score_val, id_val in zip(scores[0], ids[0]):
        # FAISS returns -1 for missing elements or padding if database is smaller than limit
        if id_val == -1:
            continue
        # Check minimum score constraint
        if score_val >= min_score:
            matched_ids.append(int(id_val))
            id_to_score[int(id_val)] = float(score_val)

    if not matched_ids:
        return []

    # Fetch corresponding memories from SQLite
    placeholders = ",".join("?" for _ in matched_ids)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT id, text, metadata, tags, created_at FROM memories WHERE id IN ({placeholders})",
            matched_ids
        ).fetchall()

    results = []
    for row in rows:
        m_id = row["id"]
        results.append({
            "id": m_id,
            "score": id_to_score[m_id],
            "text": row["text"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "tags": json.loads(row["tags"]) if row["tags"] else []
        })

    # Sort results by similarity score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def list_memories(limit: int = 20, offset: int = 0) -> dict:
    """Lists stored memories in SQLite using paginated window."""
    with get_db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        rows = conn.execute(
            "SELECT id, text, metadata, tags, created_at FROM memories ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()

    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "text": row["text"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "created_at": row["created_at"]
        })

    from common.responses import paginate
    return paginate(items, total, offset)

def delete_memory(memory_id: int) -> bool:
    """Deletes memory by id from SQLite and FAISS. Idempotent."""
    global _index
    s = settings()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM memories WHERE id = ?", (memory_id,))
        exists = cursor.fetchone()
        
        if not exists:
            return False
            
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()

    with _index_lock:
        if _index is None:
            init_index()
        try:
            _index.remove_ids(np.array([memory_id], dtype="int64"))
            faiss.write_index(_index, s.memory_index)
        except Exception:
            # If FAISS remove_ids fails (e.g. index state mismatch), we force a rebuild next time
            _index = None
            if os.path.exists(s.memory_index):
                os.remove(s.memory_index)

    return True
