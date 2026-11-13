from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def fetch_candles(
        self, symbol: str, *, market: str, exchange: str | None,
        interval: str, start: date | None, end: date | None,
    ) -> pd.DataFrame:
        raise NotImplementedError


class ProviderError(RuntimeError):
    """A provider request failed or returned unusable data."""
