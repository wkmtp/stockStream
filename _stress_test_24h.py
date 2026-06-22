"""24-hour stress test for StockStream — verifies no-crash continuous operation.

Usage:
    python _stress_test_24h.py [--duration-min 1440] [--concurrency 10]
"""

import asyncio
import gc
import os
import random
import sys
import time
import traceback

# Ensure we import from the project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aiohttp
from stockstream.core.config import get_settings
from stockstream.core.orchestrator import build_services
from stockstream.web.api import create_app

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

# ── test parameters ──────────────────────────────────────────────────
DURATION_MINUTES = 1440  # 24 hours
CONCURRENCY = 10
CHECK_INTERVAL_SEC = 5
MEMORY_CHECK_EVERY = 60  # check memory growth every N seconds
MAX_ACCEPTABLE_MEMORY_MB = 500  # alert if RSS exceeds this

# AkShare network timeout for blocking calls (seconds)
AKSHARE_CALL_TIMEOUT = 15


async def hammer_endpoint(session: aiohttp.ClientSession,
                          method: str, path: str,
                          status_counter: dict) -> None:
    """Call one endpoint and record status."""
    try:
        if method == "GET":
            async with session.get(f"{BASE}{path}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status_counter[resp.status] = status_counter.get(resp.status, 0) + 1
                await resp.read()
        else:
            async with session.post(
                f"{BASE}{path}",
                json=_sample_body(path),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                status_counter[resp.status] = status_counter.get(resp.status, 0) + 1
                await resp.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        status_counter["connection_error"] = status_counter.get("connection_error", 0) + 1
    except Exception as exc:
        status_counter["client_error"] = status_counter.get("client_error", 0) + 1


def _sample_body(path: str) -> dict:
    """Return plausible body for POST endpoints."""
    mapping = {
        "/market/tick": {"symbol": "000001", "price": 12.34},
        "/agent/auto/tick": {},
        "/agent/brief": {"symbols": ["000001", "000002"]},
        "/tts/speak": {"text": "测试语音合成"},
        "/stream/start": {"input_source": "data/avatar/test.mp4"},
        "/avatar/generate": {"audio_path": "data/tts/test.wav", "image_path": "data/images/host.jpg"},
        "/trader/open": {"symbol": "000001", "name": "平安银行", "price": 12.34, "shares": 100},
        "/trader/add": {"symbol": "000001", "price": 12.50, "shares": 100},
    }
    return mapping.get(path, {})


# ── all GET endpoints ────────────────────────────────────────────────
GET_ENDPOINTS = [
    "/health",
    "/openapi.json",
    "/agent/status",
    "/market/status",
    "/stream/status",
    "/avatar/status",
    "/tts/status",
    "/tts/available",
    "/trader/status",
    "/trader/portfolio",
    "/trader/evaluate",
    "/database/status",
    "/danmu/status",
    "/selector/status",
    "/selector/signals",
    "/analysis/status",
    # Scene / Layout endpoints (correct paths)
    "/scene/status",
    "/scene/layout_mode",
    "/layout/status",
    "/layout/presets",
    "/layout/regions",
    # Dashboard / Heatmap / Chart
    "/dashboard/status",
    "/dashboard/scene_types",
    "/heatmap/status",
    "/chart/status",
    "/chart/types",
    # Subtitle / Alignment / Slide
    "/subtitle/status",
    "/alignment/status",
    "/slide/status",
    "/slide/types",
]

# ── POST endpoints ───────────────────────────────────────────────────
POST_ENDPOINTS = [
    "/agent/auto/tick",
    "/stream/stop",
]


async def worker(session: aiohttp.ClientSession,
                 status_counter: dict,
                 stop_event: asyncio.Event) -> None:
    """Continuously call random endpoints."""
    all_gets = GET_ENDPOINTS.copy()
    all_posts = POST_ENDPOINTS.copy()

    while not stop_event.is_set():
        # 80% GET, 20% POST
        if random.random() < 0.8:
            path = random.choice(all_gets)
            await hammer_endpoint(session, "GET", path, status_counter)
        else:
            path = random.choice(all_posts)
            await hammer_endpoint(session, "POST", path, status_counter)
        # Small delay between calls
        await asyncio.sleep(random.uniform(0.05, 0.3))


async def memory_monitor(stop_event: asyncio.Event,
                         mem_samples: list,
                         pid: int) -> None:
    """Track memory usage over time."""
    try:
        import psutil
        proc = psutil.Process(pid)
    except ImportError:
        return

    while not stop_event.is_set():
        await asyncio.sleep(MEMORY_CHECK_EVERY)
        try:
            rss = proc.memory_info().rss / 1024 / 1024
            mem_samples.append((time.time(), rss))
        except (psutil.NoSuchProcess, Exception):
            break


async def run_stress_test():
    """Main stress test orchestrator."""
    print("=" * 60)
    print("StockStream 24-Hour Stress Test")
    print(f"Duration: {DURATION_MINUTES} minutes")
    print(f"Concurrency: {CONCURRENCY} workers")
    print("=" * 60)

    # Build services manually (without starting collectors etc.)
    print("\n[1/4] Building services...")
    services = await build_services()
    app = create_app(services)
    pid = os.getpid()
    print(f"   PID: {pid}")

    # Start uvicorn server in background
    print("[2/4] Starting HTTP server...")
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Give server time to start
    await asyncio.sleep(2)

    # Verify server is up
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                assert resp.status == 200, f"Server returned {resp.status}"
                data = await resp.json()
                print(f"   Health check OK: {data.get('status')}")
    except Exception as exc:
        print(f"   FAILED to reach server: {exc}")
        server.should_exit = True
        await server_task
        return

    # Start workers
    print(f"[3/4] Starting {CONCURRENCY} concurrent workers...")
    stop_event = asyncio.Event()
    status_counter: dict = {}
    mem_samples: list = []

    try:
        import psutil
        has_psutil = True
    except ImportError:
        has_psutil = False

    async with aiohttp.ClientSession() as session:
        memory_task = None
        if has_psutil:
            memory_task = asyncio.create_task(memory_monitor(stop_event, mem_samples, pid))

        workers = [
            asyncio.create_task(worker(session, status_counter, stop_event))
            for _ in range(CONCURRENCY)
        ]

        # Monitor loop
        start_time = time.time()
        deadline = start_time + DURATION_MINUTES * 60
        last_report = start_time
        error_count = 0
        crash_count = 0

        print(f"[4/4] Running for {DURATION_MINUTES} minutes...")
        print(f"   Start: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")
        print(f"   End:   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(deadline))}")
        print()

        try:
            while time.time() < deadline and not server.should_exit:
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                now = time.time()
                elapsed = now - start_time

                # Check server health periodically
                try:
                    async with session.get(f"{BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status != 200:
                            crash_count += 1
                            print(f"   [WARN] HEALTH CHECK FAILED (attempt {crash_count}) at {elapsed:.0f}s")
                except Exception:
                    crash_count += 1
                    print(f"   [WARN] SERVER UNREACHABLE (attempt {crash_count}) at {elapsed:.0f}s")
                    if crash_count > 3:
                        print("   [FAIL] Server appears dead, aborting test")
                        break

                # Periodic report
                if now - last_report >= 300:  # every 5 minutes
                    total = sum(status_counter.values())
                    error_rate = (status_counter.get("connection_error", 0) +
                                  status_counter.get("client_error", 0) +
                                  status_counter.get(500, 0)) / max(total, 1) * 100

                    mem_str = ""
                    if mem_samples:
                        latest_mem = mem_samples[-1][1]
                        mem_str = f" | Memory: {latest_mem:.1f} MB"

                    print(f"   [{time.strftime('%H:%M:%S')}] {elapsed/60:.0f}min elapsed | "
                          f"{total} reqs | {error_rate:.1f}% errors "
                          f"(200={status_counter.get(200,0)} 404={status_counter.get(404,0)} "
                          f"500={status_counter.get(500,0)} conn_err={status_counter.get('connection_error',0)})"
                          f"{mem_str}")

                    last_report = now
                    error_count = 0

        except KeyboardInterrupt:
            print("\n   Interrupted by user")
        except Exception as exc:
            print(f"\n   [FAIL] Stress test error: {exc}")
            traceback.print_exc()
        finally:
            # Cleanup
            print("\n   Shutting down...")
            stop_event.set()

            # Cancel workers
            for t in workers:
                t.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

            if memory_task:
                memory_task.cancel()
                try:
                    await memory_task
                except asyncio.CancelledError:
                    pass

    # Stop server
    server.should_exit = True
    try:
        await asyncio.wait_for(server_task, timeout=10)
    except asyncio.TimeoutError:
        print("   Server did not exit gracefully")

    # ── final report ─────────────────────────────────────────────────
    total_elapsed = time.time() - start_time
    total_requests = sum(status_counter.values())

    print("\n" + "=" * 60)
    print("STRESS TEST RESULTS")
    print("=" * 60)
    print(f"  Duration:           {total_elapsed/60:.1f} minutes")
    print(f"  Total requests:     {total_requests}")
    print(f"  Requests/sec:       {total_requests / max(total_elapsed, 0.1):.1f}")
    print(f"  Server crashes:     {crash_count}")
    print()

    if status_counter:
        print("  Status code distribution:")
        for code in sorted(status_counter.keys(), key=str):
            if code not in ("client_error", "connection_error"):
                print(f"    HTTP {code}: {status_counter[code]}")
        if status_counter.get("connection_error"):
            print(f"    Connection errors: {status_counter['connection_error']}")
        if status_counter.get("client_error"):
            print(f"    Client errors:     {status_counter['client_error']}")

    if mem_samples:
        initial_mem = mem_samples[0][1]
        final_mem = mem_samples[-1][1]
        growth = final_mem - initial_mem
        print(f"\n  Memory: {initial_mem:.1f} -> {final_mem:.1f} MB "
              f"(delta = {growth:+.1f} MB)")
        if growth > 50:
            print(f"  [!] WARNING: Memory grew by {growth:.0f} MB -- possible leak!")
        elif growth < 0:
            print(f"  [OK] Memory decreased -- GC working")
        else:
            print(f"  [OK] Memory stable")

    if crash_count == 0 and status_counter.get(500, 0) == 0:
        print("\n  [PASS] No server crashes, no 500 errors!")
        return True
    elif crash_count == 0:
        print(f"\n  [WARN] {status_counter.get(500,0)} internal errors but no crashes")
        return True
    else:
        print(f"\n  [FAIL] {crash_count} server crashes detected")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-min", type=int, default=1440,
                        help="Test duration in minutes (default: 1440 = 24h)")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="Number of concurrent workers (default: 10)")
    args = parser.parse_args()

    DURATION_MINUTES = args.duration_min
    CONCURRENCY = args.concurrency

    success = asyncio.run(run_stress_test())
    sys.exit(0 if success else 1)
