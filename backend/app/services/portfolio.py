"""FIFO portfolio accounting.

The rules here are the single source of truth for invested value, realised
P&L, unrealised P&L and transaction fee allocation. React never recalculates
these values; it only renders this module's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Any

getcontext().prec = 28

_EPSILON = Decimal("1e-12")
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
    lots: list[Lot] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fees_total(self) -> Decimal:
        return self.buy_fees + self.sell_fees

    @property
    def average_cost(self) -> Decimal:
        if self.quantity <= _EPSILON:
            return _ZERO
        return self.cost_basis / self.quantity

    @property
    def is_open(self) -> bool:
        return self.quantity > _EPSILON


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
    """Replay the ledger using FIFO and fees allocated per unit.

    A BUY lot's unit cost includes its proportional BUY fee. A SELL's net
    proceeds per unit deduct its proportional SELL fee. Realised P&L therefore
    includes both fees exactly once and remaining cost basis retains the
    unsold portion of purchase fees.
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
        side = str(row.get("side") or "").upper()
        stored_amount = _decimal(row.get("amount"))
        stored_actual_amount = _decimal(row.get("actual_amount"))
        amount = stored_amount if stored_amount > _ZERO else quantity * price
        actual_amount = stored_actual_amount if stored_actual_amount > _ZERO else quantity * price
        output = {
            "id": int(row.get("id") or 0),
            **fields,
            "side": side,
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
            fee_per_unit = fees / quantity
            unit_cost = price + fee_per_unit
            account.lots.append(
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
            proceeds_per_unit = price - (fees / quantity)
            remaining = quantity
            realised = _ZERO
            consumed_cost = _ZERO
            while remaining > _EPSILON:
                if not account.lots:
                    raise ValueError(
                        f"Ledger contains a sell larger than recorded holdings for {fields['symbol']}"
                    )
                lot = account.lots[0]
                consumed = min(remaining, lot.quantity)
                realised += consumed * (proceeds_per_unit - lot.unit_cost)
                consumed_cost += consumed * lot.unit_cost
                lot.quantity -= consumed
                remaining -= consumed
                if lot.quantity <= _EPSILON:
                    account.lots.pop(0)
            account.quantity -= quantity
            if account.quantity <= _EPSILON:
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
        else:
            raise ValueError(f"Unsupported transaction side: {side}")

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
    market_value = price * quantity if price is not None else None
    unrealised = market_value - account.cost_basis if market_value is not None else None
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
        "quantity": _round(quantity),
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
            "priced_invested": _ZERO,
            "unpriced_invested": _ZERO,
            "transaction_fees": _ZERO,
            "latest_quote_at": None,
        })
        bucket["realized_pnl"] += account.realised_pnl
        bucket["transaction_fees"] += account.fees_total
        if not account.is_open:
            bucket["closed_positions"] += 1
            continue

        bucket["open_positions"] += 1
        bucket["total_invested"] += account.cost_basis
        quote = quotes.get(account.instrument_id)
        price, _ = _quote_price(account, quote)
        if price is None:
            bucket["unpriced_positions"] += 1
            bucket["unpriced_invested"] += account.cost_basis
            continue
        market_value = price * account.quantity
        bucket["priced_positions"] += 1
        bucket["priced_invested"] += account.cost_basis
        bucket["market_value"] += market_value
        bucket["unrealized_pnl"] += market_value - account.cost_basis
        quote_time = quote.get("quote_time") if quote else None
        if quote_time and (bucket["latest_quote_at"] is None or quote_time > bucket["latest_quote_at"]):
            bucket["latest_quote_at"] = quote_time

    output: list[dict[str, Any]] = []
    for currency in sorted(currencies):
        bucket = currencies[currency]
        bucket["total_pnl"] = bucket["realized_pnl"] + bucket["unrealized_pnl"]
        bucket["unrealized_pnl_pct"] = (
            (bucket["unrealized_pnl"] / bucket["priced_invested"]) * 100
            if bucket["priced_invested"] > _EPSILON
            else None
        )
        if bucket["market_value"] > _EPSILON:
            bucket["realized_pnl_pct"] = (
                (bucket["realized_pnl"] / bucket["market_value"]) * 100
            )
        else:
            bucket["realized_pnl_pct"] = None
        bucket["total_pnl_pct"] = (
            (bucket["total_pnl"] / bucket["priced_invested"]) * 100
            if bucket["priced_invested"] > _EPSILON
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
        "note": (
            "Amounts are grouped by transaction currency. INR, USD and USDT are not "
            "added together because no verified currency-conversion source is configured. "
            "BUY fees are included in cost basis; SELL fees reduce realised proceeds, so "
            "fees are counted exactly once. Total P&L = Realised P&L + Unrealised P&L."
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
    purchase_history = [row for row in account.transactions if row["side"] == "BUY"]
    sale_history = [row for row in account.transactions if row["side"] == "SELL"]
    lots = [
        {
            "transaction_id": lot.transaction_id,
            "acquired_at": lot.acquired_at,
            "original_quantity": _round(lot.original_quantity),
            "remaining_quantity": _round(lot.quantity),
            "unit_cost": _round(lot.unit_cost),
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
        },
    }
