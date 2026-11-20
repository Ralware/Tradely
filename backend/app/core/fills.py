"""Linear-contract fill fees in quote currency. Preserve precision until presentation."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal


@dataclass(frozen=True)
class FeeSchedule:
    maker: float = 0.0005
    taker: float = 0.0002

    def __post_init__(self):
        if not all(isfinite(rate) and 0 <= rate < 1 for rate in (self.maker, self.taker)):
            raise ValueError("Fee rates must be finite fractions in [0, 1)")

    def charge(self, quantity: float, price: float, liquidity: Literal["maker", "taker"]) -> float:
        if liquidity not in ("maker", "taker"):
            raise ValueError("Unknown execution classification")
        if not all(isfinite(v) and v > 0 for v in (quantity, price)):
            raise ValueError("Fill quantity and price must be finite and positive")
        return quantity * price * (self.maker if liquidity == "maker" else self.taker)


PERPETUAL_FEES = FeeSchedule()
