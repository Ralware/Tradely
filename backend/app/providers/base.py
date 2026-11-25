from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import numpy as np
import pandas as pd


def normalize_candles(
    frame: pd.DataFrame,
    *,
    max_candles: int | None = None,
) -> pd.DataFrame:
    """Return unique, chronological OHLCV candles without inventing missing bars.

    ``max_candles`` is an optional safety limit for callers that explicitly need
    one. By default nothing is truncated, so the full requested provider range is
    preserved.
    """
    if frame is None or frame.empty:
        raise ProviderError("Provider returned no candles")
    if max_candles is not None and max_candles < 1:
        raise ValueError("max_candles must be >= 1")
    missing = {"open", "high", "low", "close"} - set(frame.columns)
    if missing:
        raise ProviderError(f"Provider response missing required OHLC fields: {', '.join(sorted(missing))}")

    result = frame.copy()
    attrs = dict(frame.attrs)
    original_rows = len(result)
    result.index = pd.to_datetime(result.index, utc=True, errors="coerce")
    result["volume"] = result["volume"] if "volume" in result.columns else 0
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.loc[~result.index.isna()]
    result = result.dropna(subset=["open", "high", "low", "close"])
    # Reject non-finite prices and impossible OHLC relationships instead of
    # letting them reach indicators, the price axis or a backtest.
    finite = np.isfinite(result[["open", "high", "low", "close"]].to_numpy(dtype=float)).all(axis=1)
    result = result.loc[finite]
    if not result.empty:
        body_high = result[["open", "close", "low"]].max(axis=1)
        body_low = result[["open", "close", "high"]].min(axis=1)
        valid_ohlc = (result["high"] >= body_high) & (result["low"] <= body_low)
        valid_volume = result["volume"].isna() | (result["volume"] >= 0)
        result = result.loc[valid_ohlc & valid_volume]
    duplicates = int(result.index.duplicated(keep="last").sum())
    result = result.loc[~result.index.duplicated(keep="last")]
    result = result.sort_index(kind="stable")
    truncated = max_candles is not None and len(result) > max_candles
    if truncated:
        result = result.tail(max_candles)
    if result.empty:
        raise ProviderError("Provider returned no valid OHLC candles")
    result = result[["open", "high", "low", "close", "volume"]]
    result.attrs.update(attrs)
    result.attrs["normalized_rows"] = len(result)
    result.attrs["invalid_rows"] = max(0, original_rows - len(result) - duplicates)
    result.attrs["duplicate_rows"] = duplicates
    if truncated:
        result.attrs["history_truncated"] = True
    return result


ADJUSTMENT_STATUSES = {"adjusted", "unadjusted", "unknown"}


def get_adjustment_status(frame: pd.DataFrame, fallback: str = "unknown") -> str:
    """Read verified adjustment provenance without collapsing unknown to false."""
    status = frame.attrs.get("adjustment_status")
    if status in ADJUSTMENT_STATUSES:
        return str(status)
    legacy = frame.attrs.get("is_adjusted")
    if isinstance(legacy, (bool, np.bool_)):
        return "adjusted" if bool(legacy) else "unadjusted"
    return fallback if fallback in ADJUSTMENT_STATUSES else "unknown"


class MarketDataProvider(ABC):
    name: str

    @property
    def adjustment_status(self) -> str:
        return "unknown"

    @property
    def is_adjusted(self) -> bool | None:
        status = self.adjustment_status
        return True if status == "adjusted" else False if status == "unadjusted" else None

    @abstractmethod
    def fetch_candles(
        self, symbol: str, *, market: str, exchange: str | None,
        interval: str, start: date | None, end: date | None,
    ) -> pd.DataFrame:
        raise NotImplementedError


class ProviderError(RuntimeError):
    """A provider request failed or returned unusable data."""
