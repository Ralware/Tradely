from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Market = Literal["india", "global", "crypto"]
Side = Literal["BUY", "SELL"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0
    currency: str | None = None
    source: str
    is_adjusted: bool = False
    is_final: bool = True

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def finite_numbers(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("OHLCV values must be finite")
        return value


class ProviderStatus(BaseModel):
    name: str
    configured: bool
    available: bool | None = None
    note: str
    last_checked: datetime | None = None


class NewsItem(BaseModel):
    id: str
    title: str
    url: str
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    summary: str | None = None
    category: str = "general"
    source: str
    related_symbols: list[str] = Field(default_factory=list)
    official: bool = False


class IndicatorSnapshot(BaseModel):
    timestamp: datetime
    values: dict[str, float | None]


class SignalCondition(BaseModel):
    name: str
    passed: bool
    observed: float | str | None = None
    threshold: float | str | None = None
    explanation: str


class StrategySignal(BaseModel):
    symbol: str
    market: Market
    strategy: str
    strategy_version: str
    state: Literal["BUY", "SELL", "WAIT", "NO_SIGNAL", "INSUFFICIENT_DATA", "STALE_DATA", "DATA_QUALITY_ERROR"]
    as_of: datetime | None = None
    entry_reference: float | None = None
    stop_reference: float | None = None
    risk_per_unit: float | None = None
    conditions: list[SignalCondition]
    explanation: str
    data_source: str | None = None


class RiskRequest(BaseModel):
    capital: float = Field(gt=0)
    risk_fraction: float = Field(gt=0, le=0.02)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    lot_size: int = Field(default=1, ge=1)
    max_position_fraction: float = Field(default=1.0, gt=0, le=1)


class RiskResult(BaseModel):
    risk_budget: float
    risk_per_unit: float
    quantity: int
    position_value: float
    planned_loss: float
    capital_limited: bool


class WatchlistItem(BaseModel):
    symbol: str
    market: Market
    exchange: str | None = None
    display_name: str | None = None


class HoldingTransaction(BaseModel):
    symbol: str
    market: Market
    side: Side
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    trade_time: datetime
    currency: str = "INR"
    fees: float = Field(default=0, ge=0)
    notes: str | None = None

    @field_validator("trade_time")
    @classmethod
    def make_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class BacktestRequest(BaseModel):
    symbol: str
    market: Market
    exchange: str | None = None
    interval: str = "1d"
    days: int = Field(default=1825, ge=240, le=3650)
    provider: str = "auto"
    initial_capital: float = Field(default=100000, gt=0)
    risk_fraction: float = Field(default=0.005, gt=0, le=0.02)
    cost_bps_per_side: float = Field(default=15, ge=0, le=500)
    max_position_fraction: float = Field(default=0.95, gt=0, le=1)
