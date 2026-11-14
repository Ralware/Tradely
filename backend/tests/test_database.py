from datetime import datetime, timezone

import pytest

from app.core.database import Database
from app.core.models import HoldingTransaction, WatchlistItem


def test_watchlist_round_trip(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    item = db.add_watchlist(WatchlistItem(symbol="RELIANCE", market="india", exchange="NSE"))
    assert item["symbol"] == "RELIANCE"
    assert len(db.get_watchlist()) == 1
    assert db.remove_watchlist("RELIANCE", "india", "NSE") is True
    assert db.get_watchlist() == []


def test_actual_holdings_ledger_prevents_overselling(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="BUY", quantity=10, price=100,
        trade_time=datetime(2026, 1, 1, tzinfo=timezone.utc), currency="USD", fees=1,
    ))
    with pytest.raises(ValueError, match="exceeds recorded holdings"):
        db.add_transaction(HoldingTransaction(
            symbol="ABC", market="global", side="SELL", quantity=11, price=110,
            trade_time=datetime(2026, 1, 2, tzinfo=timezone.utc), currency="USD", fees=1,
        ))


def test_sell_cannot_use_future_or_different_currency_buys(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="BUY", quantity=10, price=100,
        trade_time=datetime(2026, 2, 1, tzinfo=timezone.utc), currency="USD",
    ))
    with pytest.raises(ValueError, match="exceeds recorded holdings"):
        db.add_transaction(HoldingTransaction(
            symbol="ABC", market="global", side="SELL", quantity=1, price=100,
            trade_time=datetime(2026, 1, 1, tzinfo=timezone.utc), currency="USD",
        ))
    with pytest.raises(ValueError, match="exceeds recorded holdings"):
        db.add_transaction(HoldingTransaction(
            symbol="ABC", market="global", side="SELL", quantity=1, price=100,
            trade_time=datetime(2026, 2, 2, tzinfo=timezone.utc), currency="INR",
        ))
