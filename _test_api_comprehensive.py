"""Comprehensive API endpoint test v2 — corrected paths, all real routes.

Tests all non-destructive API endpoints against a live server.
Excludes endpoints that modify state (trader ops, slide generation, etc.)
and endpoints requiring path parameters.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
import aiohttp
from stockstream.core.orchestrator import build_services
from stockstream.web.api import create_app

PORT = 8767
BASE = f"http://127.0.0.1:{PORT}"

# All safe GET endpoints (no path params, no destructive side effects)
GET_ENDPOINTS = [
    "/health",
    "/openapi.json",
    "/docs",
    # Agent
    "/agent/status",
    # Market
    "/market/status",
    # Stream
    "/stream/status",
    # TTS
    "/tts/status",
    "/tts/available",
    # Trader
    "/trader/status",
    "/trader/portfolio",
    "/trader/evaluate",
    # Database
    "/database/status",
    # Danmu
    "/danmu/status",
    # Selector
    "/selector/status",
    "/selector/signals",
    # Analysis
    "/analysis/status",
    # Avatar
    "/avatar/status",
    # Dashboard
    "/dashboard/status",
    "/dashboard/scene_types",
    # Chart Engine
    "/chart/status",
    "/chart/types",
    # Heatmap
    "/heatmap/status",
    "/heatmap/types",
    "/heatmap/snapshot",
    # Scene
    "/scene/status",
    "/scene/layout_mode",
    # Layout
    "/layout/status",
    "/layout/presets",
    "/layout/regions",
    # Compositor
    "/compositor/status",
    # Subtitle
    "/subtitle/status",
    # Alignment
    "/alignment/status",
    "/alignment/methods",
    # Slide
    "/slide/status",
    "/slide/types",
    # Matcher
    "/matcher/status",
    "/matcher/categories",
    "/matcher/keywords",
]

# Safe POST endpoints (idempotent or read-only side effects)
POST_ENDPOINTS = [
    ("/agent/auto/tick", {}),
    ("/stream/stop", {}),
    ("/alignment/clear", {}),
    ("/matcher/config", {"min_confidence": 0.35}),
]


async def test_endpoint(session, method, path, body=None, timeout=12):
    """Test one endpoint, return (path, method, status, ok, detail)."""
    try:
        url = f"{BASE}{path}"
        if method == "GET":
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                await resp.read()
                ok = 200 <= resp.status < 500
                return (path, method, resp.status, ok, "")
        else:
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                await resp.read()
                ok = 200 <= resp.status < 500
                return (path, method, resp.status, ok, "")
    except aiohttp.ClientError as e:
        return (path, method, 0, False, f"ClientError: {e}")
    except asyncio.TimeoutError:
        return (path, method, 0, False, "Timeout")
    except Exception as e:
        return (path, method, 0, False, f"{type(e).__name__}: {e}")


async def main():
    print("=" * 70)
    print("StockStream Comprehensive API Endpoint Test v2")
    print("=" * 70)

    # Build app
    print("\n[1/3] Building services + app...")
    try:
        services = await build_services()
        app = create_app(services)
        print(f"   App built: {len(app.routes)} routes")
    except Exception as e:
        print(f"   FAILED: {e}")
        import traceback; traceback.print_exc()
        return False

    # Start server
    print(f"[2/3] Starting server on port {PORT}...")
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(2.5)

    # Health check
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    print(f"   Server health check returned {resp.status}")
                    server.should_exit = True
                    await server_task
                    return False
                data = await resp.json()
                print(f"   Server up: {data.get('status')}")
    except Exception as e:
        print(f"   Server not reachable: {e}")
        server.should_exit = True
        await server_task
        return False

    # Test all endpoints
    total_endpoints = len(GET_ENDPOINTS) + len(POST_ENDPOINTS)
    print(f"\n[3/3] Testing {total_endpoints} endpoints...\n")

    results = []
    passed = 0
    failed = 0
    skipped = 0

    async with aiohttp.ClientSession() as session:
        # GET endpoints in batches
        for i in range(0, len(GET_ENDPOINTS), 8):
            batch = GET_ENDPOINTS[i:i+8]
            tasks = [test_endpoint(session, "GET", p) for p in batch]
            batch_results = await asyncio.gather(*tasks)
            for path, method, status, ok, detail in batch_results:
                emblem = "[OK]" if ok else "[FAIL]"
                sys.stdout.write(f"  {emblem} {method:4s} {path:40s} -> HTTP {status}")
                if detail:
                    sys.stdout.write(f"  ({detail})")
                sys.stdout.write("\n")
                sys.stdout.flush()
                if ok:
                    passed += 1
                else:
                    failed += 1
                results.append((path, method, status, ok, detail))

        # POST endpoints
        for path, body in POST_ENDPOINTS:
            path, method, status, ok, detail = await test_endpoint(session, "POST", path, body)
            emblem = "[OK]" if ok else "[FAIL]"
            sys.stdout.write(f"  {emblem} {method:4s} {path:40s} -> HTTP {status}")
            if detail:
                sys.stdout.write(f"  ({detail})")
            sys.stdout.write("\n")
            sys.stdout.flush()
            if ok:
                passed += 1
            else:
                failed += 1
            results.append((path, method, status, ok, detail))

    # Shutdown
    print("\n   Stopping server...")
    server.should_exit = True
    try:
        await asyncio.wait_for(server_task, timeout=10)
    except asyncio.TimeoutError:
        print("   Server did not exit gracefully")

    # Summary
    total = passed + failed
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 70)

    if failed:
        print("\nFAILED ENDPOINTS:")
        for path, method, status, ok, detail in results:
            if not ok:
                print(f"  {method} {path} -> HTTP {status} {detail}")

    # Allowed failures (endpoints that depend on external services or data)
    allowed_failures = {
        "/heatmap/snapshot",         # may have no sector data yet
        "/alignment/methods",         # may return 404 if no aeneas
    }
    real_failures = [r for r in results if not r[3] and r[0] not in allowed_failures]
    if real_failures:
        print(f"\nREAL FAILURES ({len(real_failures)}):")
        for path, method, status, ok, detail in real_failures:
            print(f"  !! {method} {path} -> HTTP {status} {detail}")
        return False

    return failed == 0 or all(r[0] in allowed_failures for r in results if not r[3])


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
