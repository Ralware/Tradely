from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RecognitionStatus = Literal["resolved", "ambiguous", "not_found", "unsupported"]


class TradingQuantityRules(BaseModel):
    quantity_step: float | None = None
    min_quantity: float | None = None
    fractional: bool | None = None
    min_notional: float | None = None
    source: str | None = None


class InstrumentCapabilities(BaseModel):
    instrument_id: str
    status: str
    quote_available: bool
    real_time_streaming: bool
    historical_ohlcv: bool
    supported_intervals: list[str] = Field(default_factory=list)
    adjusted_history: bool
    technicals: bool
    backtesting_eligible: bool
    corporate_events: bool
    news: bool
    provider: str
    provider_key: str
    quote_freshness: str
    quantity: TradingQuantityRules = Field(default_factory=TradingQuantityRules)
    data_limitations: list[str] = Field(default_factory=list)


class InstrumentSearchResponse(BaseModel):
    query: str
    normalized: str
    status: RecognitionStatus
    message: str | None = None
    instrument: dict | None = None
    candidates: list[dict] = Field(default_factory=list)
    count: int = 0
    recognized: dict | None = None
