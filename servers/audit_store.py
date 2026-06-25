import os
import json
import datetime
import sqlite3
import math
from common.config import settings

def get_db_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database. Creates parent directories if missing."""
    s = settings()
    db_path = s.audit_db
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the prompt audit database schema."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens_in INTEGER NOT NULL,
                tokens_out INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL,
                quality_score REAL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

def log_call(
    run_id: str,
    step: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    quality_score: float | None = None,
    metadata: dict | None = None
) -> int:
    """Logs a single LLM call to the audit database."""
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO calls (run_id, step, model, tokens_in, tokens_out, latency_ms, quality_score, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step,
                model,
                tokens_in,
                tokens_out,
                latency_ms,
                quality_score,
                json.dumps(metadata or {}),
                now_str
            )
        )
        conn.commit()
        return cursor.lastrowid

def get_stats(run_id: str | None = None, since: str | None = None) -> dict:
    """Aggregates logged call metrics into a structured summary report."""
    query = "SELECT tokens_in, tokens_out, latency_ms, quality_score FROM calls WHERE 1=1"
    params = []
    
    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    if since:
        query += " AND created_at >= ?"
        params.append(since)

    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    total_calls = len(rows)
    if total_calls == 0:
        s = settings()
        return {
            "scope": {"run_id": run_id, "since": since},
            "calls": 0,
            "tokens": {"in": 0, "out": 0, "total": 0, "avg_in": 0.0, "avg_out": 0.0},
            "latency_ms": {"total": 0, "avg": 0.0, "p95": 0.0},
            "quality": {"avg": 0.0, "min": 0.0},
            "cost": {
                "local": {"compute_seconds": 0.0, "currency_cost": 0.0},
                "notional_cloud": {
                    "in_rate_per_1m": s.price_in_per_1m,
                    "out_rate_per_1m": s.price_out_per_1m,
                    "currency": s.price_currency,
                    "cost": 0.0
                }
            }
        }

    # Aggregate tokens & latency
    total_in = sum(r["tokens_in"] for r in rows)
    total_out = sum(r["tokens_out"] for r in rows)
    total_tokens = total_in + total_out
    
    total_latency = sum(r["latency_ms"] for r in rows)
    avg_latency = total_latency / total_calls
    
    # Calculate P95 latency
    latencies = sorted(r["latency_ms"] for r in rows)
    p95_idx = max(0, min(total_calls - 1, math.ceil(0.95 * total_calls) - 1))
    p95_latency = latencies[p95_idx]

    # Aggregate quality score (filter out None values)
    quality_scores = [r["quality_score"] for r in rows if r["quality_score"] is not None]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
    min_quality = min(quality_scores) if quality_scores else 0.0

    # Calculate local vs cloud cost
    s = settings()
    compute_sec = round(total_latency / 1000.0, 2)
    
    cloud_cost = (total_in / 1e06 * s.price_in_per_1m) + (total_out / 1e06 * s.price_out_per_1m)
    cloud_cost = round(cloud_cost, 4)

    return {
        "scope": {"run_id": run_id, "since": since},
        "calls": total_calls,
        "tokens": {
            "in": total_in,
            "out": total_out,
            "total": total_tokens,
            "avg_in": round(total_in / total_calls, 2),
            "avg_out": round(total_out / total_calls, 2)
        },
        "latency_ms": {
            "total": total_latency,
            "avg": round(avg_latency, 2),
            "p95": float(p95_latency)
        },
        "quality": {
            "avg": round(avg_quality, 4),
            "min": round(min_quality, 4)
        },
        "cost": {
            "local": {
                "compute_seconds": compute_sec,
                "currency_cost": 0.0
            },
            "notional_cloud": {
                "in_rate_per_1m": s.price_in_per_1m,
                "out_rate_per_1m": s.price_out_per_1m,
                "currency": s.price_currency,
                "cost": cloud_cost
            }
        }
    }

def get_anomalies(metric: str, k: float = 3.0, run_id: str | None = None, window: int | None = None) -> dict:
    """Identifies statistical anomalies in LLM call performance using rolling standard deviations."""
    query = "SELECT id, run_id, step, model, tokens_in, tokens_out, latency_ms FROM calls"
    params = []
    
    if run_id:
        query += " WHERE run_id = ?"
        params.append(run_id)
        
    query += " ORDER BY id DESC"
    
    if window:
        query += " LIMIT ?"
        params.append(window)

    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    # Reorder chronically
    rows = list(reversed(rows))
    
    total_records = len(rows)
    if total_records < 2:
        return {
            "metric": metric,
            "mean": 0.0,
            "std": 0.0,
            "k": k,
            "anomalies": []
        }

    # Extract values for the chosen metric
    values = []
    for r in rows:
        if metric == "latency_ms":
            val = r["latency_ms"]
        elif metric == "total_tokens":
            val = r["tokens_in"] + r["tokens_out"]
        else:
            raise ValueError(f"Invalid anomaly metric: {metric}")
        values.append(val)

    mean = sum(values) / total_records
    variance = sum((x - mean) ** 2 for x in values) / total_records
    std = math.sqrt(variance)
    if std == 0.0:
        std = 1e-09

    anomalies = []
    for i, r in enumerate(rows):
        val = values[i]
        z = (val - mean) / std
        if abs(z) >= k:
            anomalies.append({
                "id": r["id"],
                "value": val,
                "z": round(z, 2),
                "run_id": r["run_id"],
                "step": r["step"],
                "model": r["model"]
            })

    return {
        "metric": metric,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "k": k,
        "anomalies": anomalies
    }
