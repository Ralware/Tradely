from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RecognitionStatus = Literal["resolved", "ambiguous", "not_found", "unsupported"]


class InstrumentCandidate(BaseModel):
    instrument_id: str
    symbol: str
    name: str
    market: str
    exchange: str
    currency: str
    asset_type: str
    provider: str
    provider_symbol: str
    base_currency: str | None = None
    quote_currency: str | None = None
    trading_pair: str | None = None
    status: str = "active"
    score: float = 0
    match_type: Literal[
        "instrument_id", "symbol", "provider_symbol", "alias", "name",
        "partial_symbol", "partial_name",
    ] = "partial_name"
    asset_label: str = "Equity"


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
