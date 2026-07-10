"""TTS service — async queue-based sentence synthesis for live streaming.

Architecture::

    user text
      │
      ▼
    split_sentences()   ──► [sent1, sent2, ..., sentN]
      │
      ▼
    enqueue_task()
      │
      ▼
    _worker()  ──►  synthesise each sentence sequentially
      │                  │
      │                  ▼
      │            on_sentence(play_event)  ← callback for live playback
      │
      ▼
    TTSPlayEvent  →  stream bus  →  WebSocket / audio player

Usage::

    svc = TTSService(stream=stream_service)
    await svc.speak("贵州茅台今日主力净流入1.2亿，MACD金叉确认，建议轻仓关注。")

    # Listen for playback events:
    async for event in svc.play_events():
        play_audio(event.wav_path)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable, Awaitable

from stockstream.tts.engine import PiperEngine
from stockstream.tts.models import (
    Sentence,
    TTSPlayEvent,
    TTSStatus,
    TTSTask,
    TTSVoice,
)
from stockstream.tts.splitter import split_sentences

logger = logging.getLogger(__name__)

# Callback type: receives TTSPlayEvent for each synthesised sentence
OnSentenceCallback = Callable[[TTSPlayEvent], Awaitable[None]] | None


class TTSService:
    """Async TTS service with queue-based sequential playback.

    Features:
    - Splits long texts into short speakable sentences
    - Synthesises each sentence via Piper (async, non-blocking)
    - Fires play events per sentence for real-time live streaming
    - Task queue: new speaks are queued and played in order
    """

    def __init__(
        self,
        *,
        voice: TTSVoice | None = None,
        on_sentence: OnSentenceCallback = None,
        max_concurrent_tasks: int = 3,
        max_cached_tasks: int = 200,
    ) -> None:
        self.engine = PiperEngine(voice=voice)
        self._on_sentence = on_sentence
        self._task_queue: asyncio.Queue[TTSTask] = asyncio.Queue(maxsize=200)  # 24h: 防止无界增长
        self._play_events: asyncio.Queue[TTSPlayEvent] = asyncio.Queue(maxsize=256)
        self._active_tasks: dict[str, TTSTask] = {}
        self._max_cached_tasks = max_cached_tasks
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_tasks))
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Load Piper engine and start the synthesis worker."""
        # 24h: 幂等性保护 — 防止创建多个 worker task
        if self._running:
            return
        await self.engine.initialize()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("TTSService started (engine=%s)", "ready" if self.engine.available() else "dry-run")

    async def close(self) -> None:
        """Stop the worker and clean up."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None  # 24h: 清除引用，防止僵尸引用混淆
        logger.info("TTSService stopped")

    # ── public API ───────────────────────────────────────────────────

    async def speak(self, text: str, voice: TTSVoice | None = None) -> TTSTask:
        """Submit text for TTS synthesis and return a task handle.

        The text is split into sentences and synthesised sequentially.
        Use ``play_events()`` or the ``on_sentence`` callback to receive
        per-sentence WAV paths for live playback.

        Args:
            text: Raw commentary text (may be multi-sentence, ≤5000 chars).
            voice: Optional per-call voice override.

        Returns:
            A TTSTask tracking synthesis progress.
        """
        task_id = uuid.uuid4().hex[:8]
        sentences = split_sentences(text)

        task = TTSTask(
            task_id=task_id,
            text=text,
            voice=voice or self.engine.voice,
            sentences=sentences,
        )
        self._active_tasks[task_id] = task

        # V3.0: put_nowait + 背压控制，防止队列满时阻塞事件循环
        try:
            self._task_queue.put_nowait(task)
        except asyncio.QueueFull:
            # 队列满时丢弃最旧任务，避免事件循环阻塞
            try:
                old_task = self._task_queue.get_nowait()
                if old_task.task_id in self._active_tasks:
                    del self._active_tasks[old_task.task_id]
                self._task_queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self._task_queue.put_nowait(task)
            logger.warning(
                "TTS task queue full (max=%d): dropped oldest task, new=%s",
                self._task_queue.maxsize, task_id,
            )

        logger.debug(
            "TTS task %s queued: %d sentences, %d chars",
            task_id, len(sentences), len(text),
        )
        return task

    async def speak_and_wait(
        self, text: str, voice: TTSVoice | None = None, timeout: float = 60.0
    ) -> TTSTask:
        """Submit and block until all sentences are synthesised."""
        task = await self.speak(text, voice=voice)
        deadline = asyncio.get_event_loop().time() + timeout
        while task.status not in (TTSStatus.DONE, TTSStatus.FAILED):
            if asyncio.get_event_loop().time() > deadline:
                logger.warning("TTS task %s timed out", task.task_id)
                break
            await asyncio.sleep(0.1)
        return task

    async def text_to_wav(self, text: str, voice: TTSVoice | None = None) -> str:
        """Shortcut: synthesise text directly to a single WAV file.

        Best for short texts (≤100 chars).  For longer texts, use
        ``speak()`` + per-sentence callbacks.
        """
        return await self.engine.text_to_wav(text, voice=voice)

    async def play_events(self) -> TTSPlayEvent:
        """Async iterator helper — await the next play event.

        Usage::

            while True:
                event = await tts.play_events()
                await audio_player.play(event.wav_path)
        """
        return await self._play_events.get()

    def get_task(self, task_id: str) -> TTSTask | None:
        """Return a task by ID, or None."""
        return self._active_tasks.get(task_id)

    def available(self) -> bool:
        """Return True if the TTS engine is ready for synthesis."""
        return self.engine.available()

    # ── internal ────────────────────────────────────────────────────

    def _prune_old_tasks(self) -> None:
        """Remove oldest completed tasks when cache exceeds max."""
        if len(self._active_tasks) <= self._max_cached_tasks:
            return
        # Remove oldest COMPLETED/FINISHED tasks first
        removable = [
            tid for tid, t in self._active_tasks.items()
            if t.status in (TTSStatus.DONE, TTSStatus.FAILED)
        ]
        excess = len(self._active_tasks) - self._max_cached_tasks
        for tid in removable[:excess]:
            del self._active_tasks[tid]

    # ── worker ───────────────────────────────────────────────────────

    async def _worker(self) -> None:
        """Main worker loop: pull tasks from queue and synthesise in order."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            async with self._semaphore:
                await self._process_task(task)

    async def _process_task(self, task: TTSTask) -> None:
        """Synthesise all sentences in a task sequentially."""
        task.status = TTSStatus.SYNTHESIZING
        total = len(task.sentences)
        # Per-task voice override — enables DualVoiceTTS emotion modulation
        task_voice = task.voice

        for sentence in task.sentences:
            if not self._running:
                task.status = TTSStatus.FAILED
                task.error = "Service stopped"
                return

            try:
                wav_path = await self.engine.text_to_wav(
                    sentence.text, voice=task_voice,
                )
            except Exception as exc:
                logger.error("TTS synthesis error for task %s sentence %d: %s",
                             task.task_id, sentence.index, exc)
                wav_path = ""

            if wav_path:
                task.wav_paths.append(wav_path)

            is_last = (sentence.index == total - 1)
            event = TTSPlayEvent(
                task_id=task.task_id,
                sentence_index=sentence.index,
                sentence_text=sentence.text,
                wav_path=wav_path,
                is_last=is_last,
            )

            # Fire callback
            if self._on_sentence:
                try:
                    await self._on_sentence(event)
                except Exception as exc:
                    logger.error("on_sentence callback failed: %s", exc)

            # Push to play-events queue
            if self._play_events.full():
                try:
                    self._play_events.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await self._play_events.put(event)

        task.status = TTSStatus.DONE
        done, _ = task.progress
        logger.debug("TTS task %s done: %d/%d wavs", task.task_id, done, total)
        # Prune old completed tasks to prevent unbounded growth
        self._prune_old_tasks()
