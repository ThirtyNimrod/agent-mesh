import pytest
from common.config import settings
import servers.audit_store as store

@pytest.fixture(autouse=True)
def setup_temp_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "audit.db")
    monkeypatch.setattr(settings(), "audit_db", db_file)
    
    # Configure custom price table for validation
    monkeypatch.setattr(settings(), "price_in_per_1m", 10.0)
    monkeypatch.setattr(settings(), "price_out_per_1m", 30.0)
    monkeypatch.setattr(settings(), "price_currency", "USD")
    
    store.init_db()

def test_log_and_stats():
    # Log some dummy calls
    store.log_call("run-1", "extract", "qwen", 1000, 500, 2000, 0.8)
    store.log_call("run-1", "summarize", "qwen", 2000, 1000, 3000, 0.9)
    
    # Get stats for run-1
    stats = store.get_stats(run_id="run-1")
    assert stats["calls"] == 2
    assert stats["tokens"]["in"] == 3000
    assert stats["tokens"]["out"] == 1500
    assert stats["tokens"]["total"] == 4500
    
    # Verification of averaging
    assert stats["tokens"]["avg_in"] == 1500.0
    assert stats["tokens"]["avg_out"] == 750.0
    
    # Verification of latencies
    assert stats["latency_ms"]["total"] == 5000
    assert stats["latency_ms"]["avg"] == 2500.0
    assert stats["latency_ms"]["p95"] == 3000.0
    
    # Quality score aggregates
    assert stats["quality"]["avg"] == 0.85
    assert stats["quality"]["min"] == 0.8
    
    # Cost math
    # total_in = 3000 -> 3000 / 1e6 * 10 = $0.03
    # total_out = 1500 -> 1500 / 1e6 * 30 = $0.045
    # total notional cloud cost = $0.075
    assert stats["cost"]["notional_cloud"]["cost"] == 0.075
    assert stats["cost"]["local"]["compute_seconds"] == 5.0

def test_anomaly_detection():
    # Log 9 standard calls (latency ≈ 1000ms)
    for i in range(9):
        store.log_call("run-2", "extract", "qwen", 100, 50, 1000)
        
    # Log 1 anomaly call (latency = 5000ms, which is a 5x outlier)
    store.log_call("run-2", "summarize", "qwen", 100, 50, 5000)
    
    # Run anomaly check with k=2.0 (so it catches the outlier easily)
    res = store.get_anomalies("latency_ms", k=2.0, run_id="run-2")
    assert len(res["anomalies"]) == 1
    assert res["anomalies"][0]["value"] == 5000
    assert res["anomalies"][0]["step"] == "summarize"
