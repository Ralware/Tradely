from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from app.services.strategy_config import StrategyConfig

HOLDING_QUANTITY_TOLERANCE = Decimal("1e-12")

Market = Literal["india", "global", "crypto"]
TransactionIntent = Literal["BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER"]
Side = TransactionIntent
DirectionMode = Literal["long_only", "short_only", "long_short"]
PositionDirection = Literal["LONG", "SHORT"]
AssetType = Literal["equity", "crypto"]
QuoteFreshness = Literal[
    "live", "delayed", "eod", "historical", "cached", "stale", "unavailable",
]
QuoteType = Literal[
    "real_time", "delayed", "last_available", "previous_close",
    "end_of_day", "historical", "cached", "stale", "unavailable",
]


class Instrument(BaseModel):
    """Canonical instrument identity shared by every Tradely module.

    A ticker alone is never treated as an identity. The provider-specific
    symbol, exchange, currency and asset type are retained so quotes are always
    requested for the exact instrument the owner recorded. Catalogue metadata
    extends the original ledger identity additively.
    """

    instrument_id: str
    symbol: str
    name: str
    market: Market
    exchange: str
    currency: str
    asset_type: AssetType
    provider: str
    provider_symbol: str
    display_name: str | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    settlement_currency: str | None = None
    trading_pair: str | None = None
    provider_instrument_id: str | None = None
    supported_intervals: list[str] = Field(default_factory=list)
    status: str = "active"
    catalogue_source: str | None = None
    catalogue_updated_at: datetime | None = None
    is_catalogue: bool = False
    aliases: list[str] = Field(default_factory=list)


class WatchlistItem(BaseModel):
    """Watchlist entry.

    New entries may supply only ``instrument_id``. The legacy ``symbol``,
    ``market`` and ``exchange`` fields remain optional so existing records and
    older clients continue to work.
    """

    symbol: str = ""
    market: Market | None = None
    exchange: str | None = None
    display_name: str | None = None
    instrument_id: str | None = None


class HoldingTransaction(BaseModel):
    """Internal ledger row.

    Quantity and price remain persisted because FIFO, cost basis and realised
    P&L require them. They are derived by the backend from a monetary amount
    and a validated quote for amount-based transaction entry.
    """

    symbol: str
    market: Market
    side: Side
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    trade_time: datetime
    currency: str = "INR"
    fees: float = Field(default=0, ge=0, allow_inf_nan=False)
    notes: str | None = None
    # Canonical identity supplied by instrument resolution. Optional for
    # backwards compatibility with previously recorded ledger rows.
    instrument_id: str | None = None
    name: str | None = None
    exchange: str | None = None
    asset_type: AssetType | None = None
    provider: str | None = None
    provider_symbol: str | None = None
    amount: float | None = Field(default=None, ge=0)
    actual_amount: float | None = Field(default=None, ge=0)
    quote_provider: str | None = None
    quote_time: datetime | None = None
    quote_type: str | None = None
    quote_status: str | None = None
    quote_currency: str | None = None
    idempotency_key: str | None = None

    @property
    def intent(self) -> TransactionIntent:
        return self.side

    @field_validator("trade_time")
    @classmethod
    def make_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("quote_time")
    @classmethod
    def quote_time_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class AmountTransactionRequest(BaseModel):
    """Amount-based transaction entry request.

    The client never supplies the accounting quantity or unit price. The
    backend resolves the instrument, acquires a valid quote and derives both.
    New clients should send ``intent``; legacy ``side`` remains accepted.
    """

    instrument_id: str = Field(min_length=3, max_length=120)
    intent: TransactionIntent = Field(validation_alias=AliasChoices("intent", "side"))
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str | None = None
    fees: float = Field(default=0, ge=0, allow_inf_nan=False)
    trade_time: datetime
    notes: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    execution_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    preview_id: str | None = Field(default=None, min_length=1, max_length=160)

    @property
    def side(self) -> TransactionIntent:
        return self.intent

    @field_validator("trade_time")
    @classmethod
    def make_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("instrument_id")
    @classmethod
    def clean_instrument_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("currency")
    @classmethod
    def clean_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class TradingRules(BaseModel):
    quantity_step: float
    min_quantity: float
    max_quantity: float | None = None
    min_notional: float
    fractional: bool
    source: str
    is_fallback: bool = False


class BacktestRequest(BaseModel):
    symbol: str = ""
    market: Market | None = None
    exchange: str | None = None
    instrument_id: str | None = None
    interval: str = "1d"
    days: int = Field(default=1825, ge=240, le=3650)
    provider: str = "auto"
    initial_capital: float = Field(default=1000, gt=0)
    risk_fraction: float = Field(default=0.005, gt=0, le=0.02)
    cost_bps_per_side: float = Field(default=2, ge=0, le=500)
    commission_bps_per_side: float | None = Field(default=None, ge=0, le=500)
    slippage_bps_per_side: float = Field(default=0, ge=0, le=500)
    max_position_fraction: float = Field(default=0.95, gt=0, le=1)
    direction_mode: DirectionMode = "long_only"
    strategy_config: StrategyConfig = Field(default_factory=StrategyConfig)

    @model_validator(mode="after")
    def validate_cost_assumptions(self):
        for name in ("initial_capital", "risk_fraction", "cost_bps_per_side", "max_position_fraction", "slippage_bps_per_side"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        commission = self.cost_bps_per_side if self.commission_bps_per_side is None else self.commission_bps_per_side
        if self.commission_bps_per_side is not None and not math.isfinite(self.commission_bps_per_side):
            raise ValueError("commission_bps_per_side must be finite")
        if commission + self.slippage_bps_per_side > 500:
            raise ValueError("Combined commission and slippage cannot exceed 500 bps per side")
        return self
