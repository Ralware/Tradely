from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Any

from app.core.models import Instrument, TradingRules

_ZERO = Decimal("0")
_STEP_EPSILON = Decimal("1e-12")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def default_trading_rules(instrument: Instrument | dict[str, Any]) -> TradingRules:
    """Conservative ledger rules where provider metadata is unavailable.

    Crypto quotes route through TradingView, whose symbol metadata provides a
    price scale but not exchange order filters. The live rules are therefore
    derived and labelled as such, never presented as broker execution rules.
    """
    market = instrument.market if isinstance(instrument, Instrument) else instrument.get("market")
    if market == "crypto":
        return TradingRules(
            quantity_step=0.00000001,
            min_quantity=0.00000001,
            min_notional=1.0,
            fractional=True,
            source="TradingView Symbol Metadata Unavailable; Conservative Fallback",
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


def tradingview_rules_from_symbol_info(
    payload: dict[str, Any], symbol: str = "",
) -> TradingRules:
    """Derive a conservative quantity step from TradingView symbol metadata.

    TradingView publishes a price scale (``pricescale``/``minmov``), not the
    exchange's lot-size filter. Two extra decimal places beyond the price scale
    keep the ledger useful without inventing exchange precision.
    """
    try:
        pricescale = int(payload.get("pricescale") or 0)
        minmov = int(payload.get("minmov") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("TradingView symbol metadata has no usable price scale") from exc
    if pricescale < 1:
        raise ValueError("TradingView symbol metadata has no usable price scale")
    price_decimals = max(0, len(str(pricescale)) - 1)
    quantity_decimals = min(8, price_decimals + 2)
    step = Decimal(1).scaleb(-quantity_decimals)
    return TradingRules(
        quantity_step=float(step),
        min_quantity=float(step),
        min_notional=1.0,
        fractional=True,
        source=(
            f"TradingView symbol precision (pricescale={pricescale}, minmov={minmov})"
            + (f" for {symbol}" if symbol else "")
            + "; derived estimate, not exchange order filters"
        ),
        is_fallback=False,
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
