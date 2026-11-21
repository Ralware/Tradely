from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.services.portfolio import build_ledger, detail_view, position_view, summary_view

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def row(
    identifier: int,
    side: str,
    quantity: float,
    price: float,
    *,
    offset_days: int = 0,
    fees: float = 0.0,
    symbol: str = "RELIANCE",
    market: str = "india",
    exchange: str = "NSE",
    currency: str = "INR",
) -> dict:
    return {
        "id": identifier,
        "instrument_id": f"{market}:{exchange}:{symbol}",
        "symbol": symbol,
        "instrument_name": symbol,
        "market": market,
        "exchange": exchange,
        "currency": currency,
        "asset_type": "crypto" if market == "crypto" else "equity",
        "provider": "test",
        "provider_symbol": f"{exchange}:{symbol}",
        "side": side,
        "quantity": quantity,
        "price": price,
        "fees": fees,
        "trade_time": (BASE + timedelta(days=offset_days)).isoformat(),
        "notes": None,
    }


def quote(instrument_id: str, price: float, currency: str = "INR", **extra) -> dict:
    return {
        "instrument_id": instrument_id,
        "price": price,
        "currency": currency,
        "quote_type": "end_of_day",
        "quote_time": BASE.isoformat(),
        "freshness": "eod",
        **extra,
    }


def test_buy_fees_are_included_in_cost_basis_and_average_cost():
    ledger = build_ledger([row(1, "BUY", 10, 100, fees=20)])
    account = ledger.accounts["india:NSE:RELIANCE"]
    assert float(account.quantity) == 10
    assert float(account.cost_basis) == 1020
    assert float(account.average_cost) == 102
    assert float(account.buy_fees) == 20


def test_sell_realised_pnl_deducts_sell_fees_and_keeps_position_when_partial():
    ledger = build_ledger([
        row(1, "BUY", 10, 100, fees=10, offset_days=0),
        row(2, "SELL", 4, 150, fees=4, offset_days=1),
    ])
    account = ledger.accounts["india:NSE:RELIANCE"]
    # Buy unit cost 101; sell net proceeds per unit 149; realised = 4 * 48 = 192.
    assert float(account.realised_pnl) == 192
    assert float(account.quantity) == 6
    # Remaining cost basis keeps the unsold portion of the buy fee.
    assert float(account.cost_basis) == 606
    assert account.is_open


def test_fifo_consumes_oldest_lots_first():
    ledger = build_ledger([
        row(1, "BUY", 5, 100, offset_days=0),
        row(2, "BUY", 5, 120, offset_days=1),
        row(3, "SELL", 6, 130, offset_days=2),
    ])
    account = ledger.accounts["india:NSE:RELIANCE"]
    # 5 units from the 100 lot (+30 each) and 1 from the 120 lot (+10).
    assert float(account.realised_pnl) == 160
    assert float(account.quantity) == 4
    assert float(account.cost_basis) == 480


def test_full_sell_closes_position_but_keeps_realised_pnl():
    ledger = build_ledger([
        row(1, "BUY", 2, 100, fees=4),
        row(2, "SELL", 2, 110, fees=4, offset_days=1),
    ])
    account = ledger.accounts["india:NSE:RELIANCE"]
    assert not account.is_open
    assert float(account.quantity) == 0
    assert float(account.cost_basis) == 0
    # Net proceeds 108 per unit vs 102 unit cost => 12.
    assert float(account.realised_pnl) == 12


def test_oversell_raises_instead_of_creating_short_position():
    with pytest.raises(ValueError, match="sell larger than recorded holdings"):
        build_ledger([
            row(1, "BUY", 1, 100),
            row(2, "SELL", 2, 100, offset_days=1),
        ])


def test_short_fifo_lots_and_partial_cover_include_fees_in_realised_pnl():
    ledger = build_ledger([
        row(1, "SELL_SHORT", 2, 100, fees=2, offset_days=0),
        row(2, "SELL_SHORT", 3, 120, fees=3, offset_days=1),
        row(3, "BUY_TO_COVER", 3, 90, fees=3, offset_days=2),
    ])
    account = ledger.accounts["india:NSE:RELIANCE"]
    assert account.position_side == "SHORT"
    assert float(account.quantity) == -2
    assert float(account.cost_basis) == 238
    assert float(account.realised_pnl) == 44
    assert len(account.short_lots) == 1
    assert float(account.short_lots[0].quantity) == 2
    assert account.long_lots == []


def test_short_position_view_and_summary_mark_exposure_and_pnl():
    ledger = build_ledger([row(1, "SELL_SHORT", 10, 100, fees=10)])
    account = ledger.accounts["india:NSE:RELIANCE"]
    mark = quote("india:NSE:RELIANCE", 90)
    position = position_view(account, mark)
    assert position["position_side"] == "SHORT"
    assert position["cost_basis_type"] == "net_short_opening_proceeds"
    assert position["quantity"] == -10
    assert position["absolute_quantity"] == 10
    assert position["cost_basis"] == 990
    assert position["market_value"] == 900
    assert position["unrealized_pnl"] == 90
    assert position["order_execution"] is False
    summary = summary_view(
        ledger, {"india:NSE:RELIANCE": mark},
        base_currency="INR", transactions_count=1,
    )
    bucket = summary["currencies"][0]
    assert bucket["total_invested"] == 0
    assert bucket["market_value"] == 0
    assert bucket["short_market_value"] == 900
    assert bucket["gross_market_value"] == 900
    assert bucket["unrealized_pnl"] == 90


def test_cover_cannot_overclose_or_reverse_short_position():
    with pytest.raises(ValueError, match="cover larger than recorded short holdings"):
        build_ledger([
            row(1, "SELL_SHORT", 1, 100),
            row(2, "BUY_TO_COVER", 2, 90, offset_days=1),
        ])
    with pytest.raises(ValueError, match="reverse an open SHORT"):
        build_ledger([
            row(1, "SELL_SHORT", 1, 100),
            row(2, "BUY", 1, 90, offset_days=1),
        ])
    with pytest.raises(ValueError, match="reverse an open LONG"):
        build_ledger([
            row(1, "BUY", 1, 100),
            row(2, "SELL_SHORT", 1, 90, offset_days=1),
        ])


def test_summary_never_adds_currencies_and_obeys_pnl_identity():
    ledger = build_ledger([
        row(1, "BUY", 10, 100, fees=10, market="india", symbol="RELIANCE", currency="INR"),
        row(2, "BUY", 2, 50, market="crypto", symbol="BTCUSDT", exchange="BINANCE", currency="USDT"),
        row(3, "SELL", 1, 60, offset_days=1, market="crypto", symbol="BTCUSDT",
            exchange="BINANCE", currency="USDT"),
    ])
    quotes = {
        "india:NSE:RELIANCE": quote("india:NSE:RELIANCE", 120, "INR"),
        "crypto:BINANCE:BTCUSDT": quote("crypto:BINANCE:BTCUSDT", 40, "USDT"),
    }
    summary = summary_view(ledger, quotes, base_currency="INR", transactions_count=3)
    assert summary["currency_conversion"] == "unavailable"
    currencies = {bucket["currency"]: bucket for bucket in summary["currencies"]}
    assert set(currencies) == {"INR", "USDT"}

    india = currencies["INR"]
    assert india["total_invested"] == 1010
    assert india["market_value"] == 1200
    assert india["unrealized_pnl"] == 190
    assert india["total_pnl"] == india["realized_pnl"] + india["unrealized_pnl"]

    crypto = currencies["USDT"]
    assert crypto["realized_pnl"] == 10
    assert crypto["market_value"] == 40
    assert crypto["unrealized_pnl"] == -10
    assert crypto["total_pnl"] == 0


def test_summary_separates_priced_and_unpriced_invested_value():
    ledger = build_ledger([
        row(1, "BUY", 10, 100),
        row(2, "BUY", 1, 100, symbol="TCS", offset_days=1),
    ])
    summary = summary_view(
        ledger,
        {"india:NSE:RELIANCE": quote("india:NSE:RELIANCE", 110)},
        base_currency="INR",
        transactions_count=2,
    )
    bucket = summary["currencies"][0]
    assert bucket["priced_positions"] == 1
    assert bucket["unpriced_positions"] == 1
    assert bucket["market_value"] == 1100
    assert bucket["unpriced_invested"] == 100


def test_position_view_refuses_quote_in_the_wrong_currency():
    ledger = build_ledger([row(1, "BUY", 1, 100)])
    account = ledger.accounts["india:NSE:RELIANCE"]
    view = position_view(account, quote("india:NSE:RELIANCE", 100, "USD"))
    assert view["current_price"] is None
    assert view["market_value"] is None
    assert "does not match" in view["valuation_error"]


def test_position_view_reports_unavailable_quote_without_inventing_a_price():
    ledger = build_ledger([row(1, "BUY", 1, 100)])
    account = ledger.accounts["india:NSE:RELIANCE"]
    view = position_view(account, None)
    assert view["current_price"] is None
    assert view["market_value"] is None
    assert view["unrealized_pnl"] is None
    assert view["valuation_error"]


def test_detail_view_exposes_history_and_remaining_lots():
    ledger = build_ledger([
        row(1, "BUY", 10, 100, fees=10),
        row(2, "SELL", 4, 150, fees=4, offset_days=1),
    ])
    account = ledger.accounts["india:NSE:RELIANCE"]
    detail = detail_view(account, quote("india:NSE:RELIANCE", 140))
    assert len(detail["purchase_history"]) == 1
    assert len(detail["sale_history"]) == 1
    assert detail["remaining_lots"][0]["remaining_quantity"] == 6
    assert detail["totals"]["total_bought"] == 10
    assert detail["totals"]["total_sold"] == 4
    assert detail["totals"]["realised_pnl"] == 192
    assert detail["position"]["current_price"] == 140
    assert detail["position"]["market_value"] == 840
