"""Lightweight service orchestration for all modules."""

from dataclasses import dataclass

from stockstream.agent.service import AgentService
from stockstream.danmu.service import DanmuService
from stockstream.database.service import DatabaseService
from stockstream.market.service import MarketService
from stockstream.selector.service import SelectorService
from stockstream.stream.service import StreamService
from stockstream.tts.service import TTSService


@dataclass(slots=True)
class Services:
    """Container for module services used by the web API."""

    database: DatabaseService
    market: MarketService
    selector: SelectorService
    tts: TTSService
    agent: AgentService
    stream: StreamService
    danmu: DanmuService


async def build_services() -> Services:
    """Build services with explicit dependencies for easier future extension."""

    database = DatabaseService()
    stream = StreamService()
    market = MarketService(database=database, stream=stream)
    selector = SelectorService(database=database, market_storage=market.storage)
    tts = TTSService()
    agent = AgentService(selector=selector, tts=tts)
    danmu = DanmuService(stream=stream)
    return Services(
        database=database,
        market=market,
        selector=selector,
        tts=tts,
        agent=agent,
        stream=stream,
        danmu=danmu,
    )
