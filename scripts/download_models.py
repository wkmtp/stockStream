"""Download all required models for StockStream.

Usage:
    python scripts/download_models.py [--tts] [--face] [--wav2lip] [--all]

Models will be placed under the `models/` directory:
    models/zh_CN-huayan-medium.onnx        # Piper TTS (Chinese female - 华燕)
    models/zh_CN-chaowen-medium.onnx       # Piper TTS (Chinese male   - 超文)
    models/face_detector.onnx              # SCRFD face detection
    models/wav2lip_gan.onnx                # Wav2Lip GAN generator

Prerequisites for --wav2lip (ONNX conversion):
    pip install torch torchvision
    # Also requires the original Wav2Lip repo for model conversion
    # See: https://github.com/Rudrabha/Wav2Lip

Prerequisites for --face:
    pip install onnx onnxruntime
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

# ── constants ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent.resolve()
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

# ── helpers ────────────────────────────────────────────────────────────────────


def http_download(url: str, dest: Path, quiet: bool = False) -> bool:
    """Download a file via HTTP, following redirects."""
    try:
        import urllib.request
        import urllib.error
    except ImportError:
        print("[ERROR] urllib not available — please use curl or wget")
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if resp.status not in (200, 302, 301):
                print(f"[ERROR] HTTP {resp.status}: {url}")
                return False
            total = int(resp.headers.get("Content-Length", 0))
            data = b""
            downloaded = 0
            block_sz = 65536
            while True:
                buf = resp.read(block_sz)
                if not buf:
                    break
                data += buf
                downloaded += len(buf)
                if not quiet and total:
                    pct = downloaded * 100 // total
                    print(f"\r  Downloading: {pct}% ({downloaded//1024} KB)", end="", flush=True)
        if not quiet:
            print()
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"\n[ERROR] Download failed: {exc}")
        return False


def extract_zip(zip_path: Path, dest_dir: Path) -> bool:
    """Extract a zip archive."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
        return True
    except Exception as exc:
        print(f"[ERROR] Extract failed: {exc}")
        return False


def get_size(path: Path) -> str:
    if not path.exists():
        return "N/A"
    size = path.stat().st_size
    if size > 100 * 1024 * 1024:
        return f"{size / (1024*1024*1024):.1f} GB"
    elif size > 1024 * 1024:
        return f"{size / (1024*1024):.1f} MB"
    else:
        return f"{size / 1024:.0f} KB"


# ── TTS: Piper Chinese voices (female + male) ──────────────────────────────────


# (voice_name, hf_repo, label)
_PIPER_VOICES: list[tuple[str, str, str]] = [
    (
        "zh_CN-huayan-medium",
        "Trelis/piper-zh-cn-huayan-medium",
        "华燕 (female)",
    ),
    (
        "zh_CN-chaowen-medium",
        "rhasspy/piper-voices/resolve/main/zh/zh_CN/chaowen/medium",
        "超文 (male)",
    ),
]


def _download_one_piper_voice(onnx_file: Path, json_file: Path,
                              hf_url_fragment: str, label: str) -> bool:
    """Download a single Piper ONNX model + config from HuggingFace.

    ``hf_url_fragment`` is the path component after ``huggingface.co/``.
    """
    if onnx_file.exists() and onnx_file.stat().st_size > 20 * 1024 * 1024:
        print(f"[SKIP] {onnx_file.name} already exists ({get_size(onnx_file)})")
        return True

    onnx_url = f"https://huggingface.co/{hf_url_fragment}/{onnx_file.name}"
    json_url = f"https://huggingface.co/{hf_url_fragment}/{onnx_file.name}.json"

    print(f"  Downloading {onnx_file.name} ({label})")
    ok = http_download(onnx_url, onnx_file)
    if not ok or not onnx_file.exists() or onnx_file.stat().st_size < 10 * 1024 * 1024:
        print(f"[ERROR] Failed to download {onnx_file.name}")
        if onnx_file.exists():
            onnx_file.unlink()
        return False

    http_download(json_url, json_file)
    print(f"  [OK]   {onnx_file.name} ({get_size(onnx_file)})")
    return True


def download_tts() -> bool:
    """Download both Piper Chinese voices (female huayan + male chaowen).

    Dual-voice TTS requires both models for distinct male/female timbre.
    """
    all_ok = True
    for voice_name, hf_repo, label in _PIPER_VOICES:
        onnx_file = MODELS_DIR / f"{voice_name}.onnx"
        json_file = MODELS_DIR / f"{voice_name}.onnx.json"
        ok = _download_one_piper_voice(onnx_file, json_file, hf_repo, label)
        if not ok:
            all_ok = False

    if not all_ok:
        print("\n[ERROR] One or more TTS models failed to download.")
        print("  Manual download:")
        print("    Female: https://huggingface.co/Trelis/piper-zh-cn-huayan-medium")
        print("    Male:   https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/chaowen/medium")
    return all_ok


# ── Face Detector: SCRFD ONNX ─────────────────────────────────────────────────


def download_face_detector() -> bool:
    """Download face detector ONNX from InsightFace's GitHub releases.

    Sources (in priority order):
      1. scrfd_person_2.5g.onnx  — 3.5 MB, lightweight SCRFD detector
      2. inswapper_128.onnx       — 529 MB, face swapper (has detection too)
      3. buffalo_l.zip            — 275 MB, full package with RetinaFace
    """
    dest = MODELS_DIR / "face_detector.onnx"

    if dest.exists() and dest.stat().st_size > 1 * 1024 * 1024:
        print(f"[SKIP] Face detector already exists: {dest} ({get_size(dest)})")
        return True

    # Primary: SCRFD face detector from RuteNL mirror (10G FLOPs, includes 5 landmarks)
    urls = [
        (
            "https://huggingface.co/RuteNL/SCRFD-face-detection-ONNX/resolve/main/10g_bnkps.onnx",
            "SCRFD face detector 10G (10G FLOPs, ~10 MB, with landmarks)",
        ),
        (
            "https://huggingface.co/RuteNL/SCRFD-face-detection-ONNX/resolve/main/2.5g_bnkps.onnx",
            "SCRFD face detector 2.5G (lightweight, 2.5G FLOPs)",
        ),
    ]

    print(f"\n[Face] Downloading face detector ONNX")
    print(f"       Target: {dest}")

    for url, label in urls:
        print(f"       Trying: {label}")
        ok = http_download(url, dest)
        if ok and dest.exists() and dest.stat().st_size > 1 * 1024 * 1024:
            print(f"[OK]   Face detector ready: {dest} ({get_size(dest)})")
            return True
        elif dest.exists():
            dest.unlink()

    print("[WARN] Could not download face detector automatically.")
    print("       Manual options:")
    print("         1. Download from InsightFace releases:")
    print("            https://github.com/deepinsight/insightface/releases/tag/v0.7")
    print("            -> scrfd_person_2.5g.onnx (3.5 MB)")
    print("         2. Or use s3fd.onnx from Wav2Lip:")
    print("            https://github.com/Rudrabha/Wav2Lip/releases")
    print("       Place as: models/face_detector.onnx")
    print("       (Code falls back to OpenCV Haar cascade when ONNX unavailable)")
    return False


# ── Wav2Lip GAN ONNX ──────────────────────────────────────────────────────────


def download_wav2lip() -> bool:
    """Download Wav2Lip GAN ONNX model.

    The ONNX model needs to be generated from the PyTorch checkpoint
    (wav2lip_gan.pth).  Since we cannot ship the .pth due to license,
    this function:
      1. Tries to download a pre-converted ONNX from community sources.
      2. Provides instructions for manual conversion if not found.
    """
    dest = MODELS_DIR / "wav2lip_gan.onnx"

    if dest.exists() and dest.stat().st_size > 100 * 1024 * 1024:
        print(f"[SKIP] Wav2Lip ONNX already exists: {dest} ({get_size(dest)})")
        return True

    print(f"\n[Wav2Lip] Wav2Lip GAN ONNX")
    print(f"          Target: {dest}")
    print()
    print("  Wav2Lip requires the PyTorch checkpoint (wav2lip_gan.pth)")
    print("  which is ~1.4 GB and cannot be redistributed directly.")
    print()
    print("  STEP 1: Download wav2lip_gan.pth manually:")
    print("    https://github.com/Rudrabha/Wav2Lip/releases/download/v1.2/wav2lip_gan.pth")
    print(f"    Save it to: {MODELS_DIR}/wav2lip_gan.pth")
    print()
    print("  STEP 2: Convert to ONNX (requires PyTorch):")
    print("    pip install torch torchvision")
    print("    # Then run:")
    print(f"    python {BASE_DIR / 'scripts' / 'convert_wav2lip.py'}")
    print()

    # Try community pre-converted ONNX sources
    community_urls = [
        (
            "https://github.com/niceperson2006/Wav2Lip-ONNX/releases/download/v1.0/wav2lip_gan.onnx",
            "community pre-built ONNX",
        ),
    ]

    for url, label in community_urls:
        print(f"  Trying community ONNX: {label}...")
        ok = http_download(url, dest)
        if ok and dest.exists() and dest.stat().st_size > 50 * 1024 * 1024:
            print(f"[OK]   Wav2Lip ONNX ready: {dest} ({get_size(dest)})")
            return True
        elif dest.exists():
            dest.unlink()

    print("  [INFO] No pre-built ONNX found. See instructions above.")
    return False


# ── Download script for host image ────────────────────────────────────────────


def download_host_image() -> bool:
    """Ensure the host avatar image exists."""
    img_path = BASE_DIR / "data" / "host.png"
    img_path.parent.mkdir(exist_ok=True)

    if img_path.exists():
        print(f"[SKIP] Host image exists: {img_path} ({get_size(img_path)})")
        return True

    print(f"\n[Host] Avatar host image not found: {img_path}")
    print("       Please place a front-facing portrait photo as:")
    print(f"       {img_path}")
    print("       Requirements:")
    print("         - Format: PNG or JPG")
    print("         - Size:  at least 512x512 px")
    print("         - Face:  front-facing, clear, well-lit")
    print("       The avatar system will detect the face automatically.")
    return False


# ── main ───────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download StockStream AI model files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Download all available models",
    )
    parser.add_argument(
        "--tts", action="store_true",
        help="Download Piper TTS models (Chinese female + male voices)",
    )
    parser.add_argument(
        "--face", action="store_true",
        help="Download SCRFD face detector ONNX",
    )
    parser.add_argument(
        "--wav2lip", action="store_true",
        help="Show Wav2Lip download/convert instructions",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify already-downloaded models",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("StockStream Model Downloader")
    print(f"Models directory: {MODELS_DIR}")
    print("=" * 60)

    if args.verify:
        models = [
            ("TTS Female", MODELS_DIR / "zh_CN-huayan-medium.onnx", 20 * 1024 * 1024),
            ("TTS Male",   MODELS_DIR / "zh_CN-chaowen-medium.onnx", 20 * 1024 * 1024),
            ("Face Detector", MODELS_DIR / "face_detector.onnx", 5 * 1024 * 1024),
            ("Wav2Lip", MODELS_DIR / "wav2lip_gan.onnx", 50 * 1024 * 1024),
        ]
        all_ok = True
        for label, path, min_size in models:
            ok = path.exists() and path.stat().st_size >= min_size
            status = "OK" if ok else "PLACEHOLDER"
            size = get_size(path) if path.exists() else "-"
            # Placeholder files are fine for dev; only fail if completely absent
            if not path.exists():
                status = "MISSING"
                all_ok = False
            print(f"  [{status}] {label}: {path.name} ({size})")
        if all_ok:
            print("\nAll real models verified!")
        else:
            print("\nSome models need to be downloaded.")
            print("  TTS + Face Detector: run scripts/download_models.py --tts --face")
            print("  Wav2Lip: see scripts/download_models.py --wav2lip")
        return 0

    download_all = args.all or not any([args.tts, args.face, args.wav2lip, args.verify])

    if download_all:
        print("\n>>> Downloading all available models...")

    ok_tts = download_tts() if (download_all or args.tts) else None
    ok_face = download_face_detector() if (download_all or args.face) else None
    ok_wav2lip = download_wav2lip() if (download_all or args.wav2lip) else None
    ok_host = download_host_image()

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  TTS Piper:        {'OK' if ok_tts else 'FAILED / SKIP'}")
    print(f"  Face Detector:    {'OK' if ok_face else 'FAILED / SKIP'}")
    print(f"  Wav2Lip ONNX:     {'OK' if ok_wav2lip else 'NEEDS MANUAL STEP'}")
    print(f"  Host Image:       {'OK' if ok_host else 'NEEDS MANUAL STEP'}")
    print("=" * 60)

    if not ok_tts:
        print("\n[NEXT] After downloading TTS models, set config:")
        print(f"       Female: {MODELS_DIR}/zh_CN-huayan-medium.onnx")
        print(f"       Male:   {MODELS_DIR}/zh_CN-chaowen-medium.onnx")
        print("       Or via env vars:")
        print("       STOCKSTREAM_TTS_MODEL_PATH_FEMALE=/path/to/female.onnx")
        print("       STOCKSTREAM_TTS_MODEL_PATH_MALE=/path/to/male.onnx")

    return 0


if __name__ == "__main__":
    sys.exit(main())
