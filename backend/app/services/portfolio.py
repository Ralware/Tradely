"""FIFO portfolio accounting.

The rules here are the single source of truth for invested value, realised
P&L, unrealised P&L and transaction fee allocation. React never recalculates
these values; it only renders this module's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Any

from app.core.models import HOLDING_QUANTITY_TOLERANCE

getcontext().prec = 28

_EPSILON = HOLDING_QUANTITY_TOLERANCE
_ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    if value is None:
        return _ZERO
    return Decimal(str(value))


def _float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _round(value: Decimal, places: str = "0.000000000001") -> float:
    quantum = Decimal(places)
    return float(value.quantize(quantum))


@dataclass
class Lot:
    transaction_id: int
    acquired_at: str
    original_quantity: Decimal
    quantity: Decimal
    unit_cost: Decimal
    original_fees: Decimal
    price: Decimal


@dataclass
class Account:
    instrument_id: str
    symbol: str
    name: str
    market: str
    exchange: str
    currency: str
    asset_type: str
    provider: str
    provider_symbol: str
    quantity: Decimal = _ZERO
    cost_basis: Decimal = _ZERO
    realised_pnl: Decimal = _ZERO
    total_bought: Decimal = _ZERO
    total_sold: Decimal = _ZERO
    buy_fees: Decimal = _ZERO
    sell_fees: Decimal = _ZERO
    long_lots: list[Lot] = field(default_factory=list)
    short_lots: list[Lot] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def lots(self) -> list[Lot]:
        return self.short_lots if self.position_side == "SHORT" else self.long_lots

    @property
    def fees_total(self) -> Decimal:
        return self.buy_fees + self.sell_fees

    @property
    def position_side(self) -> str | None:
        if self.quantity > _EPSILON:
            return "LONG"
        if self.quantity < -_EPSILON:
            return "SHORT"
        return None

    @property
    def average_cost(self) -> Decimal:
        if abs(self.quantity) <= _EPSILON:
            return _ZERO
        return self.cost_basis / abs(self.quantity)

    @property
    def is_open(self) -> bool:
        return abs(self.quantity) > _EPSILON


@dataclass
class Ledger:
    accounts: dict[str, Account]
    transactions: list[dict[str, Any]]


def _instrument_fields(row: dict[str, Any]) -> dict[str, str]:
    symbol = (row.get("symbol") or "").upper()
    market = row.get("market") or ""
    exchange = (row.get("exchange") or "").upper()
    instrument_id = row.get("instrument_id") or f"{market}:{exchange}:{symbol}"
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "name": row.get("instrument_name") or row.get("name") or symbol,
        "market": market,
        "exchange": exchange,
        "currency": (row.get("currency") or "").upper(),
        "asset_type": row.get("asset_type") or ("crypto" if market == "crypto" else "equity"),
        "provider": row.get("provider") or "",
        "provider_symbol": row.get("provider_symbol") or symbol,
    }


def build_ledger(transactions: list[dict[str, Any]]) -> Ledger:
    """Replay manual LONG/SHORT exposure using distinct FIFO lot queues.

    A BUY lot's unit cost includes its proportional BUY fee. A SELL's net
    proceeds per unit deduct its proportional SELL fee. A SELL_SHORT lot keeps
    net opening proceeds per unit, while BUY_TO_COVER includes its fee in the
    covering cost. No intent executes an order or represents spot borrowing.
    """
    accounts: dict[str, Account] = {}
    rows: list[dict[str, Any]] = []

    ordered = sorted(
        transactions,
        key=lambda row: (str(row.get("trade_time") or ""), int(row.get("id") or 0)),
    )
    for row in ordered:
        fields = _instrument_fields(row)
        key = fields["instrument_id"]
        account = accounts.get(key)
        if account is None:
            account = Account(**fields)
            accounts[key] = account

        quantity = _decimal(row.get("quantity"))
        price = _decimal(row.get("price"))
        fees = _decimal(row.get("fees"))
        side = str(row.get("intent") or row.get("side") or "").upper()
        stored_amount = _decimal(row.get("amount"))
        stored_actual_amount = _decimal(row.get("actual_amount"))
        amount = stored_amount if stored_amount > _ZERO else quantity * price
        actual_amount = stored_actual_amount if stored_actual_amount > _ZERO else quantity * price
        output = {
            "id": int(row.get("id") or 0),
            **fields,
            "side": "BUY" if side in {"BUY", "BUY_TO_COVER"} else "SELL",
            "intent": side,
            "quantity": _round(quantity),
            "price": _round(price),
            "amount": _round(amount),
            "actual_amount": _round(actual_amount),
            "remaining_amount": _round(max(_ZERO, amount - actual_amount)),
            "trade_time": row.get("trade_time"),
            "currency": (row.get("currency") or account.currency).upper(),
            "fees": _round(fees),
            "notes": row.get("notes"),
            "quote_provider": row.get("quote_provider") or "",
            "quote_time": row.get("quote_time"),
            "quote_type": row.get("quote_type") or "",
            "quote_status": row.get("quote_status") or "",
            "quote_currency": row.get("quote_currency") or "",
            "realised_pnl": 0.0,
        }

        if quantity <= _ZERO:
            continue

        if side == "BUY":
            if account.position_side == "SHORT":
                raise ValueError(
                    f"BUY would reverse an open SHORT exposure for {fields['symbol']}"
                )
            fee_per_unit = fees / quantity
            unit_cost = price + fee_per_unit
            account.long_lots.append(
                Lot(
                    transaction_id=output["id"],
                    acquired_at=str(row.get("trade_time") or ""),
                    original_quantity=quantity,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    original_fees=fees,
                    price=price,
                )
            )
            account.quantity += quantity
            account.cost_basis += quantity * unit_cost
            account.total_bought += quantity
            account.buy_fees += fees
            output["cost_basis_added"] = _round(quantity * unit_cost)
            output["unit_cost"] = _round(unit_cost)
        elif side == "SELL":
            if account.position_side != "LONG" or account.quantity + _EPSILON < quantity:
                raise ValueError(
                    f"Ledger contains a sell larger than recorded holdings for {fields['symbol']}"
                )
            proceeds_per_unit = price - (fees / quantity)
            remaining = quantity
            realised = _ZERO
            consumed_cost = _ZERO
            while remaining > _EPSILON:
                if not account.long_lots:
                    raise ValueError(
                        f"Ledger contains a sell larger than recorded holdings for {fields['symbol']}"
                    )
                lot = account.long_lots[0]
                consumed = min(remaining, lot.quantity)
                realised += consumed * (proceeds_per_unit - lot.unit_cost)
                consumed_cost += consumed * lot.unit_cost
                lot.quantity -= consumed
                remaining -= consumed
                if lot.quantity <= _EPSILON:
                    account.long_lots.pop(0)
            account.quantity -= quantity
            if abs(account.quantity) <= _EPSILON:
                account.quantity = _ZERO
            account.cost_basis -= consumed_cost
            if account.cost_basis <= _EPSILON:
                account.cost_basis = _ZERO
            account.realised_pnl += realised
            account.total_sold += quantity
            account.sell_fees += fees
            output["realised_pnl"] = _round(realised)
            output["cost_basis_consumed"] = _round(consumed_cost)
            output["proceeds"] = _round(quantity * proceeds_per_unit)
        elif side == "SELL_SHORT":
            if account.position_side == "LONG":
                raise ValueError(
                    f"SELL_SHORT would reverse an open LONG exposure for {fields['symbol']}"
                )
            net_proceeds_per_unit = price - (fees / quantity)
            account.short_lots.append(
                Lot(
                    transaction_id=output["id"],
                    acquired_at=str(row.get("trade_time") or ""),
                    original_quantity=quantity,
                    quantity=quantity,
                    unit_cost=net_proceeds_per_unit,
                    original_fees=fees,
                    price=price,
                )
            )
            account.quantity -= quantity
            account.cost_basis += quantity * net_proceeds_per_unit
            account.total_sold += quantity
            account.sell_fees += fees
            output["cost_basis_added"] = _round(quantity * net_proceeds_per_unit)
            output["unit_proceeds"] = _round(net_proceeds_per_unit)
            output["proceeds"] = _round(quantity * net_proceeds_per_unit)
        elif side == "BUY_TO_COVER":
            if account.position_side != "SHORT" or abs(account.quantity) + _EPSILON < quantity:
                raise ValueError(
                    f"Ledger contains a cover larger than recorded short holdings for "
                    f"{fields['symbol']}"
                )
            cover_cost_per_unit = price + (fees / quantity)
            remaining = quantity
            realised = _ZERO
            consumed_proceeds = _ZERO
            while remaining > _EPSILON:
                if not account.short_lots:
                    raise ValueError(
                        f"Ledger contains a cover larger than recorded short holdings for "
                        f"{fields['symbol']}"
                    )
                lot = account.short_lots[0]
                consumed = min(remaining, lot.quantity)
                realised += consumed * (lot.unit_cost - cover_cost_per_unit)
                consumed_proceeds += consumed * lot.unit_cost
                lot.quantity -= consumed
                remaining -= consumed
                if lot.quantity <= _EPSILON:
                    account.short_lots.pop(0)
            account.quantity += quantity
            if abs(account.quantity) <= _EPSILON:
                account.quantity = _ZERO
            account.cost_basis -= consumed_proceeds
            if account.cost_basis <= _EPSILON:
                account.cost_basis = _ZERO
            account.realised_pnl += realised
            account.total_bought += quantity
            account.buy_fees += fees
            output["realised_pnl"] = _round(realised)
            output["cost_basis_consumed"] = _round(consumed_proceeds)
            output["cover_cost"] = _round(quantity * cover_cost_per_unit)
        else:
            raise ValueError(f"Unsupported transaction intent: {side}")

        account.transactions.append(output)
        rows.append(output)

    return Ledger(accounts=accounts, transactions=rows)


def _quote_price(account: Account, quote: dict[str, Any] | None) -> tuple[Decimal | None, str | None]:
    if not quote:
        return None, "No market quote is available"
    if quote.get("price") is None:
        return None, quote.get("error") or "Market price unavailable"
    quote_currency = (quote.get("currency") or "").upper()
    if quote_currency and quote_currency != account.currency:
        return None, (
            f"Quote currency {quote_currency} does not match holding currency {account.currency}"
        )
    return _decimal(quote.get("price")), None


def position_view(account: Account, quote: dict[str, Any] | None) -> dict[str, Any]:
    quantity = account.quantity
    price, price_error = _quote_price(account, quote)
    market_value = price * abs(quantity) if price is not None else None
    unrealised = (
        (account.cost_basis - market_value if account.position_side == "SHORT"
         else market_value - account.cost_basis)
        if market_value is not None
        else None
    )
    return_pct = (
        (unrealised / account.cost_basis) * 100
        if unrealised is not None and account.cost_basis > _EPSILON
        else None
    )
    payload: dict[str, Any] = {
        "instrument_id": account.instrument_id,
        "symbol": account.symbol,
        "name": account.name,
        "market": account.market,
        "exchange": account.exchange,
        "currency": account.currency,
        "asset_type": account.asset_type,
        "provider": account.provider,
        "provider_symbol": account.provider_symbol,
        "position_side": account.position_side,
        "direction": account.position_side,
        "cost_basis_type": (
            "net_short_opening_proceeds"
            if account.position_side == "SHORT"
            else "long_acquisition_cost"
        ),
        "quantity": _round(quantity),
        "absolute_quantity": _round(abs(quantity)),
        "average_cost": _round(account.average_cost),
        "cost_basis": _round(account.cost_basis),
        "realised_pnl": _round(account.realised_pnl),
        "current_price": _round(price) if price is not None else None,
        "market_value": _round(market_value) if market_value is not None else None,
        "unrealized_pnl": _round(unrealised) if unrealised is not None else None,
        "return_pct": _round(return_pct, "0.00000001") if return_pct is not None else None,
        "day_change": quote.get("day_change") if quote else None,
        "day_change_pct": quote.get("day_change_pct") if quote else None,
        "total_bought": _round(account.total_bought),
        "total_sold": _round(account.total_sold),
        "fees_total": _round(account.fees_total),
        "buy_fees": _round(account.buy_fees),
        "sell_fees": _round(account.sell_fees),
        "lot_count": len(account.lots),
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
        "quote": quote,
        "valuation_error": price_error,
    }
    return payload


def summary_view(
    ledger: Ledger,
    quotes: dict[str, dict[str, Any]],
    *,
    base_currency: str,
    transactions_count: int,
) -> dict[str, Any]:
    currencies: dict[str, dict[str, Any]] = {}
    for account in ledger.accounts.values():
        bucket = currencies.setdefault(account.currency, {
            "currency": account.currency,
            "total_invested": _ZERO,
            "market_value": _ZERO,
            "unrealized_pnl": _ZERO,
            "realized_pnl": _ZERO,
            "total_pnl": _ZERO,
            "open_positions": 0,
            "closed_positions": 0,
            "priced_positions": 0,
            "unpriced_positions": 0,
            "long_positions": 0,
            "short_positions": 0,
            "priced_invested": _ZERO,
            "unpriced_invested": _ZERO,
            "short_proceeds_basis": _ZERO,
            "priced_short_proceeds_basis": _ZERO,
            "short_market_value": _ZERO,
            "gross_market_value": _ZERO,
            "transaction_fees": _ZERO,
            "latest_quote_at": None,
        })
        bucket["realized_pnl"] += account.realised_pnl
        bucket["transaction_fees"] += account.fees_total
        if not account.is_open:
            bucket["closed_positions"] += 1
            continue

        bucket["open_positions"] += 1
        is_short = account.position_side == "SHORT"
        bucket["short_positions" if is_short else "long_positions"] += 1
        if is_short:
            bucket["short_proceeds_basis"] += account.cost_basis
        else:
            bucket["total_invested"] += account.cost_basis
        quote = quotes.get(account.instrument_id)
        price, _ = _quote_price(account, quote)
        if price is None:
            bucket["unpriced_positions"] += 1
            if not is_short:
                bucket["unpriced_invested"] += account.cost_basis
            continue
        market_value = price * abs(account.quantity)
        bucket["priced_positions"] += 1
        bucket["gross_market_value"] += market_value
        if is_short:
            bucket["short_market_value"] += market_value
            bucket["priced_short_proceeds_basis"] += account.cost_basis
            unrealised = account.cost_basis - market_value
        else:
            bucket["priced_invested"] += account.cost_basis
            bucket["market_value"] += market_value
            unrealised = market_value - account.cost_basis
        bucket["unrealized_pnl"] += unrealised
        quote_time = quote.get("quote_time") if quote else None
        if quote_time and (bucket["latest_quote_at"] is None or quote_time > bucket["latest_quote_at"]):
            bucket["latest_quote_at"] = quote_time

    output: list[dict[str, Any]] = []
    for currency in sorted(currencies):
        bucket = currencies[currency]
        bucket["total_pnl"] = bucket["realized_pnl"] + bucket["unrealized_pnl"]
        bucket["unrealized_pnl_pct"] = (
            (
                bucket["unrealized_pnl"]
                / (bucket["priced_invested"] + bucket["priced_short_proceeds_basis"])
            ) * 100
            if bucket["priced_invested"] + bucket["priced_short_proceeds_basis"] > _EPSILON
            else None
        )
        if bucket["market_value"] > _EPSILON:
            bucket["realized_pnl_pct"] = (
                (bucket["realized_pnl"] / bucket["market_value"]) * 100
            )
        else:
            bucket["realized_pnl_pct"] = None
        bucket["total_pnl_pct"] = (
            (
                bucket["total_pnl"]
                / (bucket["priced_invested"] + bucket["priced_short_proceeds_basis"])
            ) * 100
            if bucket["priced_invested"] + bucket["priced_short_proceeds_basis"] > _EPSILON
            else None
        )
        output.append({
            key: (_round(value) if isinstance(value, Decimal) else value)
            for key, value in bucket.items()
        })

    open_positions = sum(1 for account in ledger.accounts.values() if account.is_open)
    return {
        "base_currency": base_currency.upper(),
        "currencies": output,
        "currency_conversion": "unavailable",
        "mode": "manual-research-exposure-ledger",
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
        "note": (
            "Amounts are grouped by transaction currency. INR, USD and USDT are not "
            "added together because no verified currency-conversion source is configured. "
            "BUY and BUY_TO_COVER fees increase their respective accounting costs; SELL "
            "and SELL_SHORT fees reduce recorded proceeds, so fees are counted exactly once. "
            "SHORT exposure is manual accounting only: no order execution, spot borrow, "
            "collateral, margin, or funding is implied. Total P&L = Realised P&L + "
            "Unrealised P&L. Market value is long-only; short marked exposure is reported "
            "separately as short_market_value and gross exposure as gross_market_value."
        ),
        "open_positions": open_positions,
        "closed_positions": sum(1 for account in ledger.accounts.values() if not account.is_open),
        "instruments": len(ledger.accounts),
        "transactions": transactions_count,
    }


def detail_view(
    account: Account,
    quote: dict[str, Any] | None,
) -> dict[str, Any]:
    position = position_view(account, quote)
    purchase_history = [row for row in account.transactions if row["intent"] == "BUY"]
    sale_history = [row for row in account.transactions if row["intent"] == "SELL"]
    short_history = [
        row for row in account.transactions
        if row["intent"] in {"SELL_SHORT", "BUY_TO_COVER"}
    ]
    lots = [
        {
            "transaction_id": lot.transaction_id,
            "acquired_at": lot.acquired_at,
            "position_side": account.position_side,
            "original_quantity": _round(lot.original_quantity),
            "remaining_quantity": _round(lot.quantity),
            "unit_cost": _round(lot.unit_cost),
            "unit_proceeds": (
                _round(lot.unit_cost) if account.position_side == "SHORT" else None
            ),
            "price": _round(lot.price),
            "fees_allocated": _round(lot.original_fees),
            "remaining_cost_basis": _round(lot.quantity * lot.unit_cost),
        }
        for lot in account.lots
    ]
    return {
        "instrument_id": account.instrument_id,
        "position": position,
        "purchase_history": purchase_history,
        "sale_history": sale_history,
        "short_history": short_history,
        "transactions": account.transactions,
        "remaining_lots": lots,
        "totals": {
            "total_bought": _round(account.total_bought),
            "total_sold": _round(account.total_sold),
            "buy_fees": _round(account.buy_fees),
            "sell_fees": _round(account.sell_fees),
            "fees_total": _round(account.fees_total),
            "realised_pnl": _round(account.realised_pnl),
            "remaining_cost_basis": _round(account.cost_basis),
            "average_cost": _round(account.average_cost),
            "position_side": account.position_side,
            "long_lot_count": len(account.long_lots),
            "short_lot_count": len(account.short_lots),
        },
        "purpose": "research/manual exposure tracking only",
        "order_execution": False,
        "spot_borrow_claims": False,
    }
