"""Stock selection and signal generation module."""

from stockstream.database.service import DatabaseService


class SelectorService:
    """Runs lightweight rule-based selection, with room for ML models later."""

    def __init__(self, database: DatabaseService) -> None:
        self.database = database

    async def rank(self, symbols: list[str]) -> list[dict]:
        """Return deterministic placeholder rankings for candidate symbols."""

        return [
            {"symbol": symbol.upper(), "score": round(1.0 / (index + 1), 4)}
            for index, symbol in enumerate(symbols)
        ]
