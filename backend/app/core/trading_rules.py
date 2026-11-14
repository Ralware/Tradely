from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Any

from app.core.models import Instrument, TradingRules

_ZERO = Decimal("0")
_STEP_EPSILON = Decimal("1e-12")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def default_trading_rules(instrument: Instrument | dict[str, Any]) -> TradingRules:
    """Conservative ledger rules where a broker-specific rule set is unavailable.

    Crypto quotes route through Binance, whose exchange rules are fetched by the
    quote service. For equities there is no public per-broker order filter in the
    configured free feeds, so the source is labelled honestly rather than
    pretending these are broker execution rules.
    """
    market = instrument.market if isinstance(instrument, Instrument) else instrument.get("market")
    if market == "crypto":
        return TradingRules(
            quantity_step=0.00000001,
            min_quantity=0.00000001,
            min_notional=5.0,
            fractional=True,
            source="Binance Pair Rules Unavailable; Conservative Fallback",
            is_fallback=True,
        )
    if market == "india":
        return TradingRules(
            quantity_step=1.0,
            min_quantity=1.0,
            min_notional=1.0,
            fractional=False,
            source="NSE/BSE Whole Shares",
        )
    return TradingRules(
        quantity_step=0.000001,
        min_quantity=0.000001,
        min_notional=1.0,
        fractional=True,
        source="Fractional-Share Market Default",
    )


def binance_rules_from_exchange_info(
    payload: dict[str, Any], symbol: str,
) -> TradingRules:
    """Extract quantity and notional filters for one exact Binance Spot pair."""
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise ValueError("Binance exchangeInfo response did not contain symbols")
    match = next(
        (
            item for item in symbols
            if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol.upper()
        ),
        None,
    )
    if not match:
        raise ValueError(f"Binance exchangeInfo did not include {symbol}")

    filters = {
        str(item.get("filterType")): item
        for item in match.get("filters", [])
        if isinstance(item, dict) and item.get("filterType")
    }
    lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")
    if not lot:
        raise ValueError(f"Binance did not publish LOT_SIZE rules for {symbol}")
    step = _decimal(lot.get("stepSize") or "0")
    minimum = _decimal(lot.get("minQty") or step)
    maximum_value = lot.get("maxQty")
    maximum = _decimal(maximum_value) if maximum_value not in (None, "") else None
    notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
    minimum_notional = _decimal(notional_filter.get("minNotional") or "0")
    if step <= _ZERO:
        raise ValueError(f"Binance returned an invalid quantity step for {symbol}")
    return TradingRules(
        quantity_step=float(step),
        min_quantity=float(max(minimum, step)),
        max_quantity=float(maximum) if maximum is not None else None,
        min_notional=float(max(minimum_notional, _ZERO)),
        fractional=step < Decimal("1"),
        source="Binance Spot Exchange Rules",
    )


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= _ZERO:
        raise ValueError("Quantity step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _as_float(value: Decimal) -> float:
    return float(value)


def calculate_amount_transaction(
    *,
    side: str,
    requested_amount: float,
    price: float,
    rules: TradingRules,
    available_quantity: float | None = None,
    fees: float = 0.0,
) -> dict[str, Any]:
    """Derive quantity and reconciled notional from a monetary amount.

    Quantity is always rounded down to the instrument step. A BUY therefore
    never spends more than the requested amount. A SELL first checks the
    maximum sellable market value of the available holdings and rejects an
    amount above it.
    """
    amount = _decimal(requested_amount)
    reference_price = _decimal(price)
    fee_value = _decimal(fees)
    step = _decimal(rules.quantity_step)
    minimum_quantity = _decimal(rules.min_quantity)
    minimum_notional = _decimal(rules.min_notional)
    maximum_quantity = _decimal(rules.max_quantity) if rules.max_quantity is not None else None

    if amount <= _ZERO:
        raise ValueError("Transaction amount must be positive")
    if reference_price <= _ZERO:
        raise ValueError("A positive reference price is required")
    if fee_value < _ZERO:
        raise ValueError("Fees cannot be negative")

    raw_quantity = amount / reference_price
    quantity = _floor_to_step(raw_quantity, step)
    available = _decimal(available_quantity) if available_quantity is not None else None
    max_sell_quantity: Decimal | None = None
    max_sell_amount: Decimal | None = None
    remaining_holding_quantity: Decimal | None = None

    if side == "SELL":
        if available is None:
            raise ValueError("Available holdings are required for a SELL transaction")
        if available <= _ZERO:
            raise ValueError("No available holdings to sell for this instrument")
        max_sell_quantity = _floor_to_step(available, step)
        max_sell_amount = max_sell_quantity * reference_price
        tolerance = max(Decimal("0.000001"), max_sell_amount * Decimal("0.000000001"))
        if amount > max_sell_amount + tolerance:
            raise ValueError(
                f"Sell amount {float(amount):.8g} exceeds the available holdings market value "
                f"{float(max_sell_amount):.8g}"
            )
        remaining_holding_quantity = max(_ZERO, available - quantity)

    if quantity <= _ZERO:
        raise ValueError(
            "Amount is too small for the instrument quantity step; increase the amount"
        )
    if quantity < minimum_quantity:
        raise ValueError(
            f"Derived quantity {float(quantity):.8g} is below the instrument minimum "
            f"quantity {float(minimum_quantity):.8g}"
        )
    if maximum_quantity is not None and quantity > maximum_quantity:
        raise ValueError(
            f"Derived quantity {float(quantity):.8g} exceeds the instrument maximum order "
            f"quantity {float(maximum_quantity):.8g}"
        )

    actual_amount = quantity * reference_price
    if actual_amount < minimum_notional:
        raise ValueError(
            f"Actual notional {float(actual_amount):.8g} is below the instrument minimum "
            f"notional {float(minimum_notional):.8g}"
        )

    remainder = amount - actual_amount
    if abs(remainder) <= _STEP_EPSILON:
        remainder = _ZERO
    if remainder < _ZERO and abs(remainder) > Decimal("0.000000001"):
        raise ValueError("Quantity rounding exceeded the requested transaction amount")
    if remainder < _ZERO:
        remainder = _ZERO

    return {
        "quantity": _as_float(quantity),
        "actual_amount": _as_float(actual_amount),
        "remaining_amount": _as_float(remainder),
        "requested_amount": _as_float(amount),
        "fees": _as_float(fee_value),
        "total_cash_cost": _as_float(actual_amount + fee_value) if side == "BUY" else None,
        "net_proceeds": _as_float(actual_amount - fee_value) if side == "SELL" else None,
        "available_quantity": _as_float(available) if available is not None else None,
        "max_sell_amount": _as_float(max_sell_amount) if max_sell_amount is not None else None,
        "max_sell_quantity": _as_float(max_sell_quantity) if max_sell_quantity is not None else None,
        "remaining_holding_quantity": (
            _as_float(remaining_holding_quantity) if remaining_holding_quantity is not None else None
        ),
        "rules": rules.model_dump(mode="json"),
    }
