from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class StrategyConfig(BaseModel):
    """The Trend + Donchian strategy's actual rule parameters."""
    sma_fast_period: int = Field(50, ge=2, le=500)
    sma_slow_period: int = Field(200, ge=3, le=1000)
    rsi_period: int = Field(14, ge=2, le=100)
    rsi_threshold: float = Field(50, ge=1, le=99)
    adx_period: int = Field(14, ge=2, le=100)
    min_adx: float = Field(20, ge=0, le=100)
    atr_period: int = Field(14, ge=2, le=100)
    initial_stop_atr: float = Field(2.0, gt=0, le=20)
    trailing_stop_atr: float = Field(3.0, gt=0, le=20)
    donchian_entry_period: int = Field(20, ge=2, le=500)
    rvol_period: int = Field(20, ge=2, le=500)
    min_rvol: float = Field(1.0, ge=0, le=100)
    donchian_exit_period: int = Field(10, ge=2, le=500)

    @model_validator(mode="after")
    def validate_sma_order(self):
        if self.sma_fast_period >= self.sma_slow_period:
            raise ValueError("Fast SMA period must be less than slow SMA period")
        return self


DEFAULT_STRATEGY_CONFIG = StrategyConfig()
