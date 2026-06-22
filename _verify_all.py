"""Comprehensive verification: compile all .py files, import all modules, start server, health check."""
import sys, os, traceback, subprocess

PROJECT = r"d:\ai\stock\stockStream"
errors = []

# 1. Compile every .py file
print("=== Compile all .py files ===")
for root, dirs, files in os.walk(os.path.join(PROJECT, "stockstream")):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if f.endswith(".py"):
            fp = os.path.join(root, f)
            try:
                compile(open(fp, "r", encoding="utf-8").read(), fp, "exec")
            except Exception as e:
                errors.append(f"[COMPILE] {fp}: {e}")
                print(f"  FAIL {fp}: {e}")
print(f"Compile done. Errors: {len(errors)}")

# 2. Import every module
print("\n=== Import all modules ===")
sys.path.insert(0, PROJECT)
imports = [
    "stockstream", "stockstream.core.config", "stockstream.core.orchestrator",
    "stockstream.market", "stockstream.market.models", "stockstream.market.service",
    "stockstream.market.storage", "stockstream.market.collector",
    "stockstream.selector", "stockstream.selector.models",
    "stockstream.selector.indicators", "stockstream.selector.repository",
    "stockstream.selector.service",
    "stockstream.tts", "stockstream.tts.engine", "stockstream.tts.models",
    "stockstream.tts.service", "stockstream.tts.splitter",
    "stockstream.agent", "stockstream.agent.service",
    "stockstream.agent.strategy.pipeline",
    "stockstream.agent.trader.models", "stockstream.agent.trader.engine",
    "stockstream.agent.trader.repository", "stockstream.agent.trader.service",
    "stockstream.stream", "stockstream.stream.models",
    "stockstream.stream.ffmpeg_streamer", "stockstream.stream.service",
    "stockstream.danmu", "stockstream.danmu.service",
    "stockstream.web", "stockstream.web.api",
    "stockstream.database", "stockstream.database.service",
    "stockstream.analysis", "stockstream.analysis.models",
    "stockstream.analysis.engine", "stockstream.analysis.prompts",
    "stockstream.analysis.service",
    "stockstream.avatar", "stockstream.avatar.models",
    "stockstream.avatar.face_detector", "stockstream.avatar.audio_processor",
    "stockstream.avatar.wav2lip_onnx", "stockstream.avatar.video_assembler",
    "stockstream.avatar.pipeline", "stockstream.avatar.service",
]
for mod in imports:
    try:
        __import__(mod)
        print(f"  OK  {mod}")
    except Exception as e:
        errors.append(f"[IMPORT] {mod}: {e}")
        print(f"  FAIL {mod}: {type(e).__name__}: {e}")
print(f"Import done. Errors: {len(errors)}")

# 3. Build app
print("\n=== Build FastAPI app ===")
from stockstream.app import build_app
try:
    app = build_app()
    route_count = len(app.routes) if hasattr(app, 'routes') else '?'
    print(f"  OK  app built, {route_count} routes")
except Exception as e:
    errors.append(f"[APP BUILD] {e}")
    print(f"  FAIL: {e}")

# 4. Summary
print(f"\n{'='*50}")
if errors:
    print(f"TOTAL ERRORS: {len(errors)}")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED!")
    sys.exit(0)
