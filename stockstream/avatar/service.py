"""Avatar service — async queue-based talking-head video generation.

Integrates with TTS: listens for TTSPlayEvents, then generates
a Wav2Lip talking-head MP4 for each synthesised sentence.

Usage::

    svc = AvatarService(
        host_image="streamer.jpg",
        output_dir="data/avatar",
        config=AvatarConfig(),
    )
    await svc.initialize()

    # Option 1: generate a single video
    result = await svc.generate(
        task_id="demo",
        audio_path="tts_output.wav",
    )

    # Option 2: auto-generate from TTS events
    await svc.start_auto()
    # Data flow: TTSPlayEvent → auto_enqueue → generate → stream event
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from stockstream.avatar.models import (
    AvatarConfig,
    AvatarResult,
    AvatarStatus,
    AvatarTask,
)
from stockstream.avatar.pipeline import AvatarPipeline
from stockstream.tts.models import TTSPlayEvent

logger = logging.getLogger(__name__)


class AvatarService:
    """Async service for Wav2Lip talking-head video generation.

    Features:
    - Single-video generation: image + audio → MP4
    - Auto mode: hooks into TTS play events, generates per-sentence videos
    - Progress tracking: query task status by ID
    """

    def __init__(
        self,
        *,
        host_image: str = "",
        output_dir: str = "data/avatar",
        config: AvatarConfig | None = None,
        max_cached_results: int = 100,
    ) -> None:
        self.host_image = host_image
        self.output_dir = Path(output_dir)
        self.config = config or AvatarConfig()
        self.pipeline = AvatarPipeline(self.config)
        self._tasks: dict[str, AvatarTask] = {}
        self._results: dict[str, AvatarResult] = {}
        self._max_cached_results = max_cached_results
        self._running = False
        self._auto_task: asyncio.Task[None] | None = None

        # Queue for incoming TTS events in auto mode
        self._event_queue: asyncio.Queue[TTSPlayEvent] = asyncio.Queue(maxsize=128)
        self._semaphore = asyncio.Semaphore(2)  # max concurrent generations

    # ── lifecycle ──────────────────────────────────────────────────

    async def initialize(self) -> bool:
        """Load ONNX models. Returns True if pipeline is ready."""
        ok = await self.pipeline.initialize()
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        if not ok:
            logger.warning("Avatar pipeline not fully initialised — check ONNX models")
        return ok

    async def close(self) -> None:
        """Stop auto mode and release resources."""
        self._running = False
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
            try:
                await self._auto_task
            except asyncio.CancelledError:
                pass
        logger.info("AvatarService stopped")

    def ready(self) -> bool:
        return self.pipeline.ready()

    # ── single generation ──────────────────────────────────────────

    async def generate(
        self,
        task_id: str,
        image_path: str = "",
        audio_path: str = "",
    ) -> Optional[AvatarResult]:
        """Generate a single talking-head MP4.

        Args:
            task_id: Unique task identifier.
            image_path: Host image path (uses self.host_image if empty).
            audio_path: Piper TTS WAV audio path.

        Returns:
            AvatarResult with MP4 path, or None on failure.
        """
        img = image_path or self.host_image
        if not img:
            logger.error("No host image configured")
            return None
        if not audio_path:
            logger.error("No audio path provided")
            return None
        if not Path(audio_path).exists():
            logger.error("Audio file not found: %s", audio_path)
            return None

        async with self._semaphore:
            result = await self.pipeline.generate(
                task_id=task_id,
                image_path=img,
                audio_path=audio_path,
                output_dir=self.output_dir,
            )

        if result:
            self._results[task_id] = result
            # Prune oldest results to prevent memory leak
            while len(self._results) > self._max_cached_results:
                oldest = next(iter(self._results))
                del self._results[oldest]
        return result

    async def generate_and_wait(
        self,
        task_id: str,
        audio_path: str,
        image_path: str = "",
        timeout: float = 120.0,
    ) -> Optional[AvatarResult]:
        """Generate and wait for completion."""
        return await self.generate(task_id, image_path, audio_path)

    # ── auto mode (TTS-driven) ─────────────────────────────────────

    async def start_auto(self) -> None:
        """Start the background auto-generation worker.

        In auto mode, the service listens on a queue of TTSPlayEvents.
        Each event triggers a per-sentence avatar generation.
        """
        if self._running:
            return
        self._running = True
        self._auto_task = asyncio.create_task(self._auto_worker())
        logger.info("AvatarService auto mode started")

    async def stop_auto(self) -> None:
        """Stop the background worker."""
        self._running = False

    async def on_tts_event(self, event: TTSPlayEvent) -> None:
        """Enqueue a TTS play event for auto-generation.

        Call this from the TTS on_sentence callback.

        Args:
            event: TTSPlayEvent containing wav_path and sentence text.
        """
        if not self._running:
            return
        if not event.wav_path:
            return
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Avatar event queue full, dropping event %s/%d",
                           event.task_id, event.sentence_index)

    async def _auto_worker(self) -> None:
        """Background worker: pull TTS events and generate avatar videos."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            task_id = f"auto_{event.task_id}_{event.sentence_index}"
            logger.debug("Auto-generating avatar for %s: %s", task_id, event.sentence_text[:40])

            try:
                result = await self.generate(
                    task_id=task_id,
                    audio_path=event.wav_path,
                )
                if result:
                    # Publish result via stream event
                    logger.info("Auto avatar done: %s → %s", task_id, result.output_path)
            except Exception as exc:
                logger.error("Auto avatar generation failed for %s: %s", task_id, exc)

    # ── status / query ─────────────────────────────────────────────

    def status(self) -> dict:
        """Return service status summary."""
        return {
            "running": self._running,
            "pipeline_ready": self.pipeline.ready(),
            "host_image": self.host_image,
            "output_dir": str(self.output_dir),
            "tasks_count": len(self._tasks),
            "results_count": len(self._results),
            "config_fps": self.config.fps,
        }

    def get_result(self, task_id: str) -> Optional[AvatarResult]:
        """Return a completed result by task ID."""
        return self._results.get(task_id)

    def list_results(self, limit: int = 20) -> list[dict]:
        """List recent completed results."""
        items = list(self._results.values())[-limit:]
        return [r.to_dict() for r in items]
