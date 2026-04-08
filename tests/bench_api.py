"""
NetPilot API 压力测试脚本 v2
500 台设备 + 1000 台服务器数据量下的完整压测。
使用 asyncio + httpx 对核心 API 端点做并发压测，收集 P50/P95/P99 延迟和吞吐量。
"""
import asyncio
import time
import statistics
import json
import sys
import random
import httpx

BASE = "http://127.0.0.1:8003"

# ── 先登录拿 token ────────────────────────────────────────────
async def get_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(f"{BASE}/api/login", json={"username": "admin", "password": "admin123"})
    if resp.status_code == 200:
        data = resp.json()
        return data.get("data", {}).get("token") or data.get("token", "")
    # 尝试默认密码
    resp2 = await client.post(f"{BASE}/api/login", json={"username": "admin", "password": "admin"})
    if resp2.status_code == 200:
        data = resp2.json()
        return data.get("data", {}).get("token") or data.get("token", "")
    print(f"[WARN] 登录失败 ({resp.status_code}), 将以无 token 模式测试")
    return ""


# ── 压测某个端点 ─────────────────────────────────────────
async def bench_endpoint(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    concurrency: int,
    total_requests: int,
    label: str,
    payload: dict | None = None,
):
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    status_codes: dict[int, int] = {}

    async def fire():
        nonlocal errors
        async with semaphore:
            t0 = time.perf_counter()
            try:
                if method == "GET":
                    resp = await client.get(url, headers=headers, timeout=30.0)
                else:
                    resp = await client.post(url, headers=headers, json=payload, timeout=30.0)
                elapsed = (time.perf_counter() - t0) * 1000  # ms
                latencies.append(elapsed)
                sc = resp.status_code
                status_codes[sc] = status_codes.get(sc, 0) + 1
                if sc >= 400:
                    errors += 1
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed)
                errors += 1
                status_codes[-1] = status_codes.get(-1, 0) + 1

    t_start = time.perf_counter()
    await asyncio.gather(*[fire() for _ in range(total_requests)])
    wall_time = time.perf_counter() - t_start

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.5)] if n else 0
    p95 = latencies[int(n * 0.95)] if n else 0
    p99 = latencies[int(n * 0.99)] if n else 0
    avg = statistics.mean(latencies) if n else 0
    rps = total_requests / wall_time if wall_time > 0 else 0

    return {
        "label": label,
        "total": total_requests,
        "concurrency": concurrency,
        "wall_time_s": round(wall_time, 2),
        "rps": round(rps, 1),
        "avg_ms": round(avg, 1),
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "min_ms": round(min(latencies), 1) if latencies else 0,
        "max_ms": round(max(latencies), 1) if latencies else 0,
        "errors": errors,
        "status_codes": dict(sorted(status_codes.items())),
    }


def print_result(r: dict):
    print(f"\n{'='*60}")
    print(f"  {r['label']}")
    print(f"{'='*60}")
    print(f"  请求总数: {r['total']}   并发: {r['concurrency']}   耗时: {r['wall_time_s']}s")
    print(f"  吞吐量:   {r['rps']} req/s")
    print(f"  延迟:     avg={r['avg_ms']}ms  P50={r['p50_ms']}ms  P95={r['p95_ms']}ms  P99={r['p99_ms']}ms")
    print(f"  范围:     min={r['min_ms']}ms  max={r['max_ms']}ms")
    print(f"  错误:     {r['errors']}/{r['total']}")
    print(f"  状态码:   {r['status_codes']}")


async def main():
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            print(f"[OK] 已获取 token: {token[:20]}...")
        else:
            print("[WARN] 无 token, 部分端点可能 401")

        # 先验证数据量
        r = await client.get(f"{BASE}/api/devices?page=1&page_size=1", headers=headers, timeout=10.0)
        if r.status_code == 200:
            total = r.json().get("data", {}).get("total", "?")
            print(f"[INFO] 数据库设备数: {total}")

        # ── 第一轮：常规负载（并发20, 500请求） ────────
        print(f"\n{'#'*60}")
        print(f"  第一轮：常规负载 (并发20, 500请求/端点)")
        print(f"  数据量: 503 台设备 + 1002 台服务器")
        print(f"{'#'*60}")

        round1_tests = [
            ("GET",  "/api/health",                              "Health Check",              20, 500, None),
            ("GET",  "/api/devices?page=1&page_size=50",         "设备列表 (50/页)",            20, 500, None),
            ("GET",  "/api/devices?page=1&page_size=200",        "设备列表 (200/页-满载)",       20, 500, None),
            ("GET",  "/api/devices?page=1&page_size=50&mode=light", "设备列表 (轻量模式)",      20, 500, None),
            ("GET",  "/api/devices?page=3&page_size=50",         "设备列表 (第3页深翻页)",       20, 500, None),
            ("GET",  "/api/monitoring/overview",                  "监控概览",                   20, 500, None),
            ("GET",  "/api/alerts?status=open",                  "告警列表 (open)",             20, 500, None),
            ("GET",  "/api/alerts?status=resolved&page=1&page_size=50", "历史告警 (resolved)",  20, 500, None),
            ("GET",  "/api/audit/events?page=1&page_size=50",    "审计日志 (50/页)",            20, 500, None),
            ("GET",  "/api/compliance/overview",                  "合规概览",                   20, 300, None),
            ("GET",  "/api/compliance/findings?page=1&page_size=50", "合规缺陷列表",            20, 500, None),
            ("GET",  "/api/config/snapshots/latest?page=1&page_size=20", "最新配置备份",        20, 500, None),
            ("GET",  "/api/assets?page=1&page_size=50",          "资产列表 (50/页)",            20, 500, None),
            ("GET",  "/api/ipam/subnets",                        "IP/VLAN 子网",               20, 300, None),
        ]

        results = []
        for method, path, label, conc, total, payload in round1_tests:
            url = f"{BASE}{path}"
            r = await bench_endpoint(client, method, url, headers, conc, total, label, payload)
            print_result(r)
            results.append(r)

        # ── 第二轮：高并发压力（并发50, 1000请求） ────
        print(f"\n\n{'#'*60}")
        print(f"  第二轮：高并发压力 (并发50, 1000请求)")
        print(f"{'#'*60}")

        round2_tests = [
            ("GET",  "/api/health",                              "Health (C50)",              50, 1000, None),
            ("GET",  "/api/devices?page=1&page_size=50",         "设备列表 (C50)",             50, 1000, None),
            ("GET",  "/api/alerts?status=open",                  "告警列表 (C50)",             50, 1000, None),
            ("GET",  "/api/audit/events?page=1&page_size=50",    "审计日志 (C50)",             50, 1000, None),
            ("GET",  "/api/monitoring/overview",                  "监控概览 (C50)",             50, 1000, None),
        ]
        for method, path, label, conc, total, payload in round2_tests:
            url = f"{BASE}{path}"
            r = await bench_endpoint(client, method, url, headers, conc, total, label, payload)
            print_result(r)
            results.append(r)

        # ── 第三轮：极限压力（并发100, 3000请求） ─────
        print(f"\n\n{'#'*60}")
        print(f"  第三轮：极限压力 (并发100, 3000请求)")
        print(f"{'#'*60}")

        round3_tests = [
            ("GET",  "/api/health",                              "Health (C100)",             100, 3000, None),
            ("GET",  "/api/devices?page=1&page_size=50",         "设备列表 (C100)",            100, 3000, None),
        ]
        for method, path, label, conc, total, payload in round3_tests:
            url = f"{BASE}{path}"
            r = await bench_endpoint(client, method, url, headers, conc, total, label, payload)
            print_result(r)
            results.append(r)

        # ── 第四轮：混合负载模拟真实使用 ──────────────
        print(f"\n\n{'#'*60}")
        print(f"  第四轮：混合负载 (并发30, 2000请求随机端点)")
        print(f"{'#'*60}")

        mixed_endpoints = [
            "/api/devices?page=1&page_size=50",
            "/api/devices?page=2&page_size=50",
            "/api/monitoring/overview",
            "/api/alerts?status=open",
            "/api/audit/events?page=1&page_size=50",
            "/api/compliance/findings?page=1&page_size=50",
            "/api/assets?page=1&page_size=50",
            "/api/health",
        ]

        mixed_latencies = []
        mixed_errors = 0
        mixed_status = {}
        semaphore = asyncio.Semaphore(30)
        mixed_total = 2000

        async def mixed_fire():
            nonlocal mixed_errors
            async with semaphore:
                url = f"{BASE}{random.choice(mixed_endpoints)}"
                t0 = time.perf_counter()
                try:
                    resp = await client.get(url, headers=headers, timeout=30.0)
                    elapsed = (time.perf_counter() - t0) * 1000
                    mixed_latencies.append(elapsed)
                    sc = resp.status_code
                    mixed_status[sc] = mixed_status.get(sc, 0) + 1
                    if sc >= 400:
                        mixed_errors += 1
                except Exception:
                    elapsed = (time.perf_counter() - t0) * 1000
                    mixed_latencies.append(elapsed)
                    mixed_errors += 1
                    mixed_status[-1] = mixed_status.get(-1, 0) + 1

        t_start = time.perf_counter()
        await asyncio.gather(*[mixed_fire() for _ in range(mixed_total)])
        wall_time = time.perf_counter() - t_start

        mixed_latencies.sort()
        n = len(mixed_latencies)
        mixed_result = {
            "label": "混合负载 (C30, 8端点随机)",
            "total": mixed_total,
            "concurrency": 30,
            "wall_time_s": round(wall_time, 2),
            "rps": round(mixed_total / wall_time, 1) if wall_time > 0 else 0,
            "avg_ms": round(statistics.mean(mixed_latencies), 1) if n else 0,
            "p50_ms": round(mixed_latencies[int(n * 0.5)], 1) if n else 0,
            "p95_ms": round(mixed_latencies[int(n * 0.95)], 1) if n else 0,
            "p99_ms": round(mixed_latencies[int(n * 0.99)], 1) if n else 0,
            "min_ms": round(min(mixed_latencies), 1) if n else 0,
            "max_ms": round(max(mixed_latencies), 1) if n else 0,
            "errors": mixed_errors,
            "status_codes": dict(sorted(mixed_status.items())),
        }
        print_result(mixed_result)
        results.append(mixed_result)

        # ── 汇总表 ────────────────────────────────────
        print(f"\n\n{'='*90}")
        print(f"{'端点':<35} {'并发':>4} {'RPS':>8} {'P50':>8} {'P95':>8} {'P99':>8} {'错误':>6}")
        print(f"{'-'*90}")
        for r in results:
            print(f"{r['label']:<35} {r['concurrency']:>4} {r['rps']:>8.1f} {r['p50_ms']:>7.1f}ms {r['p95_ms']:>7.1f}ms {r['p99_ms']:>7.1f}ms {r['errors']:>5}")
        print(f"{'='*90}")


if __name__ == "__main__":
    asyncio.run(main())
