import pytest
import time
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from core.context import request_id_var, user_var
from core.metrics import metrics_registry
from core.scheduler_lock import acquire_scheduler_lock, synchronized_scheduler_job
from database import get_db_connection

client = TestClient(app)

def test_context_vars():
    """Verify that context variables can be set and default values are correct."""
    assert request_id_var.get() == "-"
    assert user_var.get() == "-"
    
    token = request_id_var.set("test-request-123")
    assert request_id_var.get() == "test-request-123"
    request_id_var.reset(token)
    assert request_id_var.get() == "-"

def test_scheduler_lock():
    """Verify lock acquisition, rejection, expiration, and cleanup."""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM scheduler_locks WHERE lock_name = 'test_lock'")
        conn.commit()
    finally:
        conn.close()

    # 1. Acquire first time
    assert acquire_scheduler_lock("test_lock", expire_seconds=2) is True

    # 2. Re-acquire should fail
    assert acquire_scheduler_lock("test_lock", expire_seconds=2) is False

    # 3. Simulate lock expiration by manually updating expires_at to past time
    conn = get_db_connection()
    try:
        past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        conn.execute("UPDATE scheduler_locks SET expires_at = ? WHERE lock_name = 'test_lock'", (past,))
        conn.commit()
    finally:
        conn.close()

    # 4. Re-acquire should succeed since lock is expired
    assert acquire_scheduler_lock("test_lock", expire_seconds=2) is True

def test_scheduler_lock_decorator():
    """Verify synchronized_scheduler_job decorator prevents concurrent runs."""
    run_count = 0

    @synchronized_scheduler_job("decorator_lock", expire_seconds=2)
    def my_job():
        nonlocal run_count
        run_count += 1

    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM scheduler_locks WHERE lock_name = 'decorator_lock'")
        conn.commit()
    finally:
        conn.close()

    # First run should succeed
    my_job()
    assert run_count == 1

    # Second run should skip since lock is held
    my_job()
    assert run_count == 1

def test_health_metrics_api():
    """Verify health and metrics API returns valid status structures."""
    # Record some mock latency
    metrics_registry.record_api_latency(12.5)
    metrics_registry.record_api_latency(17.5)
    metrics_registry.record_ipam_conflict()
    metrics_registry.record_ssh(1.2, True)
    metrics_registry.record_polling(0.8, True)

    # Call /api/health
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "scheduler" in data
    assert "worker" in data
    assert "metrics" in data
    
    metrics = data["metrics"]
    assert metrics["api_latency_avg_ms"] > 0
    assert metrics["ipam_allocation_conflict_count"] >= 1
    assert metrics["ssh_success_count"] >= 1
    assert metrics["snmp_success_count"] >= 1

    # Call /api/health/metrics
    resp_metrics = client.get("/api/health/metrics")
    assert resp_metrics.status_code == 200
    m_data = resp_metrics.json()
    assert m_data["api_latency_avg_ms"] > 0
    assert m_data["ipam_allocation_conflict_count"] >= 1

@pytest.mark.asyncio
async def test_concurrency_performance():
    """Simulate concurrent database queries and IPAM address operations under load."""
    start_time = time.perf_counter()
    
    # Run 50 concurrent lookups to verify database connection pool performance
    async def db_task(i):
        await asyncio.to_thread(acquire_scheduler_lock, f"concurrent_lock_{i}", expire_seconds=5)

    tasks = [db_task(i) for i in range(50)]
    await asyncio.gather(*tasks)
    
    duration = time.perf_counter() - start_time
    print(f"Completed 50 concurrent database lock queries in {duration:.4f} seconds")
    
    # Cleanup concurrent locks
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM scheduler_locks WHERE lock_name LIKE 'concurrent_lock_%'")
        conn.commit()
    finally:
        conn.close()
    
    assert duration < 5.0  # Must be fast under pooling


def test_platform_normalization():
    """Verify that vendor-platform strict alignment prevents silent Cisco fallback."""
    from core.platform_utils import normalize_device_platform
    
    # 1. Vendor is Huawei, platform is empty or Cisco - must override to huawei_vrp
    assert normalize_device_platform("Huawei", "") == "huawei_vrp"
    assert normalize_device_platform("Huawei", "cisco_ios") == "huawei_vrp"
    
    # 2. Vendor is H3C, platform is empty or generic - must override to h3c_comware
    assert normalize_device_platform("H3C", "") == "h3c_comware"
    assert normalize_device_platform("H3C", "generic") == "h3c_comware"
    
    # 3. Matches are normalized properly
    assert normalize_device_platform("Cisco", "nxos") == "cisco_nxos"
    assert normalize_device_platform("", "vrp") == "huawei_vrp"
