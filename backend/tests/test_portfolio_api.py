from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.models import TradingRules
from app.main import app

BASE = datetime(2026, 2, 1, 9, 30, tzinfo=timezone.utc)


class FakeQuoteService:
    def __init__(self):
        self.fail = False
        self.prices = {
            "india:NSE:RELIANCE": 120.0,
            "crypto:BINANCE:BTCUSDT": 70000.0,
            "global:NASDAQ:AAPL": 210.0,
        }
        self.calls: list[str] = []
        self.transaction_times: list[datetime] = []
        self.quote_forces: list[bool] = []

    def quote_for(self, instrument, *, force=False):
        payload = instrument if isinstance(instrument, dict) else instrument.model_dump()
        instrument_id = payload.get("instrument_id") or ""
        self.calls.append(instrument_id)
        quote = {
            **payload,
            "quote_type": "end_of_day",
            "freshness": "eod",
            "quote_time": (BASE + timedelta(hours=6)).isoformat(),
            "retrieved_at": BASE.isoformat(),
            "day_change": 1.0,
            "day_change_pct": 0.9,
            "error": None,
        }
        if self.fail:
            quote.update({
                "price": None, "quote_type": "unavailable",
                "freshness": "unavailable", "error": "provider offline",
            })
        else:
            quote["price"] = self.prices.get(instrument_id, 100.0)
        return quote

    def quote_for_transaction(self, instrument, trade_time, *, now=None, force=True):
        self.transaction_times.append(trade_time)
        self.quote_forces.append(force)
        quote = self.quote_for(instrument, force=True)
        current = now or datetime.now(timezone.utc)
        if current - trade_time > timedelta(minutes=10):
            quote = {**quote, "quote_type": "historical", "freshness": "historical"}
        return quote

    def trading_rules_for(self, instrument):
        payload = instrument if isinstance(instrument, dict) else instrument.model_dump()
        if payload.get("market") == "crypto":
            return TradingRules(
                quantity_step=0.00001,
                min_quantity=0.00001,
                min_notional=5,
                fractional=True,
                source="Test Binance Spot Exchange Rules",
            )
        if payload.get("market") == "india":
            return TradingRules(
                quantity_step=1,
                min_quantity=1,
                min_notional=1,
                fractional=False,
                source="NSE/BSE Whole Shares",
            )
        return TradingRules(
            quantity_step=0.000001,
            min_quantity=0.000001,
            min_notional=1,
            fractional=True,
            source="Fractional-Share Market Default",
        )

    def quotes_for(self, instruments, *, force=False):
        seen = set()
        output = []
        for instrument in instruments:
            payload = instrument if isinstance(instrument, dict) else instrument.model_dump()
            instrument_id = payload.get("instrument_id") or ""
            if instrument_id in seen:
                continue
            seen.add(instrument_id)
            output.append(self.quote_for(payload, force=force))
        return output

    def invalidate(self, instrument_id):
        return None

    def subscribe_stream(self, instruments):
        return "token"

    def unsubscribe_stream(self, token):
        return None

    def shutdown(self):
        return None


@pytest.fixture()
def api(tmp_path, monkeypatch):
    original_db = app.state.db
    original_quotes = app.state.quote_service
    db = Database(tmp_path / "portfolio-test.sqlite3")
    quotes = FakeQuoteService()
    app.state.db = db
    app.state.quote_service = quotes
    client = TestClient(app)
    try:
        yield SimpleNamespace(client=client, db=db, quotes=quotes)
    finally:
        app.state.db = original_db
        app.state.quote_service = original_quotes


def trade(client, **overrides):
    payload = {
        "instrument_id": "india:NSE:RELIANCE",
        "side": "BUY",
        "amount": 1200,
        "currency": "INR",
        "fees": 10,
        "trade_time": BASE.isoformat(),
        "notes": None,
        "idempotency_key": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return client.post("/api/portfolio/transactions", json=payload)


def test_instrument_resolution_returns_canonical_identity(api):
    response = api.client.get("/api/instruments/resolve", params={
        "symbol": "reliance", "market": "india", "exchange": "NSE",
    })
    assert response.status_code == 200
    instrument = response.json()["instrument"]
    assert instrument["instrument_id"] == "india:NSE:RELIANCE"
    assert instrument["currency"] == "INR"
    assert instrument["provider_symbol"] == "RELIANCE"

    bad = api.client.get("/api/instruments/resolve", params={
        "symbol": "BTC", "market": "crypto",
    })
    assert bad.status_code == 422


def test_buy_derives_quantity_from_amount_and_records_fifo(api):
    response = trade(api.client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["quote_available"] is True
    transaction = payload["transaction"]
    assert transaction["instrument_id"] == "india:NSE:RELIANCE"
    assert transaction["amount"] == 1200
    assert transaction["actual_amount"] == 1200
    assert transaction["quantity"] == 10
    assert transaction["price"] == 120
    assert transaction["quote_provider"]
    assert transaction["quote_time"]
    assert transaction["quote_type"] == "historical"
    assert payload["position"]["quantity"] == 10
    assert payload["position"]["average_cost"] == 121
    assert payload["position"]["market_value"] == 1200
    assert payload["position"]["unrealized_pnl"] == -10

    summary = payload["summary"]
    bucket = summary["currencies"][0]
    assert bucket["currency"] == "INR"
    assert bucket["total_invested"] == 1210
    assert bucket["realized_pnl"] + bucket["unrealized_pnl"] == bucket["total_pnl"]

    watchlist = api.client.get("/api/watchlist").json()["items"]
    assert len(watchlist) == 1
    assert watchlist[0]["instrument_id"] == "india:NSE:RELIANCE"
    assert watchlist[0]["is_held"] is True

    # A second BUY must not duplicate the held instrument in the watchlist.
    assert trade(api.client).status_code == 200
    assert len(api.client.get("/api/watchlist").json()["items"]) == 1


def test_quote_failure_blocks_recording_without_writing_a_transaction(api):
    api.quotes.fail = True
    response = trade(api.client)
    assert response.status_code == 422
    assert "usable market quote" in response.json()["detail"]
    assert api.client.get("/api/portfolio/transactions").json()["transactions"] == []


def test_sell_rejects_amount_above_available_market_value(api):
    assert trade(api.client).status_code == 200
    oversell = trade(api.client, side="SELL", amount=2500)
    assert oversell.status_code == 422
    assert "exceeds the available holdings market value" in oversell.json()["detail"]
    assert len(api.client.get("/api/portfolio/transactions").json()["transactions"]) == 1


def test_partial_sell_keeps_position_and_reports_fifo_realised_pnl(api):
    assert trade(api.client).status_code == 200
    api.quotes.prices["india:NSE:RELIANCE"] = 130.0
    response = trade(api.client, side="SELL", amount=520, fees=4,
                     trade_time=(BASE + timedelta(days=1)).isoformat())
    assert response.status_code == 200
    payload = response.json()
    position = payload["position"]
    assert payload["transaction"]["quantity"] == 4
    assert position["quantity"] == 6
    assert position["realised_pnl"] == 32
    assert position["cost_basis"] == 726
    assert payload["summary"]["currencies"][0]["realized_pnl"] == 32

    positions = api.client.get("/api/portfolio/positions").json()["positions"]
    assert len(positions) == 1
    details = api.client.get("/api/portfolio/positions/india:NSE:RELIANCE").json()
    assert len(details["purchase_history"]) == 1
    assert len(details["sale_history"]) == 1
    assert details["totals"]["total_sold"] == 4


def test_short_intents_are_manual_only_and_cover_uses_short_fifo(api):
    opened = trade(
        api.client, intent="SELL_SHORT", amount=1200, fees=10,
    )
    assert opened.status_code == 200
    result = opened.json()
    assert result["transaction"]["intent"] == "SELL_SHORT"
    assert result["transaction"]["side"] == "SELL"
    assert result["purpose"] == "research/manual exposure tracking only"
    assert result["order_execution"] is False
    assert result["spot_borrow_claims"] is False
    assert result["position"]["position_side"] == "SHORT"
    assert result["position"]["quantity"] == -10
    assert result["position"]["cost_basis"] == 1190
    held = api.client.get("/api/watchlist").json()["items"][0]
    assert held["is_held"] is True
    assert held["held_quantity"] == -10
    assert held["held_side"] == "SHORT"
    listed = api.client.get("/api/portfolio/transactions").json()
    assert listed["mode"] == "manual-research-exposure-ledger"
    assert listed["transactions"][0]["intent"] == "SELL_SHORT"
    assert listed["transactions"][0]["side"] == "SELL"

    preview = api.client.post("/api/portfolio/transactions/preview", json={
        "instrument_id": "india:NSE:RELIANCE",
        "intent": "BUY_TO_COVER",
        "amount": 600,
        "currency": "INR",
        "fees": 6,
        "trade_time": (BASE + timedelta(days=1)).isoformat(),
    }).json()
    assert preview["valid"] is True
    assert preview["intent"] == "BUY_TO_COVER"
    assert preview["side"] == "BUY"
    assert preview["max_close_amount"] == 1200
    assert preview["total_cash_cost"] is None

    api.quotes.prices["india:NSE:RELIANCE"] = 100
    covered = trade(
        api.client, intent="BUY_TO_COVER", amount=600, fees=6,
        trade_time=(BASE + timedelta(days=1)).isoformat(),
    )
    assert covered.status_code == 200
    result = covered.json()
    assert result["transaction"]["intent"] == "BUY_TO_COVER"
    assert result["position"]["position_side"] == "SHORT"
    assert result["position"]["quantity"] == -4
    assert result["position"]["realised_pnl"] == 108
    assert result["position"]["cost_basis"] == 476
    assert result["position"]["market_value"] == 400
    assert result["calculation"]["total_cash_cost"] is None
    assert result["calculation"]["net_proceeds"] is None


def test_short_intents_reject_overcovers_and_long_short_reversals(api):
    assert trade(api.client, intent="SELL_SHORT", amount=1200).status_code == 200
    overcover = trade(
        api.client, intent="BUY_TO_COVER", amount=2400,
        trade_time=(BASE + timedelta(days=1)).isoformat(),
    )
    assert overcover.status_code == 422
    assert "exceeds the available holdings market value" in overcover.json()["detail"]

    reverse = trade(
        api.client, intent="BUY", amount=120,
        trade_time=(BASE + timedelta(days=1)).isoformat(),
    )
    assert reverse.status_code == 422
    assert "cannot reverse an open SHORT" in reverse.json()["detail"]


def test_full_sell_closes_position_but_ledger_remains(api):
    assert trade(api.client).status_code == 200
    api.quotes.prices["india:NSE:RELIANCE"] = 110.0
    response = trade(api.client, side="SELL", amount=1100, fees=0,
                     trade_time=(BASE + timedelta(days=1)).isoformat())
    assert response.status_code == 200
    assert api.client.get("/api/portfolio/positions").json()["positions"] == []
    assert len(api.client.get("/api/portfolio/transactions").json()["transactions"]) == 2
    details = api.client.get("/api/portfolio/positions/india:NSE:RELIANCE").json()
    assert details["position"]["quantity"] == 0
    assert details["totals"]["realised_pnl"] is not None


def test_delete_rejects_removing_a_buy_that_created_an_unbacked_sell(api):
    assert trade(api.client).status_code == 200
    assert trade(api.client, side="SELL", amount=600, fees=0,
                 trade_time=(BASE + timedelta(days=1)).isoformat()).status_code == 200
    buy_id = api.client.get("/api/portfolio/transactions").json()["transactions"][0]["id"]
    response = api.client.delete(f"/api/portfolio/transactions/{buy_id}")
    assert response.status_code == 422
    assert len(api.client.get("/api/portfolio/transactions").json()["transactions"]) == 2


def test_delete_sell_restores_open_position(api):
    assert trade(api.client).status_code == 200
    sell = trade(api.client, side="SELL", amount=600, fees=0,
                 trade_time=(BASE + timedelta(days=1)).isoformat())
    sell_id = sell.json()["transaction"]["id"]
    response = api.client.delete(f"/api/portfolio/transactions/{sell_id}")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["transactions"]) == 1
    assert payload["positions"][0]["quantity"] == 10


def test_summary_keeps_currencies_separate(api):
    assert trade(api.client).status_code == 200
    crypto = trade(
        api.client, instrument_id="crypto:BINANCE:BTCUSDT", market="crypto",
        amount=35000, currency="USDT", fees=5,
    )
    assert crypto.status_code == 200
    assert crypto.json()["transaction"]["quantity"] == 0.5
    summary = api.client.get("/api/portfolio/summary").json()
    currencies = {bucket["currency"] for bucket in summary["currencies"]}
    assert currencies == {"INR", "USDT"}
    assert summary["currency_conversion"] == "unavailable"


def test_preview_derives_quantity_precision_and_remainder(api):
    api.client.get("/api/instruments/resolve", params={
        "symbol": "BTCUSDT", "market": "crypto", "exchange": "BINANCE",
    })
    api.quotes.prices["crypto:BINANCE:BTCUSDT"] = 100000.0
    response = api.client.post("/api/portfolio/transactions/preview", json={
        "instrument_id": "crypto:BINANCE:BTCUSDT",
        "side": "BUY",
        "amount": 100.001,
        "currency": "USDT",
        "fees": 0.5,
        "trade_time": datetime.now(timezone.utc).isoformat(),
        "notes": None,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["quantity"] == 0.001
    assert payload["actual_amount"] == 100
    assert payload["remaining_amount"] == pytest.approx(0.001)
    assert payload["total_cash_cost"] == pytest.approx(100.5)
    assert payload["trading_rules"]["quantity_step"] == 0.00001
    assert payload["quote"]["quote_type"] == "end_of_day"


def test_preview_reuses_cached_quote_while_recording_forces_a_refresh(api):
    api.client.get("/api/instruments/resolve", params={
        "symbol": "RELIANCE", "market": "india", "exchange": "NSE",
    })
    api.quotes.quote_forces.clear()
    preview = api.client.post("/api/portfolio/transactions/preview", json={
        "instrument_id": "india:NSE:RELIANCE",
        "side": "BUY",
        "amount": 1200,
        "currency": "INR",
        "fees": 0,
        "trade_time": datetime.now(timezone.utc).isoformat(),
        "notes": None,
    })
    assert preview.status_code == 200
    assert preview.json()["valid"] is True
    assert api.quotes.quote_forces == [False]

    assert trade(api.client).status_code == 200
    assert api.quotes.quote_forces[-1] is True


def test_preview_rejects_sell_above_available_holdings(api):
    assert trade(api.client).status_code == 200
    response = api.client.post("/api/portfolio/transactions/preview", json={
        "instrument_id": "india:NSE:RELIANCE",
        "side": "SELL",
        "amount": 2500,
        "currency": "INR",
        "fees": 0,
        "trade_time": datetime.now(timezone.utc).isoformat(),
        "notes": None,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert "exceeds the available holdings market value" in payload["error"]


def test_idempotent_submission_does_not_duplicate_transaction(api):
    key = "repeat-request-123"
    first = trade(api.client, idempotency_key=key)
    second = trade(api.client, idempotency_key=key)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["transaction"]["id"] == first.json()["transaction"]["id"]
    assert len(api.client.get("/api/portfolio/transactions").json()["transactions"]) == 1


def test_currency_mismatch_is_rejected(api):
    response = trade(api.client, currency="USD")
    assert response.status_code == 422
    assert "does not match instrument currency" in response.json()["detail"]


def test_market_quotes_endpoint_and_watchlist_quotes(api):
    assert trade(api.client).status_code == 200
    response = api.client.get("/api/market/quotes", params={
        "instrument_id": ["india:NSE:RELIANCE", "india:NSE:RELIANCE"],
    })
    assert response.status_code == 200
    quotes = response.json()["quotes"]
    assert len(quotes) == 1
    assert quotes[0]["price"] == 120

    watchlist_quotes = api.client.get("/api/watchlist/quotes").json()["quotes"]
    assert len(watchlist_quotes) == 1
    assert watchlist_quotes[0]["instrument_id"] == "india:NSE:RELIANCE"
