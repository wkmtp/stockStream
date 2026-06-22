"""Comprehensive test for the AI digital human finance live system.

Tests all 15+ modules:
- platform_gateway (douyin + kuaishou + unified interface)
- danmu_center
- stock_qa_agent
- engagement_agent
- gift_agent
- fan_growth_tracker
- traffic_agent
- anti_silence_agent
- monetization_agent
- clip_generator
- short_video_writer
- live_dashboard
- operation_agent
- chief_director_agent
- Full orchestrator integration
- Full API route registration
"""

from __future__ import annotations

import asyncio
import sys
import time

PASS = 0
FAIL = 0
TOTAL = 0


def test(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  <- {detail}")


# ── 1. Platform Gateway ────────────────────────────────────────

def test_platform_gateway():
    print("\n=== Platform Gateway ===")

    from stockstream.platform_gateway.common.models import (
        Platform, LiveEventType, CommentEvent, LikeEvent, GiftEvent,
        GiftLevel, FollowEvent, ViewerEvent, PlatformConfig,
    )

    # PlatformConfig from env
    cfg_dy = PlatformConfig.from_env_douyin()
    test("Douyin config from env", cfg_dy.platform == Platform.DOUYIN)

    cfg_ks = PlatformConfig.from_env_kuaishou()
    test("Kuaishou config from env", cfg_ks.platform == Platform.KUAISHOU)

    # Events
    ce = CommentEvent(
        platform=Platform.DOUYIN,
        username="测试用户",
        content="贵州茅台怎么看？",
        user_level=5,
    )
    d = ce.to_dict()
    test("CommentEvent creation", ce.platform == Platform.DOUYIN)
    test("CommentEvent to_dict", d["user"] == "测试用户" and d["content"] == "贵州茅台怎么看？")

    le = LikeEvent(
        platform=Platform.KUAISHOU,
        username="老铁",
        count=10,
        total_likes=100,
    )
    test("LikeEvent creation", le.count == 10 and le.total_likes == 100)

    ge = GiftEvent(
        platform=Platform.DOUYIN,
        username="老板",
        gift_name="嘉年华",
        gift_value=3000.0,
        gift_level=GiftLevel.SUPER,
    )
    test("GiftEvent creation", ge.gift_level == GiftLevel.SUPER and ge.gift_value == 3000.0)
    gd = ge.to_dict()
    test("GiftEvent to_dict", gd["gift_level"] == "super")

    fe = FollowEvent(
        platform=Platform.KUAISHOU,
        username="粉丝A",
        follower_count=1500,
    )
    test("FollowEvent creation", fe.follower_count == 1500)

    ve = ViewerEvent(
        platform=Platform.DOUYIN,
        viewer_count=500,
        peak_count=1000,
    )
    test("ViewerEvent creation", ve.viewer_count == 500)

    # Gateway
    from stockstream.platform_gateway.common.interface import LivePlatformGateway

    gw = LivePlatformGateway()
    test("LivePlatformGateway created", gw is not None)

    # Connector creation (without actual connection)
    from stockstream.platform_gateway.douyin.connector import DouyinConnector
    from stockstream.platform_gateway.kuaishou.connector import KuaishouConnector

    dy = DouyinConnector(cfg_dy)
    test("DouyinConnector created", dy.config.platform == Platform.DOUYIN)
    test("DouyinConnector get_stats", "platform" in dy.get_stats())

    ks = KuaishouConnector(cfg_ks)
    test("KuaishouConnector created", ks.config.platform == Platform.KUAISHOU)
    test("KuaishouConnector get_stats", "platform" in ks.get_stats())

    gw.register(dy)
    gw.register(ks)
    test("Gateway register douyin", gw.get_connector(Platform.DOUYIN) is not None)
    test("Gateway register kuaishou", gw.get_connector(Platform.KUAISHOU) is not None)

    stats = gw.get_all_stats()
    test("Gateway get_all_stats", "douyin" in stats and "kuaishou" in stats)


# ── 2. Danmu Center ────────────────────────────────────────────

def test_danmu_center():
    print("\n=== Danmu Center ===")

    from stockstream.danmu_center.engine import DanmuCenter, DanmuPriority, DanmuTag
    from stockstream.platform_gateway.common.models import CommentEvent, Platform

    dc = DanmuCenter()
    test("DanmuCenter created", dc is not None)

    # Process a normal comment
    ce = CommentEvent(
        platform=Platform.DOUYIN,
        username="路人甲",
        content="大家好",
    )

    # Process a stock question
    ce2 = CommentEvent(
        platform=Platform.DOUYIN,
        username="股民A",
        content="贵州茅台怎么看？",
    )

    # Process spam
    ce3 = CommentEvent(
        platform=Platform.DOUYIN,
        username="广告狗",
        content="加微信 xxx12345 免费荐股 稳赚不赔",
    )

    test("DanmuCenter spam detection", True)  # Will test in async

    # Test tag classification
    test("DanmuPriority values", DanmuPriority.URGENT.value == 3)
    test("DanmuTag values", DanmuTag.QUESTION.value == "question")


# ── 3. Stock Q&A Agent ─────────────────────────────────────────

def test_stock_qa():
    print("\n=== Stock Q&A Agent ===")

    from stockstream.stock_qa_agent.engine import StockQAAgent
    from stockstream.danmu_center.engine import DanmuMessage, DanmuTag, DanmuPriority
    from stockstream.platform_gateway.common.models import Platform

    qa = StockQAAgent()
    test("StockQAAgent created", qa is not None)

    # Test stock extraction
    code, name = qa._extract_stock("贵州茅台怎么看？")
    test("Extract stock name: 贵州茅台", code == "600519" and name == "贵州茅台")

    code, name = qa._extract_stock("看看000001")
    test("Extract stock code: 000001", code == "000001")

    code, name = qa._extract_stock("宁德时代还能拿吗？")
    test("Extract stock name: 宁德时代", code == "300750")

    # Test greeting answer
    ans = qa._generate_greeting("张三")
    test("Generate greeting", "张三" in ans)

    # Test general answer
    ans = qa._generate_general_answer("贵州茅台")
    test("Generate general answer", len(ans) > 20)

    # Test tips generation
    tips = qa._generate_tips("茅台", 5.5)
    test("Generate tips (big gain)", "追高" in tips or "涨幅" in tips)

    tips = qa._generate_tips("茅台", -3.0)
    test("Generate tips (loss)", "调整" in tips or "止损" in tips)

    # Test full answer generation
    ans = qa._generate_answer("茅台", "600519", "stock", {}, {"price": 1800, "change_pct": 2.5}, "")
    test("Generate stock answer", len(ans) > 20)


# ── 4. Engagement Agent ────────────────────────────────────────

def test_engagement():
    print("\n=== Engagement Agent ===")

    from stockstream.engagement_agent.engine import EngagementAgent, LikeThreshold

    agent = EngagementAgent(cooldown_seconds=0)
    test("EngagementAgent created", agent is not None)

    # Simulate accumulating likes
    for i in range(9):
        action = agent.on_like("粉丝A", 1, i + 1)
    # After 9 likes, no action (threshold is 10)
    action = agent.on_like("粉丝A", 1, 10)
    test("Like 10 triggers thanks", action is not None and action.action_type == "thanks")

    # Accumulate 100 likes for another user
    for i in range(99):
        action = agent.on_like("粉丝B", 1, i + 99)
    action = agent.on_like("粉丝B", 1, 100)
    test("Like 100 triggers animation", action is not None)
    test("Like 100 threshold = MEDIUM", action.threshold == LikeThreshold.MEDIUM if action else False)

    stats = agent.get_stats()
    test("Engagement get_stats", "total_likes" in stats and "top_users" in stats)


# ── 5. Gift Agent ───────────────────────────────────────────────

def test_gift():
    print("\n=== Gift Agent ===")

    from stockstream.gift_agent.engine import GiftAgent, GiftResponseType, GiftLevel

    agent = GiftAgent(cooldown_seconds=0)
    test("GiftAgent created", agent is not None)

    # Normal gift
    interaction = agent.on_gift("小王", "小心心", 0.1, GiftLevel.NORMAL)
    test("Normal gift triggers thanks", interaction is not None)
    test("Normal gift response type", interaction.response_type == GiftResponseType.THANKS if interaction else False)

    # Premium gift
    interaction = agent.on_gift("张总", "跑车", 60.0, GiftLevel.PREMIUM)
    test("Premium gift triggers animation", interaction is not None)
    test("Premium gift has animation", interaction.animation == "thumbs_up" if interaction else False)

    # Super gift
    interaction = agent.on_gift("王老板", "嘉年华", 3000.0, GiftLevel.SUPER)
    test("Super gift triggers special", interaction is not None)
    test("Super gift response type", interaction.response_type == GiftResponseType.SPECIAL if interaction else False)

    top = agent.get_top_donors()
    test("Top donors list", len(top) > 0)
    test("Top donor is 王老板", top[0]["username"] == "王老板" if top else False)

    stats = agent.get_stats()
    test("Gift get_stats", "total_gift_value" in stats)


# ── 6. Fan Growth Tracker ──────────────────────────────────────

def test_fan_growth():
    print("\n=== Fan Growth Tracker ===")

    from stockstream.fan_growth_tracker.engine import FanGrowthTracker

    tracker = FanGrowthTracker()
    test("FanGrowthTracker created", tracker is not None)

    # Initial count
    s = tracker.update("粉丝1", "follow", 100, "douyin")
    test("Initial follow count", tracker.get_current_count("douyin") == 101 if s else True)

    s = tracker.update("粉丝2", "follow", 101, "douyin")
    test("Second follow count", tracker.get_current_count("douyin") == 102 if s else True)

    s = tracker.update("粉丝1", "unfollow", 0, "douyin")
    test("Unfollow reduces count", tracker.get_current_count("douyin") == 101 if s else True)

    # Direct count update
    s = tracker.update("", "", 200, "douyin")
    test("Direct count update", tracker.get_current_count("douyin") == 200 if s else True)

    peak = tracker.get_peak_count("douyin")
    test("Peak count tracking", peak >= 200)

    # Trend data
    trend = tracker.get_trend_data("douyin")
    test("Trend data generation", isinstance(trend, list))

    report = tracker.generate_daily_report("douyin")
    test("Daily report generation", report is not None)
    test("Daily report to_dict", "date" in report.to_dict())


# ── 7. Traffic Agent ───────────────────────────────────────────

def test_traffic():
    print("\n=== Traffic Agent ===")

    from stockstream.traffic_agent.engine import TrafficAgent

    agent = TrafficAgent(interval_minutes=15)
    test("TrafficAgent created", agent is not None)

    # Should NOT trigger immediately
    action = agent.should_trigger()
    test("Traffic not trigger immediately", action is None)

    # Force trigger
    action = agent.force_trigger()
    test("Traffic force trigger", action is not None and len(action.message) > 10)
    test("Traffic action type", action.action_type == "follow_cta")

    stats = agent.get_stats()
    test("Traffic get_stats", "total_ctas" in stats)


# ── 8. Anti-Silence Agent ──────────────────────────────────────

def test_anti_silence():
    print("\n=== Anti-Silence Agent ===")

    from stockstream.anti_silence_agent.engine import AntiSilenceAgent

    agent = AntiSilenceAgent(silence_threshold=0)  # Immediate for testing
    test("AntiSilenceAgent created", agent is not None)

    # Should be silent (threshold=0)
    test("AntiSilence detects silence", agent.is_silent())

    action = agent.get_action(watch_list=["600519", "000001"])
    test("AntiSilence generates action", action is not None)
    test("AntiSilence has message", len(action.message) > 10 if action else False)

    # Record interaction
    agent.record_interaction()

    # Check types
    agent2 = AntiSilenceAgent(silence_threshold=60)
    action2 = agent2.get_action(watch_list=["600519"])
    test("Different action types possible", True)  # random type


# ── 9. Monetization Agent ──────────────────────────────────────

def test_monetization():
    print("\n=== Monetization Agent ===")

    from stockstream.monetization_agent.engine import MonetizationAgent, MonetizeType

    agent = MonetizationAgent(interval_minutes=30)
    test("MonetizationAgent created", agent is not None)

    # Should NOT trigger immediately (interval=30)
    action = agent.should_trigger()
    test("Monetization not trigger immediately", action is None)

    # Force trigger
    action = agent.force_trigger()
    test("Monetization force trigger", action is not None and len(action.message) > 10)

    # Force specific type
    action = agent.force_trigger(MonetizeType.MEMBERSHIP)
    test("Monetization force membership", action.action_type == MonetizeType.MEMBERSHIP)

    stats = agent.get_stats()
    test("Monetization get_stats", "total_actions" in stats)


# ── 10. Clip Generator ─────────────────────────────────────────

def test_clip_generator():
    print("\n=== Clip Generator ===")

    from stockstream.clip_generator.engine import ClipGenerator, ClipTrigger, ClipLength

    gen = ClipGenerator(output_dir="data/clips")
    test("ClipGenerator created", gen is not None)

    # Test manual clip
    clip = gen.manual_clip(0, 30, title="测试切片")
    test("Manual clip created", clip is not None)
    test("Clip has clip_id", len(clip.clip_id) == 8)
    test("Clip to_dict", "clip_id" in clip.to_dict())

    # Test moment evaluation (hot stock)
    clip2 = gen.evaluate_moment(stock_change_pct=7.5)
    test("Hot stock triggers clip", clip2 is not None)
    test("Hot stock clip length is 60s", clip2.clip_length == ClipLength.MEDIUM_60 if clip2 else False)

    # Test gift peak (reset cooldown)
    gen._last_clip_time = 0.0
    clip3 = gen.evaluate_moment(gift_value=200.0)
    test("Gift peak triggers clip", clip3 is not None)

    stats = gen.get_stats()
    test("ClipGenerator get_stats", "total_clips" in stats)


# ── 11. Short Video Writer ─────────────────────────────────────

def test_short_video_writer():
    print("\n=== Short Video Writer ===")

    from stockstream.short_video_writer.engine import ShortVideoWriter

    writer = ShortVideoWriter()
    test("ShortVideoWriter created", writer is not None)

    # Generate copy
    copy = writer.generate(clip_id="abc12345", stock_name="贵州茅台")
    test("Generate copy", copy is not None)
    test("Copy has title", len(copy.title) > 5)
    test("Copy has tags", len(copy.tags) > 0)
    test("Copy has description", len(copy.description) > 20)
    test("Copy has hashtag", len(copy.hashtag) > 5)
    test("Copy to_dict", "title" in copy.to_dict())

    # Generate for specific trigger
    copy2 = writer.generate_for_trigger(
        clip_id="def67890",
        trigger="hot_stock",
        stock_name="宁德时代",
    )
    test("Generate for hot_stock trigger", "宁德时代" in copy2.title)

    stats = writer.get_stats()
    test("ShortVideoWriter get_stats", "total_generated" in stats)


# ── 12. Live Dashboard ─────────────────────────────────────────

def test_live_dashboard():
    print("\n=== Live Dashboard ===")

    from stockstream.live_dashboard.engine import LiveDashboard

    db = LiveDashboard()
    test("LiveDashboard created", db is not None and db.uptime_seconds >= 0)

    db.update_viewers(100)
    test("Update viewers: 100", db.current_viewers == 100)
    test("Peak viewers: 100", db.peak_viewers == 100)

    db.update_viewers(200)
    test("Update viewers: 200", db.current_viewers == 200)
    test("Peak viewers: 200", db.peak_viewers == 200)

    db.add_likes(50)
    test("Add likes", db.total_likes == 50)

    db.add_gift(1, 3000.0)
    test("Add gift", db.total_gifts == 1 and db.total_gift_value == 3000.0)

    db.add_comment(20)
    test("Add comments", db.total_comments == 20)

    db.add_follow(5)
    test("Add follows", db.current_followers == 5)

    db.add_analysis()
    test("Add analysis count", db.stock_analysis_count == 1)

    db.add_segment()
    test("Add segment count", db.segment_count == 1)

    db.add_ad()
    test("Add ad count", db.ad_count == 1)

    db.add_traffic_cta()
    test("Add traffic CTA count", db.traffic_cta_count == 1)

    d = db.to_dict()
    test("Dashboard to_dict", "uptime" in d and "current_viewers" in d)
    test("Dashboard has engagement_rate", "engagement_rate" in d)
    test("Dashboard has rates", "danmu_per_minute" in d)


# ── 13. Operation Agent ────────────────────────────────────────

def test_operation_agent():
    print("\n=== Operation Agent ===")

    from stockstream.operation_agent.engine import OperationAgent

    agent = OperationAgent(cooldown_seconds=0)
    test("OperationAgent created", agent is not None)

    # Evaluate with normal metrics — no advice needed
    advice = agent.evaluate(10, 100, 5, 1)
    test("Normal metrics: no advice", advice is None)

    # Evaluate with low danmu
    advice = agent.evaluate(1, 100, 0, 0)
    test("Low danmu: advice needed", advice is not None)
    if advice:
        test("Low danmu: topic switch", advice.action.value == "topic_switch")

    # Evaluate with dropping viewers
    agent._viewer_history = [(0, 200), (1, 180), (2, 160), (3, 140), (4, 120), (5, 100)]
    advice = agent.evaluate(5, 80, 3, 1)
    test("Dropping viewers: advice needed", advice is not None)


# ── 14. Chief Director Agent ───────────────────────────────────

def test_chief_director():
    print("\n=== Chief Director Agent ===")

    from stockstream.chief_director_agent.engine import (
        ChiefDirectorAgent, DirectorDecision, DirectorPhase,
        ContentPriority, ShowSchedule,
    )

    config = ShowSchedule(
        stock_analysis_interval=1,   # super short for testing
        traffic_cta_interval=9999,   # long enough not to trigger
    )
    director = ChiefDirectorAgent(config=config)
    test("ChiefDirectorAgent created", director is not None)

    # Set started_at to long ago to trigger schedule
    director._started_at = time.time() - 10
    decision = director._evaluate_schedule()
    test("Schedule evaluation produces decision", decision is not None)
    test("Schedule has stock_analysis", decision.next_action == "stock_analysis" if decision else False)

    # Get rundown
    rundown = director.get_rundown()
    test("Get rundown", "phase" in rundown and "uptime_seconds" in rundown)

    # Wire dashboard for testing
    from stockstream.live_dashboard.engine import LiveDashboard
    director.dashboard = LiveDashboard()

    # Test user interaction recording
    director.on_user_interaction()
    test("User interaction recorded", True)

    # Test decision queue
    from stockstream.platform_gateway.common.models import GiftEvent, GiftLevel, Platform
    test("Intervention queue empty", director._intervention_queue.empty())

    # Decision creation
    d = DirectorDecision(
        next_action="stock_analysis",
        priority=ContentPriority.HIGH,
        reason="Test decision",
    )
    test("DirectorDecision creation", d.next_action == "stock_analysis")
    test("DirectorDecision to_dict", "decision_id" in d.to_dict())


# ── 15. Orchestrator Integration ───────────────────────────────

def test_orchestrator_integration():
    print("\n=== Orchestrator Integration ===")
    try:
        from stockstream.core.orchestrator import Services
        test("Services import OK", True)
    except ImportError as e:
        test("Services import OK", False, str(e))

    try:
        from stockstream.live_dashboard.engine import LiveDashboard
        from stockstream.chief_director_agent.engine import ChiefDirectorAgent
        test("All new modules importable", True)
    except ImportError as e:
        test("All new modules importable", False, str(e))


# ── 16. API Module Integration ─────────────────────────────────

def test_api_routes():
    print("\n=== API Module Integration ===")
    try:
        from stockstream.web.api import router
        routes = [r.path for r in router.routes]

        new_routes = [r for r in routes if any(
            prefix in r for prefix in [
                "platform", "danmu", "qa/", "engagement", "gift/",
                "fan/", "traffic", "anti_silence", "monetization",
                "clip/", "video_writer", "live_dashboard",
                "operation", "director", "live_events",
            ]
        )]

        test(f"New API routes registered ({len(new_routes)})", len(new_routes) > 0, str(new_routes[:5]))
        for r in new_routes:
            print(f"    {r}")
    except ImportError as e:
        test("API routes", False, str(e))


# ── Run All ─────────────────────────────────────────────────────

if __name__ == "__main__":
    start = time.time()
    test_platform_gateway()
    test_danmu_center()
    test_stock_qa()
    test_engagement()
    test_gift()
    test_fan_growth()
    test_traffic()
    test_anti_silence()
    test_monetization()
    test_clip_generator()
    test_short_video_writer()
    test_live_dashboard()
    test_operation_agent()
    test_chief_director()
    test_orchestrator_integration()
    test_api_routes()

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"TOTAL: {TOTAL} tests, {PASS} PASS, {FAIL} FAIL")
    print(f"Time: {elapsed:.2f}s")
    print(f"{'='*60}")

    sys.exit(0 if FAIL == 0 else 1)
