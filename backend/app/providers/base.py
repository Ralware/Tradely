from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

MAX_HISTORY_CANDLES = 2500


def normalize_candles(
    frame: pd.DataFrame,
    *,
    max_candles: int = MAX_HISTORY_CANDLES,
) -> pd.DataFrame:
    """Return unique, chronological OHLCV candles without inventing missing bars."""
    if frame is None or frame.empty:
        raise ProviderError("Provider returned no candles")
    if max_candles < 1:
        raise ValueError("max_candles must be >= 1")
    missing = {"open", "high", "low", "close"} - set(frame.columns)
    if missing:
        raise ProviderError(f"Provider response missing required OHLC fields: {', '.join(sorted(missing))}")

    result = frame.copy()
    attrs = dict(frame.attrs)
    result.index = pd.to_datetime(result.index, utc=True, errors="coerce")
    result["volume"] = result["volume"] if "volume" in result.columns else 0
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.loc[~result.index.isna()]
    result = result.dropna(subset=["open", "high", "low", "close"])
    result = result.loc[~result.index.duplicated(keep="last")]
    result = result.sort_index(kind="stable")
    truncated = len(result) > max_candles
    if truncated:
        result = result.tail(max_candles)
    if result.empty:
        raise ProviderError("Provider returned no valid OHLC candles")
    result = result[["open", "high", "low", "close", "volume"]]
    result.attrs.update(attrs)
    if truncated:
        result.attrs["history_truncated"] = True
    return result


class MarketDataProvider(ABC):
    name: str
    max_history_candles = MAX_HISTORY_CANDLES

    @property
    def is_adjusted(self) -> bool:
        return False

    @abstractmethod
    def fetch_candles(
        self, symbol: str, *, market: str, exchange: str | None,
        interval: str, start: date | None, end: date | None,
    ) -> pd.DataFrame:
        raise NotImplementedError


class ProviderError(RuntimeError):
    """A provider request failed or returned unusable data."""
