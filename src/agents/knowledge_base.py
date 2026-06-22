"""财经知识库 — 内置技术指标、K线形态、板块知识、风险知识、术语解释。

供主播引用，可在直播中自动调用。

特性:
    1. 技术指标解释 (MACD/KDJ/RSI/BOLL/MA...)
    2. K线形态识别 (锤子线/十字星/三只乌鸦...)
    3. 板块分类知识
    4. 风险知识
    5. 术语词典
    6. 支持模糊搜索和关键词匹配

用法:
    from src.agents.knowledge_base import FinanceKnowledgeBase

    kb = FinanceKnowledgeBase()
    entry = kb.search("MACD")        # 按关键词搜索
    random_tip = kb.get_random_tip() # 获取随机知识（用于直播暖场）
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeEntry:
    """知识条目。"""
    id: str
    category: str      # indicator / pattern / sector / risk / term / fun_fact
    title: str
    content: str        # 详细解释
    summary: str = ""   # 一句话总结（用于主播口播）
    tags: list[str] = field(default_factory=list)
    difficulty: str = "beginner"  # beginner / intermediate / advanced
    script: str = ""    # 主播口播脚本

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "content": self.content,
            "summary": self.summary,
            "tags": self.tags,
            "difficulty": self.difficulty,
            "script": self.script,
        }


# ── Built-in Knowledge Base ──────────────────────────────────────────────


_TECHNICAL_INDICATORS: list[dict] = [
    {
        "id": "indicator_macd",
        "category": "indicator",
        "title": "MACD — 指数平滑异同移动平均线",
        "content": "MACD由快线(DIF)、慢线(DEA)和柱状图组成。当DIF上穿DEA形成'金叉'为买入信号，下穿形成'死叉'为卖出信号。MACD柱状图从负转正为买入信号，从正转负为卖出信号。",
        "summary": "MACD金叉买，死叉卖，是最常用的趋势指标之一。",
        "tags": ["MACD", "金叉", "死叉", "趋势", "DIF", "DEA"],
        "difficulty": "beginner",
        "script": "MACD指标啊，是我们技术分析中最常用的指标之一。简单说就是金叉买入、死叉卖出。当快线DIF上穿慢线DEA的时候，就形成金叉，是买入信号；反过来DIF下穿DEA就是死叉，要考虑卖出了。不过呢，任何指标都不能单独使用，要结合K线形态和成交量一起来判断。",
    },
    {
        "id": "indicator_kdj",
        "category": "indicator",
        "title": "KDJ — 随机指标",
        "content": "KDJ由K线、D线和J线组成，取值范围0-100。K值和D值低于20为超卖区，高于80为超买区。J线最敏感，J值大于100或小于0时提示反转可能。",
        "summary": "KDJ低于20超卖可关注反弹，高于80超买注意回调风险。",
        "tags": ["KDJ", "超买", "超卖", "随机指标", "K线", "D线", "J线"],
        "difficulty": "beginner",
        "script": "KDJ指标，也叫随机指标，反映的是股价在近期内的相对位置。一般来说，KDJ值低于20，说明股票处于超卖状态，可能会有反弹；高于80呢，就是超买状态，短期可能要回调。但是要注意，在强势上涨行情中，KDJ可以在高位钝化很长时间，所以不能单独看KDJ就做决定。",
    },
    {
        "id": "indicator_rsi",
        "category": "indicator",
        "title": "RSI — 相对强弱指标",
        "content": "RSI衡量一段时间内价格上涨幅度与下跌幅度的比值，范围0-100。RSI>70为超买，RSI<30为超卖。RSI背离（价格创新高而RSI未创新高）是重要的反转信号。",
        "summary": "RSI超过70要注意回调，低于30可能是抄底机会。",
        "tags": ["RSI", "超买", "超卖", "背离", "相对强弱"],
        "difficulty": "intermediate",
        "script": "RSI，相对强弱指标，衡量的是买卖力量的对比。RSI大于70，说明买方力量过强，短期可能回调；低于30，说明卖方力量衰竭，可能反弹。特别要注意RSI背离，如果股价创新高但RSI没创新高，这是顶背离，回调风险很大。",
    },
    {
        "id": "indicator_boll",
        "category": "indicator",
        "title": "BOLL — 布林带",
        "content": "布林带由中轨（20日均线）、上轨和下轨组成。价格触及上轨可能回调，触及下轨可能反弹。带宽收窄预示变盘，带宽扩大确认趋势。",
        "summary": "股价触及布林带上轨注意压力，触及下轨注意支撑。",
        "tags": ["BOLL", "布林带", "压力", "支撑", "变盘"],
        "difficulty": "intermediate",
        "script": "布林带是个很实用的指标。中轨是20日均线，上轨是压力位，下轨是支撑位。股价运行到上轨附近，短期压力较大；跌到下轨附近，往往有支撑。当布林带开口收得很窄的时候，往往意味着要变盘了，这个时候要格外留意。",
    },
    {
        "id": "indicator_ma",
        "category": "indicator",
        "title": "MA — 移动平均线",
        "content": "均线系统包括5日、10日、20日、60日、120日、250日均线。短期均线上穿长期均线形成'金叉'为买入信号，反之为'死叉'。均线多头排列（短期均线在上，长期在下）为强势，空头排列为弱势。",
        "summary": "均线多头排列看涨，空头排列看跌，金叉买死叉卖。",
        "tags": ["MA", "均线", "金叉", "死叉", "多头排列", "空头排列"],
        "difficulty": "beginner",
        "script": "均线是我们看盘最基本的东西。短期均线上穿长期均线叫金叉，是看涨信号；反过来就是死叉，看跌。当多条均线从上到下按短期到长期排列，这叫多头排列，说明趋势很强；反过来就是空头排列，说明在下跌趋势中。",
    },
    {
        "id": "indicator_volume",
        "category": "indicator",
        "title": "成交量分析",
        "content": "量价关系是技术分析的核心。'量价齐升'为健康上涨，'价升量缩'为背离需警惕，'价跌量增'为恐慌抛售，'价跌量缩'为缩量调整。地量见地价，天量见天价。",
        "summary": "量价配合最重要，有量才有价，无量不追高。",
        "tags": ["成交量", "量价关系", "放量", "缩量", "地量", "天量"],
        "difficulty": "beginner",
        "script": "成交量是市场的温度计。量价齐升说明上涨健康，可以持有；价格上涨但成交量萎缩，这就要小心了，说明追涨力量不足。大幅下跌伴随巨量，往往是恐慌盘出逃，可能是短期底部。地量见地价，极度缩量往往离底部不远了。",
    },
]


_KLINE_PATTERNS: list[dict] = [
    {
        "id": "pattern_hammer",
        "category": "pattern",
        "title": "锤子线 — 底部反转信号",
        "content": "锤子线出现在下跌趋势末端，下影线长度至少是实体长度的2倍，上影线很短或没有。表明空方力量衰竭，多方开始反击，是看涨信号。",
        "summary": "底部出现长下影线锤子线，可能是止跌信号。",
        "tags": ["锤子线", "反转", "底部", "下影线"],
        "difficulty": "beginner",
        "script": "大家看这根K线，下影线特别长，实体很小，像一把锤子，这就叫锤子线。在下跌趋势中出现锤子线，说明空头打压不下去了，多头开始反击，是个止跌信号。不过要等第二天的阳线确认才更可靠。",
    },
    {
        "id": "pattern_doji",
        "category": "pattern",
        "title": "十字星 — 变盘信号",
        "content": "十字星开盘价和收盘价几乎相同，上下影线长度相当。出现在上涨趋势末端为'黄昏之星'，出现在下跌趋势末端为'早晨之星'，预示趋势可能反转。",
        "summary": "十字星是多空平衡的信号，往往预示变盘。",
        "tags": ["十字星", "变盘", "反转", "早晨之星", "黄昏之星"],
        "difficulty": "beginner",
        "script": "十字星很有意思，开盘价和收盘价几乎一样，说明多空双方打了一天打成平手。上涨过程中出现十字星，说明多头力量衰减了，可能要回调；下跌过程中出现十字星，说明空头力量衰竭了，可能要反弹。",
    },
    {
        "id": "pattern_three_crows",
        "category": "pattern",
        "title": "三只乌鸦 — 顶部反转信号",
        "content": "三只乌鸦由三根连续阴线组成，每根开盘价在前一根实体内，收盘价接近当日最低。出现在上涨趋势后，是强烈的看跌信号。",
        "summary": "连续三根阴线叫三只乌鸦，是强烈的卖出信号。",
        "tags": ["三只乌鸦", "阴线", "反转", "顶部", "看跌"],
        "difficulty": "intermediate",
        "script": "三只乌鸦是非常经典的顶部反转形态。连续三根阴线，一根比一根低，说明空头力量非常强。如果是在高位出现三只乌鸦，投资者要高度警惕，及时减仓。",
    },
    {
        "id": "pattern_three_soldiers",
        "category": "pattern",
        "title": "红三兵 — 底部反转信号",
        "content": "红三兵由三根连续阳线组成，每根收盘价高于前一根，开盘价在前一根实体内。出现在下跌趋势后，是强烈的看涨信号。",
        "summary": "底部三连阳叫红三兵，是强烈的买入信号。",
        "tags": ["红三兵", "阳线", "反转", "底部", "看涨"],
        "difficulty": "intermediate",
        "script": "红三兵是和三只乌鸦对应的底部反转信号。底部连续出现三根阳线，而且一根比一根高，说明多头开始主导市场。如果配合放量，信号更加可靠。",
    },
    {
        "id": "pattern_engulfing",
        "category": "pattern",
        "title": "吞没形态 — 强烈反转信号",
        "content": "看涨吞没：阴线之后出现一根大阳线，阳线实体完全覆盖前一根阴线。看跌吞没：阳线之后出现一根大阴线，阴线实体完全覆盖前一根阳线。是重要的反转信号。",
        "summary": "大阳线吞没前一根阴线叫看涨吞没，是买入信号。",
        "tags": ["吞没", "反转", "阳包阴", "阴包阳"],
        "difficulty": "intermediate",
        "script": "吞没形态是非常经典的反转信号。如果在下跌中出现一根大阳线，完全吞没了前一天的小阴线，这叫看涨吞没，是多头强力反击的信号。反之，上涨中出现大阴线吞没前一天的阳线，就是看跌吞没，要警惕。",
    },
]


_SECTOR_KNOWLEDGE: list[dict] = [
    {
        "id": "sector_tech",
        "category": "sector",
        "title": "科技板块",
        "content": "科技板块包括半导体、软件、人工智能、消费电子等。受政策支持力度大，但波动也大。关注芯片国产替代、AI应用落地、数字经济等主线。",
        "summary": "科技板块弹性大，涨得快跌得也快，适合波段操作。",
        "tags": ["科技", "半导体", "芯片", "AI", "人工智能", "软件", "消费电子"],
        "difficulty": "beginner",
        "script": "科技板块是我们A股最活跃的板块之一。芯片、AI、软件这些都是国家战略支持的，长期看好。但是科技股的波动也特别大，涨得快跌得也快，操作上要注意控制节奏，不要追高。",
    },
    {
        "id": "sector_consumer",
        "category": "sector",
        "title": "大消费板块",
        "content": "消费板块包括白酒、食品饮料、家电、医美等。特点是业绩稳定、现金流好，是外资偏爱的板块。关注消费复苏节奏、CPI数据、节假日消费。",
        "summary": "消费股业绩稳定，适合长期持有，但要注意估值。",
        "tags": ["消费", "白酒", "食品", "家电", "医美"],
        "difficulty": "beginner",
        "script": "大消费是A股的压舱石。白酒、食品、家电这些都是刚需，业绩稳定，长期来看是很好的投资标的。但消费股也要注意估值，估值太高的时候买入，可能要等很久才能回本。",
    },
    {
        "id": "sector_new_energy",
        "category": "sector",
        "title": "新能源板块",
        "content": "新能源包括光伏、风电、储能、新能源汽车等。是'双碳'目标下的核心赛道。关注产能过剩风险、技术路线变化、海外政策变动。",
        "summary": "新能源长期向好，但短期产能过剩需要消化。",
        "tags": ["新能源", "光伏", "风电", "储能", "新能源汽车", "锂电池"],
        "difficulty": "intermediate",
        "script": "新能源是国家战略方向，光伏、储能、新能源汽车都是万亿级赛道。不过大家要注意，前两年产能扩张太快，现在有些细分领域出现了产能过剩，价格战比较激烈。选股要选有技术壁垒的龙头。",
    },
    {
        "id": "sector_finance",
        "category": "sector",
        "title": "金融板块",
        "content": "金融板块包括银行、券商、保险。银行股息率高、估值低，是防御品种；券商弹性大，牛市急先锋；保险兼具保障和投资属性。关注利率、政策、市场情绪。",
        "summary": "银行防守、券商进攻、保险均衡，金融三驾马车各有千秋。",
        "tags": ["金融", "银行", "券商", "保险", "高股息"],
        "difficulty": "beginner",
        "script": "金融板块分为银行、券商、保险三大类。银行股分红高、估值低，适合稳健型投资者；券商股是牛市风向标，行情来的时候涨得最快；保险股介于两者之间。配置金融股要注意分散，不要只买一个细分。",
    },
    {
        "id": "sector_medical",
        "category": "sector",
        "title": "医药板块",
        "content": "医药包括创新药、医疗器械、中药、医疗服务等。特点是刚需+政策敏感。关注集采政策影响、创新药出海、中药政策利好等。",
        "summary": "医药是长牛赛道，但要关注集采政策的影响。",
        "tags": ["医药", "创新药", "医疗器械", "中药", "CXO", "集采"],
        "difficulty": "intermediate",
        "script": "医药板块长期来看是非常好的赛道，人口老龄化带来的需求是确定的。但医药股有一个大风险就是集采，集采会大幅压低药价，影响利润。所以选医药股要看研发实力，有创新药管线的公司更有投资价值。",
    },
]


_RISK_KNOWLEDGE: list[dict] = [
    {
        "id": "risk_diversification",
        "category": "risk",
        "title": "分散投资原则",
        "content": "不要把所有鸡蛋放在一个篮子里。建议单只股票仓位不超过总资金的20%，单个行业不超过40%。通过分散投资降低非系统性风险。",
        "summary": "分散投资是控制风险最基本的方法，不要满仓一只票。",
        "tags": ["分散投资", "仓位管理", "风险控制"],
        "difficulty": "beginner",
        "script": "老话说得好，不要把鸡蛋放在一个篮子里。再好的股票也有风险，建议大家的仓位要分散，单只股票最好不要超过总资金的20%。这样即使踩到雷，也不会伤筋动骨。",
    },
    {
        "id": "risk_stop_loss",
        "category": "risk",
        "title": "止损纪律",
        "content": "设置止损是保护本金的关键。建议根据个人风险承受能力设置5%-10%的止损线。跌破止损位坚决卖出，不要抱有侥幸心理。",
        "summary": "设置止损线，到了就卖，不要犹豫。",
        "tags": ["止损", "风险控制", "纪律"],
        "difficulty": "beginner",
        "script": "止损是投资的第一课。很多散户亏大钱，就是因为没有止损纪律，跌了不舍得卖，越套越深。我建议大家买入之前就想好止损位，比如亏5%就卖，到了就坚决执行，不要犹豫。",
    },
    {
        "id": "risk_leverage",
        "category": "risk",
        "title": "杠杆风险警示",
        "content": "融资融券和配资放大了收益也放大了风险。加杠杆后股价下跌可能触发强制平仓，导致本金全部亏损。普通投资者不建议使用杠杆。",
        "summary": "不要借钱炒股！杠杆会放大亏损，可能血本无归。",
        "tags": ["杠杆", "融资融券", "配资", "风险", "强制平仓"],
        "difficulty": "beginner",
        "script": "在这里我要特别提醒大家，千万不要借钱炒股、不要加杠杆！杠杆是把双刃剑，赚的时候是快，但亏的时候更快。一旦触发强制平仓，本金可能就全没了。用闲钱投资，心态才会好。",
    },
    {
        "id": "risk_chasing",
        "category": "risk",
        "title": "追高风险",
        "content": "追涨杀跌是散户亏损的主要原因。连续涨停的股票风险极大，开板后可能连续跌停。建议回调低吸而非追高买入。",
        "summary": "不要追涨杀跌，涨多了要谨慎，跌多了反而有机会。",
        "tags": ["追高", "追涨杀跌", "风险"],
        "difficulty": "beginner",
        "script": "追涨杀跌是散户亏钱最主要的原因。看到一个股票涨得好就冲进去，结果买在最高点；看到跌得厉害就割肉，结果卖在最低点。正确的方法应该是回调低吸，而不是追高买入。",
    },
    {
        "id": "risk_rumor",
        "category": "risk",
        "title": "消息面风险",
        "content": "不要轻信小道消息和荐股群。内幕交易违法，跟风消息炒股风险极大。建议以公开信息为准，结合技术面和基本面独立判断。",
        "summary": "不要听小道消息炒股，内幕消息往往是陷阱。",
        "tags": ["消息面", "内幕交易", "荐股", "风险"],
        "difficulty": "beginner",
        "script": "大家一定要警惕各种荐股群和小道消息。真正有用的消息不会随便传播，等传到散户耳朵里的时候，主力早就布局好了。投资要基于公开信息和自己的独立判断。",
    },
    {
        "id": "risk_market_hours",
        "category": "risk",
        "title": "交易时间与市场规则",
        "content": "A股交易时间为周一至周五9:30-11:30和13:00-15:00。T+1交易制度，当天买入次日才能卖出。涨跌停板±10%（科创/创业板±20%）。",
        "summary": "A股T+1交易，今天买的明天才能卖。",
        "tags": ["交易规则", "T+1", "涨跌停", "交易时间"],
        "difficulty": "beginner",
        "script": "提醒一下刚入市的朋友，A股是T+1交易，今天买的股票明天才能卖。所以盘中看到冲高不能当天卖出获利，要有心理准备。另外有涨跌停限制，主板±10%，科创板和创业板是±20%。",
    },
]


_TERMS: list[dict] = [
    {
        "id": "term_bull_bear",
        "category": "term",
        "title": "牛市与熊市",
        "content": "牛市(Bull Market)：市场持续上涨，投资者情绪乐观。熊市(Bear Market)：市场持续下跌，投资者情绪悲观。通常以涨跌20%为牛熊分界线。",
        "summary": "牛市就是持续上涨的行情，熊市就是持续下跌的行情。",
        "tags": ["牛市", "熊市", "牛熊"],
        "difficulty": "beginner",
        "script": "牛市和熊市是最基本的概念。简单说，牛市就是市场在涨、大家情绪好；熊市就是市场在跌、大家都比较悲观。一般来说，从低点涨超20%就可以认为是牛市，跌超20%就是熊市。",
    },
    {
        "id": "term_pe",
        "category": "term",
        "title": "市盈率 PE",
        "content": "市盈率=股价/每股收益，反映市场对公司未来盈利的预期。PE越高，市场给予的估值越高。不同行业PE差异很大，科技股PE通常高于银行股。",
        "summary": "市盈率越低越便宜，但不同行业要分开比较。",
        "tags": ["市盈率", "PE", "估值", "每股收益"],
        "difficulty": "beginner",
        "script": "市盈率PE是最常用的估值指标，等于股价除以每股收益。PE低说明股票相对便宜，PE高说明市场给了高估值。但不同行业的PE不能直接比较，科技股PE普遍比银行股高。",
    },
    {
        "id": "term_pb",
        "category": "term",
        "title": "市净率 PB",
        "content": "市净率=股价/每股净资产。PB<1表示股价低于净资产（破净），可能被低估。银行、钢铁等重资产行业常用PB估值。",
        "summary": "市净率小于1叫破净，股价低于公司净资产。",
        "tags": ["市净率", "PB", "破净", "净资产"],
        "difficulty": "beginner",
        "script": "市净率PB是股价除以每股净资产。如果PB小于1，说明股价比公司的净资产还低，也就是'破净'。银行股经常出现破净，但破净不一定就是便宜，还要看资产质量。",
    },
    {
        "id": "term_limit",
        "category": "term",
        "title": "涨停与跌停",
        "content": "涨停：股价达到当日涨幅上限（主板10%，科创/创业板20%），无法继续上涨。跌停：股价达到当日跌幅上限，无法继续下跌。连续涨停/跌停需关注交易所问询。",
        "summary": "涨停就是涨到当天上限了，买不进了；跌停就是跌到当天下限了，卖不出了。",
        "tags": ["涨停", "跌停", "涨跌幅", "一字板"],
        "difficulty": "beginner",
        "script": "涨停和跌停是A股特有的制度。主板股票涨跌幅限制是10%，涨到10%就涨停了，买盘堆积但买不进；跌到10%就是跌停，想卖也卖不出去。科创板和创业板涨跌幅是20%，波动更大。",
    },
    {
        "id": "term_ipo",
        "category": "term",
        "title": "IPO — 首次公开发行",
        "content": "IPO(Initial Public Offering)即公司首次向公众发行股票。打新股即申购IPO股票，中签后以发行价买入，上市首日通常有溢价。但注册制下破发风险也存在。",
        "summary": "IPO就是新股上市，打新股中签一般能赚钱，但也有破发风险。",
        "tags": ["IPO", "新股", "打新", "上市", "发行价"],
        "difficulty": "beginner",
        "script": "IPO就是新股上市。打新股就是在发行价申购，中签后在上市当天卖出通常能赚个差价。不过现在注册制改革后，新股破发的情况也多了，打新也不是稳赚不赔了。",
    },
]


_FUN_FACTS: list[dict] = [
    {
        "id": "fun_wall_street",
        "category": "fun_fact",
        "title": "华尔街铜牛的由来",
        "content": "华尔街铜牛是1989年艺术家Arturo Di Modica未经许可放置在纽约证券交易所前的。铜牛重达3200公斤，象征牛市的'力量和勇气'，现已成为金融市场的标志。",
        "summary": "华尔街铜牛重3.2吨，是牛市的象征。",
        "tags": ["华尔街", "铜牛", "趣闻"],
        "difficulty": "beginner",
        "script": "大家知道华尔街那头著名的铜牛有多重吗？3.2吨！是1989年一位艺术家偷偷放在交易所门口的，后来成了华尔街的象征。牛市用牛来代表，因为牛攻击时角向上顶，象征上涨。",
    },
    {
        "id": "fun_tulip",
        "category": "fun_fact",
        "title": "郁金香泡沫 — 史上第一次金融泡沫",
        "content": "17世纪荷兰郁金香狂热是人类历史上有记载的第一次金融泡沫。一株稀有郁金香球茎价格曾高达一栋豪宅的价格，泡沫破裂后价格暴跌99%以上。",
        "summary": "荷兰郁金香泡沫是人类历史上第一次金融泡沫。",
        "tags": ["郁金香", "泡沫", "历史", "趣闻"],
        "difficulty": "beginner",
        "script": "说起金融泡沫，不得不提荷兰的郁金香泡沫。17世纪的时候，荷兰人疯狂炒作郁金香球茎，一株稀有品种能换一栋房子。泡沫破裂后价格跌了99%，很多人倾家荡产。这个故事告诉我们，任何资产涨得太疯狂都要小心。",
    },
    {
        "id": "fun_nyse_button",
        "category": "fun_fact",
        "title": "纽交所敲钟仪式",
        "content": "纽约证券交易所每天开盘和收盘都会举行敲钟仪式，邀请各界名人、上市公司CEO来敲钟。这个传统从1903年延续至今，是华尔街最具仪式感的时刻。",
        "summary": "纽交所敲钟仪式已有120年历史。",
        "tags": ["纽交所", "敲钟", "趣闻"],
        "difficulty": "beginner",
        "script": "纽约证券交易所每天开盘都会敲钟，这个传统已经120年了。能去纽交所敲钟是企业家的荣耀，很多上市公司上市当天都会去敲钟。我们虽然不能去纽交所，但在直播间里也可以感受一下市场的脉搏。",
    },
]


class FinanceKnowledgeBase:
    """财经知识库。

    推送事件:
      knowledge.query_result    — 搜索结果
      knowledge.random_tip      — 随机知识
    """

    def __init__(self) -> None:
        self._entries: dict[str, KnowledgeEntry] = {}
        self._index: dict[str, list[str]] = {}  # tag/word → [entry_ids]
        self._load_builtin()
        self._build_index()

    # ── Data Loading ────────────────────────────────────────────────

    def _load_builtin(self) -> None:
        """加载内置知识。"""
        all_data = (
            _TECHNICAL_INDICATORS +
            _KLINE_PATTERNS +
            _SECTOR_KNOWLEDGE +
            _RISK_KNOWLEDGE +
            _TERMS +
            _FUN_FACTS
        )

        for item in all_data:
            entry = KnowledgeEntry(**item)
            self._entries[entry.id] = entry

        logger.info("FinanceKnowledgeBase loaded: %d entries", len(self._entries))

    def _build_index(self) -> None:
        """构建搜索索引。"""
        self._index.clear()
        for entry_id, entry in self._entries.items():
            # 索引标题
            words = set(entry.title.lower().split())
            # 索引标签
            words.update(t.lower() for t in entry.tags)
            # 索引内容关键词
            words.update(w.lower() for w in entry.content[:200].split())

            for word in words:
                word = word.strip("，。！？、：；""''（）…—·")
                if len(word) >= 2:
                    if word not in self._index:
                        self._index[word] = []
                    if entry_id not in self._index[word]:
                        self._index[word].append(entry_id)

    # ── Search ──────────────────────────────────────────────────────

    def search(self, query: str, category: str = "", limit: int = 5) -> list[KnowledgeEntry]:
        """模糊搜索知识条目。

        Args:
            query: 搜索关键词
            category: 限定分类 (indicator/pattern/sector/risk/term/fun_fact)
            limit: 返回条数上限
        """
        query_words = [w.strip("，。！？、：；""''（）…—·").lower()
                       for w in query.split() if len(w.strip()) >= 1]

        scored: dict[str, float] = {}

        for word in query_words:
            if word in self._index:
                for entry_id in self._index[word]:
                    scored[entry_id] = scored.get(entry_id, 0) + 1

            # 模糊匹配：包含关系
            for idx_word, entry_ids in self._index.items():
                if word in idx_word or idx_word in word:
                    for entry_id in entry_ids:
                        scored[entry_id] = scored.get(entry_id, 0) + 0.5

        # 排序
        sorted_ids = sorted(scored.keys(), key=lambda k: -scored[k])

        results = []
        for entry_id in sorted_ids:
            entry = self._entries.get(entry_id)
            if entry:
                if category and entry.category != category:
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def get_by_id(self, entry_id: str) -> KnowledgeEntry | None:
        """按ID获取知识条目。"""
        return self._entries.get(entry_id)

    def get_by_category(self, category: str) -> list[KnowledgeEntry]:
        """获取指定分类的所有知识。"""
        return [e for e in self._entries.values() if e.category == category]

    # ── Random Tips ─────────────────────────────────────────────────

    def get_random_tip(self, category: str = "") -> KnowledgeEntry | None:
        """获取随机知识（用于直播暖场/填充）。"""
        pool = [e for e in self._entries.values()
                if not category or e.category == category]
        if not pool:
            return None
        return random.choice(pool)

    def get_daily_knowledge(self, seed: str = "") -> KnowledgeEntry | None:
        """获取每日知识（基于日期种子，同一天返回相同结果）。"""
        import hashlib
        from datetime import date
        seed = seed or date.today().isoformat()
        idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(self._entries)
        return list(self._entries.values())[idx]

    # ── Script Generation ───────────────────────────────────────────

    def generate_script(self, query: str) -> str:
        """根据查询生成主播口播脚本。"""
        results = self.search(query, limit=1)
        if results and results[0].script:
            return results[0].script

        # 组合多个相关条目
        results = self.search(query, limit=3)
        if not results:
            return f"关于{query}，让我们稍后在节目中详细讨论。"

        parts = []
        for i, entry in enumerate(results):
            if i == 0:
                parts.append(f"首先来聊聊{entry.title}。{entry.summary}")
            else:
                parts.append(f"另外，{entry.title}方面，{entry.summary}")

        return "。".join(parts) + "。以上内容仅供参考，不构成投资建议。"

    # ── Stats ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        return {
            "total_entries": len(self._entries),
            "categories": {
                cat: len(self.get_by_category(cat))
                for cat in ["indicator", "pattern", "sector", "risk", "term", "fun_fact"]
            },
            "index_terms": len(self._index),
        }

    # ── Import/Export ───────────────────────────────────────────────

    def export_json(self, path: str) -> None:
        """导出知识库为 JSON。"""
        data = [e.to_dict() for e in self._entries.values()]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_json(self, path: str) -> int:
        """从 JSON 导入知识库（追加模式）。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for item in data:
            entry = KnowledgeEntry(**item)
            if entry.id not in self._entries:
                self._entries[entry.id] = entry
                count += 1

        if count:
            self._build_index()
            logger.info("Imported %d knowledge entries from %s", count, path)

        return count
