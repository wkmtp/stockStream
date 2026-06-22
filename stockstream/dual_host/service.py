"""Dual-host live service — main orchestrator for the AI finance talk show.

Ties together all sub-engines:
- Dialogue generation from market analysis
- Emotion-driven voice synthesis
- Debate and humor for engagement
- Director scheduling for show pacing
- Audience simulation and live comment fusion
- Avatar action cues

Architecture::

    DirectorAgent ──► DualHostService ◄── MarketService
        │                    │                    │
        ▼                    ▼                    ▼
    Schedule         DialogueGenerator    AnalysisService
                     DebateEngine
                     FinanceHumorEngine
                     AudienceAgent
                     NewsCommentator
                         │
                         ▼
                    DialogueScript
                         │
                         ▼
                    DualVoiceTTS ──► TTSService
                    AvatarActionEngine
                         │
                         ▼
                    Stream Bus (live playback)

Usage::

    from stockstream.dual_host.service import DualHostService
    svc = DualHostService(
        analysis=analysis_svc,
        tts=tts_svc,
        stream=stream_svc,
        market_storage=market_storage,
    )
    await svc.start()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from typing import Any

from stockstream.dual_host.audience_agent import AudienceAgent
from stockstream.dual_host.avatar_action_engine import AvatarActionEngine
from stockstream.dual_host.debate_engine import DebateEngine
from stockstream.dual_host.dialogue_generator import DialogueGenerator
from stockstream.dual_host.director_agent import DirectorAgent
from stockstream.dual_host.dual_voice_tts import DualVoiceTTS
from stockstream.dual_host.emotion_engine import EmotionEngine
from stockstream.dual_host.finance_humor_engine import FinanceHumorEngine
from stockstream.dual_host.live_comment_fusion import LiveCommentFusion
from stockstream.dual_host.models import (
    AvatarAction,
    DialogTurn,
    DialogueScript,
    DualHostConfig,
    Emotion,
    ScheduleSlot,
    ShowSegmentType,
    Speaker,
)
from stockstream.dual_host.news_commentator import NewsCommentator
from stockstream.dual_host.storytelling_engine import StorytellingEngine
from stockstream.market.storage import MarketSQLiteStorage

logger = logging.getLogger(__name__)


class DualHostService:
    """Main service for the AI finance talk show with dual digital hosts."""

    def __init__(
        self,
        *,
        analysis: Any = None,           # AnalysisService
        tts: Any = None,                # TTSService
        stream: Any = None,             # StreamService
        danmu: Any = None,              # DanmuService
        market_storage: MarketSQLiteStorage | None = None,
        config: DualHostConfig | None = None,
    ) -> None:
        self.analysis = analysis
        self.tts = tts
        self.stream = stream
        self.danmu = danmu
        self.storage = market_storage or MarketSQLiteStorage()
        self.config = config or DualHostConfig()

        # ── Engines ─────────────────────────────────────────────
        self.emotion_engine = EmotionEngine()
        self.storytelling = StorytellingEngine()
        self.dialogue_gen = DialogueGenerator(
            emotion_engine=self.emotion_engine,
            storytelling_engine=self.storytelling,
        )
        self.debate_engine = DebateEngine(emotion_engine=self.emotion_engine)
        self.humor_engine = FinanceHumorEngine()
        self.news_commentator = NewsCommentator(emotion_engine=self.emotion_engine)
        self.audience_agent = AudienceAgent(emotion_engine=self.emotion_engine)
        self.comment_fusion = LiveCommentFusion(audience_agent=self.audience_agent)
        self.director = DirectorAgent(config=self.config)
        self.action_engine = AvatarActionEngine()

        # TTS — pass dual-model config for true male/female voice separation
        if self.tts is not None:
            from stockstream.tts.models import TTSVoice
            male_voice = TTSVoice(
                name=self.config.male_voice,
                model_path=self.config.male_model_path,
                length_scale=1.05,
                noise_scale=0.65,
                noise_w=0.78,
                sentence_silence=0.28,
            )
            female_voice = TTSVoice(
                name=self.config.female_voice,
                model_path=self.config.female_model_path,
                length_scale=0.92,
                noise_scale=0.72,
                noise_w=0.72,
                sentence_silence=0.16,
            )
            self.dual_tts = DualVoiceTTS(
                tts_svc=self.tts,
                male_voice=male_voice,
                female_voice=female_voice,
                output_dir=self.config.tts_output_dir,
            )
        else:
            self.dual_tts = None

        # ── State ───────────────────────────────────────────────
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._script_history: list[DialogueScript] = []
        self._script_history_max: int = 200  # 24h: 防止无界增长
        self._current_watch_list: list[str] = []
        self._segment_tasks: dict[str, asyncio.Task] = {}
        self._started_at: float = 0.0

        # Register director callback
        self.director.on_segment(self._handle_segment)

    # ── lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dual-host live show."""
        self._running = True
        self._started_at = time.monotonic()

        # Load watch list
        self._current_watch_list = await self._load_watch_list()

        # Start director scheduling
        await self.director.start()

        logger.info("DualHostService started (watch_list=%d stocks)", len(self._current_watch_list))

    async def stop(self) -> None:
        """Stop the live show."""
        self._running = False
        await self.director.stop()

        # Cancel any in-progress segment tasks
        for tid, task in list(self._segment_tasks.items()):
            if not task.done():
                task.cancel()
        self._segment_tasks.clear()

        logger.info("DualHostService stopped (scripts=%d)", len(self._script_history))

    # ── director callback ───────────────────────────────────────

    async def _handle_segment(
        self, segment_type: ShowSegmentType, meta: dict
    ) -> DialogueScript | None:
        """Generate and process a segment based on director schedule."""
        script: DialogueScript | None = None

        try:
            if segment_type == ShowSegmentType.OPENING:
                script = self._generate_opening()
            elif segment_type == ShowSegmentType.STOCK_ANALYSIS:
                script = await self._generate_stock_analysis()
            elif segment_type == ShowSegmentType.HOT_SECTOR:
                script = await self._generate_sector_segment()
            elif segment_type == ShowSegmentType.NEWS_COMMENTARY:
                script = await self.news_commentator.get_commentary()
            elif segment_type == ShowSegmentType.FINANCE_FUN:
                script = self._generate_humor_segment()
            elif segment_type == ShowSegmentType.AUDIENCE_QA:
                script = await self._generate_qa_segment()
            elif segment_type == ShowSegmentType.MARKET_REVIEW:
                script = await self._generate_market_review()
            elif segment_type == ShowSegmentType.CLOSING:
                script = self._generate_closing()
            else:
                return None

            if script:
                self._script_history.append(script)
                # 24h: 限制历史记录最多 200 条，超出时截断最早的一半
                if len(self._script_history) > self._script_history_max:
                    self._script_history = self._script_history[-100:]
                await self._deliver_script(script)

        except Exception as exc:
            logger.error("Segment generation failed for %s: %s", segment_type, exc)

        return script

    # ── segment generators ──────────────────────────────────────

    def _generate_opening(self) -> DialogueScript:
        """Generate show opening dialogue."""
        turns: list[DialogTurn] = []
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="各位观众朋友们大家好！欢迎来到今天的财经相声直播间！我是你们的新人主播小财妹~",
            emotion=Emotion.HAPPY,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text="大家好，我是老股民老张。今天又和大家见面了，咱们一起看看今天市场有什么新鲜事。",
            emotion=Emotion.NEUTRAL,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="老张，昨天晚上我看美股那边又跌了，今天A股会不会受影响啊？",
            emotion=Emotion.THINKING,
            is_question=True,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text="美股的调整对A股会有一定的情绪影响，不过港股和A股现在有自己的节奏，"
                  "关键还是看内资的态度。我们先看看集合竞价的情况，再来分析今天的策略。",
            emotion=Emotion.NEUTRAL,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="好的，那咱们话不多说，开始今天的节目！",
            emotion=Emotion.HAPPY,
        ))

        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.OPENING,
            topic="opening",
            turns=turns,
        )

    async def _generate_stock_analysis(self) -> DialogueScript | None:
        """Generate analysis for a stock on the watch list."""
        if not self._current_watch_list:
            return None

        # Pick next stock (round-robin)
        stock = self._current_watch_list[len(self._script_history) % len(self._current_watch_list)]

        # Get analysis context
        context = {}
        if self.analysis:
            try:
                result = await self.analysis.analyze(stock, mode="stock")
                context = result.context if hasattr(result, 'context') else {}
            except Exception as exc:
                logger.warning("Analysis failed for %s: %s", stock, exc)

        if not context:
            context = {"symbol": stock, "name": stock, "query": stock}

        # Generate dialogue
        script = self.dialogue_gen.generate_stock_dialogue(
            context,
            min_turns=self.config.dialogue_turns_per_stock[0],
            max_turns=self.config.dialogue_turns_per_stock[1],
        )

        # Optionally append debate
        if self.config.enable_debate and random.random() > 0.6:
            debate_turns = self.debate_engine.generate(context)
            # Only add debate if it fits within total turns
            if len(script.turns) + len(debate_turns) <= 10:
                script.turns.extend(debate_turns)

        return script

    async def _generate_sector_segment(self) -> DialogueScript | None:
        """Generate sector analysis segment."""
        context = {"name": "机器人概念", "query": "机器人概念"}
        if self.analysis:
            try:
                result = await self.analysis.analyze("机器人概念", mode="sector")
                context.update(result.context if hasattr(result, 'context') else {})
            except Exception as exc:
                logger.warning("DualHost: sector analysis failed, using defaults — %s", exc)
        return self.dialogue_gen.generate_sector_dialogue(context)

    def _generate_humor_segment(self) -> DialogueScript:
        """Generate a humor break segment."""
        turns = self.humor_engine.generate_dialogue()
        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.FINANCE_FUN,
            topic="humor",
            turns=turns,
        )

    async def _generate_qa_segment(self) -> DialogueScript | None:
        """Generate audience Q&A segment."""
        question = self.comment_fusion.get_next(self._current_watch_list)
        if not question:
            return None

        # Try to get stock context
        stock_contexts = {}
        return self.audience_agent.generate_qa_dialogue(question, stock_contexts)

    async def _generate_market_review(self) -> DialogueScript | None:
        """Generate market review segment."""
        context = {}
        if self.analysis:
            try:
                result = await self.analysis.analyze_market()
                context = result.context if hasattr(result, 'context') else {}
            except Exception as exc:
                logger.warning("DualHost: market review analysis failed, using fallback — %s", exc)
        if not context:
            context = {"query": "大盘", "up_count": 1200, "down_count": 800, "avg_change_pct": 0.5}
        return self.dialogue_gen.generate_market_review(context)

    def _generate_closing(self) -> DialogueScript:
        """Generate show closing."""
        turns: list[DialogTurn] = []
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="今天的节目就到这里了，感谢大家的陪伴！",
            emotion=Emotion.HAPPY,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.MALE,
            text="记住，投资是一场马拉松，不是百米冲刺。控制好风险，保持好心态，我们下次再见。",
            emotion=Emotion.SERIOUS,
        ))
        turns.append(DialogTurn(
            speaker=Speaker.FEMALE,
            text="大家有什么想聊的话题欢迎在弹幕区告诉我们！明天同一时间不见不散~拜拜！",
            emotion=Emotion.HAPPY,
        ))
        return DialogueScript(
            segment_id=uuid.uuid4().hex[:8],
            segment_type=ShowSegmentType.CLOSING,
            topic="closing",
            turns=turns,
        )

    # ── delivery ────────────────────────────────────────────────

    async def _deliver_script(self, script: DialogueScript) -> None:
        """Deliver a dialogue script to TTS synthesis and stream publishing."""
        if not script.turns:
            return

        logger.info(
            "Delivering %s: [%s] %d turns",
            script.segment_type.value, script.topic, len(script.turns),
        )

        # Generate avatar actions
        actions = self.action_engine.generate_action_script(script.turns)

        # Publish script to stream bus for live consumption
        if self.stream:
            await self.stream.publish({
                "type": "dual_host.script",
                "segment_id": script.segment_id,
                "segment_type": script.segment_type.value,
                "topic": script.topic,
                "turns": script.to_dict(),
                "actions": actions,
            })

        # Publish each turn individually for subtitle/sync
        for turn in script.turns:
            if self.stream:
                await self.stream.publish({
                    "type": "dual_host.turn",
                    "segment_id": script.segment_id,
                    "speaker": turn.speaker.value,
                    "text": turn.text,
                    "emotion": turn.emotion.value,
                    "action": turn.action.value,
                    "duration_sec": turn.duration_sec,
                })

            # Send as danmu-style overlay for viewers
            if self.danmu:
                label = "老张" if turn.speaker == Speaker.MALE else "小财妹"
                await self.danmu.send(f"[{label}] {turn.text[:60]}...")

        # TTS synthesis (if enabled)
        if self.dual_tts and self.tts:
            task_id = f"dh_{script.segment_id}"
            # 24h: 追踪 fire-and-forget task，以便在 stop() 时正确 cancel
            t = asyncio.create_task(self._synthesize_script(task_id, script))
            self._segment_tasks[task_id] = t

    async def _synthesize_script(self, task_id: str, script: DialogueScript) -> None:
        """Background TTS synthesis for a dialogue script.

        After synthesis, publishes ``dual_host.audio`` events to the stream bus
        so that frontend / compositor can play back the generated WAV files.
        """
        try:
            results = await self.dual_tts.speak_script(script.turns)
            logger.debug("TTS done for %s: %d turns synthesised", task_id, len(results))

            # Publish audio events for each turn, linked to the script
            for i, result in enumerate(results):
                if not result.get("wav_paths"):
                    continue
                if self.stream:
                    await self.stream.publish({
                        "type": "dual_host.audio",
                        "segment_id": script.segment_id,
                        "segment_type": script.segment_type.value,
                        "turn_index": i,
                        "speaker": result.get("speaker"),
                        "emotion": result.get("emotion"),
                        "text": result.get("text"),
                        "wav_paths": result.get("wav_paths"),
                        "task_id": result.get("task_id"),
                        "voice_name": result.get("voice_name"),
                        "model_path": result.get("model_path"),
                        "length_scale": result.get("length_scale"),
                        "noise_scale": result.get("noise_scale"),
                    })
        except asyncio.CancelledError:
            logger.debug("TTS cancelled for %s", task_id)
        except Exception as exc:
            logger.error("TTS synthesis failed for %s: %s", task_id, exc)
        finally:
            # 24h: 清理已完成/已取消的 task 引用，防止内存泄漏
            self._segment_tasks.pop(task_id, None)

    # ── public API ──────────────────────────────────────────────

    async def request_segment(self, segment_type: ShowSegmentType) -> DialogueScript | None:
        """Manually trigger a segment (e.g., for audience interaction)."""
        return await self._handle_segment(segment_type, {"manual": True})

    def push_danmu(self, username: str, message: str) -> None:
        """Feed a real viewer danmu into the system."""
        self.comment_fusion.push_real(username, message)

    def get_stats(self) -> dict[str, Any]:
        """Return current show statistics."""
        return {
            "running": self._running,
            "elapsed_sec": time.monotonic() - self._started_at if self._started_at else 0,
            "scripts_generated": len(self._script_history),
            "watch_list": self._current_watch_list,
            "last_scripts": [
                {"type": s.segment_type.value, "topic": s.topic, "turns": len(s.turns)}
                for s in self._script_history[-5:]
            ],
            "director_rundown": self.director.get_rundown(),
        }

    # ── helpers ─────────────────────────────────────────────────

    async def _load_watch_list(self) -> list[str]:
        """Load watch list from storage or config defaults."""
        from stockstream.core.config import get_settings
        settings = get_settings()

        symbols_str = settings.market_symbols
        if symbols_str:
            return [s.strip() for s in symbols_str.split(",") if s.strip()]

        # Default: top-volume stocks from cache
        try:
            rows = await self.storage.latest("spot", limit=20)
            if rows:
                return [
                    str(r.get("payload", {}).get("代码", ""))
                    for r in rows
                    if r.get("payload", {}).get("代码")
                ][:10]
        except Exception:
            pass

        # Hard fallback
        return ["000001", "600519", "000858", "300750", "002594",
                "601318", "600036", "000002", "600276", "601012"]
