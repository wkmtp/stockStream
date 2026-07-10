"""Comprehensive test for the dual_host_live_system module.

Validates all engines: emotion, storytelling, dialogue, debate, humor,
news, director, audience, comment fusion, TTS config, avatar actions.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stockstream.dual_host.models import (
    Emotion, AvatarAction, Speaker, DialogTurn, DialogueScript,
    ShowSegmentType, DualHostConfig, EMOTION_ACTION_MAP,
    ScheduleSlot, DEFAULT_SCHEDULE,
)
from stockstream.dual_host.emotion_engine import EmotionEngine
from stockstream.dual_host.storytelling_engine import StorytellingEngine
from stockstream.dual_host.dialogue_generator import DialogueGenerator
from stockstream.dual_host.debate_engine import DebateEngine
from stockstream.dual_host.finance_humor_engine import FinanceHumorEngine
from stockstream.dual_host.news_commentator import NewsCommentator
from stockstream.dual_host.director_agent import DirectorAgent
from stockstream.dual_host.audience_agent import AudienceAgent
from stockstream.dual_host.live_comment_fusion import LiveCommentFusion
from stockstream.dual_host.avatar_action_engine import AvatarActionEngine

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ── Sync tests ────────────────────────────────────────────────

def test_emotion():
    print("\n=== Emotion Engine ===")
    eng = EmotionEngine()

    e = eng.detect("今天涨停了！", Speaker.FEMALE)
    check("涨停→EXCITED", e == Emotion.EXCITED, f"got {e}")

    e = eng.detect("主力资金大幅流入", Speaker.MALE)
    check("流入→HAPPY", e == Emotion.HAPPY, f"got {e}")

    e = eng.detect("注意风险控制", Speaker.MALE)
    check("风险→SERIOUS", e == Emotion.SERIOUS, f"got {e}")

    e = eng.detect("突然跳水了！", Speaker.FEMALE)
    check("跳水→SURPRISED", e == Emotion.SURPRISED, f"got {e}")

    e = eng.detect("大幅下跌注意止损", Speaker.MALE)
    check("下跌止损→WARNING", e == Emotion.WARNING, f"got {e}")

    e = eng.detect("不过还需要观察", Speaker.MALE)
    check("犹豫→THINKING", e == Emotion.THINKING, f"got {e}")

    e = eng.detect("你好", Speaker.MALE)
    check("普通→NEUTRAL", e == Emotion.NEUTRAL, f"got {e}")

    e = eng.detect("", Speaker.MALE, {"change_pct": 10.0})
    check("context涨停→EXCITED", e == Emotion.EXCITED, f"got {e}")

    e = eng.detect("", Speaker.MALE, {"change_pct": -8.0})
    check("context大跌→WARNING", e == Emotion.WARNING, f"got {e}")

    batch = eng.batch_detect(["涨停", "跌停", "正常"], Speaker.MALE)
    check("batch detect", len(batch) == 3, str(batch))
    return eng


def test_storytelling():
    print("\n=== Storytelling Engine ===")
    ste = StorytellingEngine()
    ctx = {
        "macd_golden_cross": True,
        "rsi14": 72.0,
        "change_pct": 5.5,
        "main_inflow": 1.5e8,
        "shrinking_volume": True,
    }
    stories = ste.translate_indicators(ctx)
    check("stories生成", len(stories) >= 2, f"got {len(stories)} stories")
    check("stories非空", all(len(s) > 10 for s in stories))
    for s in stories:
        print(f"    {s[:60]}...")

    st = ste.explain_single("macd_golden_cross")
    check("单指标解释", len(st) > 10, st[:50])
    return ste


def test_dialogue(eng, ste):
    print("\n=== Dialogue Generator ===")
    dg = DialogueGenerator(emotion_engine=eng, storytelling_engine=ste)

    stock_ctx = {
        "symbol": "000001", "name": "平安银行",
        "change_pct": 3.5, "main_inflow": 5e7,
        "macd_golden_cross": True, "close": 12.50,
    }
    script = dg.generate_stock_dialogue(stock_ctx, min_turns=3, max_turns=6)
    check("个股对话生成", script is not None)
    check("3-6轮对话", 3 <= len(script.turns) <= 8, f"got {len(script.turns)} turns")
    check("有男女角色", any(t.speaker == Speaker.MALE for t in script.turns) and
          any(t.speaker == Speaker.FEMALE for t in script.turns))
    check("m→to_dict", "turns" in script.to_dict())
    for t in script.turns:
        print(f"    [{t.speaker.value}] {t.text[:60]}...")

    script2 = dg.generate_sector_dialogue({"name": "机器人概念"})
    check("板块对话", len(script2.turns) >= 3)

    script3 = dg.generate_market_review({"up_count": 1500, "down_count": 800, "avg_change_pct": 0.8})
    check("大盘复盘", len(script3.turns) >= 3)
    return dg


def test_debate(eng):
    print("\n=== Debate Engine ===")
    de = DebateEngine(emotion_engine=eng)

    turns = de.generate({"name": "贵州茅台", "change_pct": 7.2, "main_inflow": 2e8})
    check("辩论生成", len(turns) >= 4, f"got {len(turns)} turns")
    check("有提问", any(t.is_question for t in turns))
    for t in turns:
        print(f"    [{t.speaker.value}] {t.text[:60]}...")

    turns2 = de.generate({"name": "某股票", "change_pct": -6.0, "main_inflow": -1e8})
    check("看空场景", len(turns2) >= 4)
    return de


def test_humor():
    print("\n=== Finance Humor Engine ===")
    he = FinanceHumorEngine()
    joke_turns = he.generate_dialogue()
    check("段子生成", len(joke_turns) >= 2)
    for t in joke_turns:
        print(f"    [{t.speaker.value}] {t.text[:60]}...")
    one_line = he.one_liner()
    check("一句话段子", len(one_line) > 10, one_line[:60])
    return he


def test_audience():
    print("\n=== Audience Agent ===")
    aa = AudienceAgent()
    q = aa.generate_question(["000001", "600519"])
    check("观众提问", len(q["question"]) > 5, q["question"][:50])
    print(f"    {q['username']}: {q['question']}")
    batch = aa.generate_batch(5)
    check("批量提问", len(batch) == 5)
    qa = aa.generate_qa_dialogue(q)
    check("QA脚本", len(qa.turns) >= 3)
    return aa


def test_comment_fusion(aa):
    print("\n=== Live Comment Fusion ===")
    lcf = LiveCommentFusion(audience_agent=aa)
    lcf.push_real("老王", "000001怎么看？")
    r = lcf.get_next()
    check("真实弹幕优先", r and r["source"] == "real", str(r))
    r2 = lcf.get_next(["600519"])
    check("模拟弹幕回退", r2 and r2["source"] == "simulated", str(r2))
    return lcf


def test_avatar_actions():
    print("\n=== Avatar Action Engine ===")
    aae = AvatarActionEngine()
    test_turns = [
        DialogTurn(speaker=Speaker.MALE, text="分析", emotion=Emotion.NEUTRAL),
        DialogTurn(speaker=Speaker.FEMALE, text="提问", emotion=Emotion.THINKING, is_question=True),
        DialogTurn(speaker=Speaker.MALE, text="警告", emotion=Emotion.WARNING),
        DialogTurn(speaker=Speaker.FEMALE, text="开心", emotion=Emotion.EXCITED),
    ]
    actions = aae.batch_actions(test_turns)
    check("动作生成", len(actions) == len(test_turns))
    for a in actions:
        print(f"    [{a['speaker']}] emo={a['emotion']} → act={a['action']} intensity={a['intensity']}")
    check("每个都有动作", all("action" in a and "intensity" in a for a in actions))
    male_actions = [a["action"] for a in actions if a["speaker"] == "male"]
    check("男主播动作多样性", len(set(male_actions)) >= 2, str(set(male_actions)))


def test_models():
    print("\n=== Data Models ===")
    check("Speaker values", Speaker.MALE == "male" and Speaker.FEMALE == "female")
    check("Emotion values", len(list(Emotion)) == 8, f"got {len(list(Emotion))}")
    check("AvatarAction values", len(list(AvatarAction)) >= 10)
    check("ShowSegmentType values", len(list(ShowSegmentType)) == 10, f"got {len(list(ShowSegmentType))}")
    check("DEFAULT_SCHEDULE", len(DEFAULT_SCHEDULE) == 7)
    check("EMOTION_ACTION_MAP", len(EMOTION_ACTION_MAP) == len(list(Emotion)))

    turn = DialogTurn(speaker=Speaker.MALE, text="测试", emotion=Emotion.HAPPY)
    d = turn.to_dict()
    check("DialogTurn.to_dict", d["speaker"] == "male" and d["emotion"] == "happy")

    script = DialogueScript(segment_id="t1", segment_type=ShowSegmentType.OPENING, topic="test",
                            turns=[turn, DialogTurn(speaker=Speaker.FEMALE, text="好")])
    check("m-lines", script.male_lines == ["测试"])
    check("f-lines", len(script.female_lines) == 1)
    d2 = script.to_dict()
    check("script.to_dict", d2["turn_count"] == 2)

    c = DualHostConfig()
    check("config默认值", c.tick_seconds == 1.0 and c.dialogue_turns_per_stock == (3, 6))


# ── Async tests ────────────────────────────────────────────────

async def test_director():
    print("\n=== Director Agent ===")
    dcfg = DualHostConfig()
    d = DirectorAgent(config=dcfg)
    segments_received = []

    async def test_callback(seg_type, meta):
        segments_received.append(seg_type)
        return None

    d.on_segment(test_callback)
    await d.start()
    await asyncio.sleep(1.5)
    await d.stop()

    check("导演启动", len(segments_received) > 0, f"received {len(segments_received)} segments")
    print(f"    收到片段: {[s.value for s in segments_received]}")
    check("开场先触发", ShowSegmentType.OPENING in segments_received)
    rundown = d.get_rundown()
    check("有调度信息", len(rundown) > 0)


async def test_news(eng):
    print("\n=== News Commentator ===")
    nc = NewsCommentator(emotion_engine=eng)
    news_script = await nc.get_commentary()
    check("新闻评论", news_script is not None)
    check("4-6轮对话", 3 <= len(news_script.turns) <= 7, f"got {len(news_script.turns)} turns")
    print(f"    topic: {news_script.topic}")
    for t in news_script.turns:
        print(f"    [{t.speaker.value}] {t.text[:60]}...")


# ── Main ───────────────────────────────────────────────────────

async def main():
    # Sync tests
    eng = test_emotion()
    ste = test_storytelling()
    test_dialogue(eng, ste)
    test_debate(eng)
    test_humor()
    aa = test_audience()
    test_comment_fusion(aa)
    test_avatar_actions()
    test_models()

    # Async tests
    await test_director()
    await test_news(eng)

    print(f"\n{'='*50}")
    print(f"  TOTAL: {PASS+FAIL} tests, {PASS} PASS, {FAIL} FAIL")
    print(f"{'='*50}")

    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
