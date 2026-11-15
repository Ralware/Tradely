from datetime import datetime, timezone
import sqlite3

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


def test_short_ledger_allows_cover_and_rejects_overcover_or_reversal(tmp_path):
    db = Database(tmp_path / "short-ledger.sqlite3")
    db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="SELL_SHORT", quantity=5, price=100,
        trade_time=datetime(2026, 1, 1, tzinfo=timezone.utc), currency="USD",
    ))
    assert db.available_short_quantity(
        "global:NASDAQ:ABC", "USD", datetime(2026, 1, 2, tzinfo=timezone.utc),
    ) == 5
    with pytest.raises(ValueError, match="exceeds recorded short holdings"):
        db.add_transaction(HoldingTransaction(
            symbol="ABC", market="global", side="BUY_TO_COVER", quantity=6, price=90,
            trade_time=datetime(2026, 1, 2, tzinfo=timezone.utc), currency="USD",
        ))
    db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="BUY_TO_COVER", quantity=2, price=90,
        trade_time=datetime(2026, 1, 2, tzinfo=timezone.utc), currency="USD",
    ))
    with pytest.raises(ValueError, match="cannot reverse an open SHORT"):
        db.add_transaction(HoldingTransaction(
            symbol="ABC", market="global", side="BUY", quantity=1, price=90,
            trade_time=datetime(2026, 1, 3, tzinfo=timezone.utc), currency="USD",
        ))


def test_existing_sqlite_ledger_migrates_additive_intent_without_losing_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE holding_transactions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               symbol TEXT NOT NULL,
               market TEXT NOT NULL,
               side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
               quantity REAL NOT NULL,
               price REAL NOT NULL,
               trade_time TEXT NOT NULL,
               currency TEXT NOT NULL,
               fees REAL NOT NULL DEFAULT 0,
               notes TEXT
           )"""
    )
    connection.execute(
        """INSERT INTO holding_transactions
           (symbol,market,side,quantity,price,trade_time,currency,fees)
           VALUES('ABC','global','BUY',2,100,'2026-01-01T00:00:00+00:00','USD',1)"""
    )
    connection.commit()
    connection.close()

    db = Database(path)
    rows = db.list_transactions()
    assert len(rows) == 1
    assert rows[0]["side"] == "BUY"
    assert rows[0]["intent"] == "BUY"
    assert rows[0]["quantity"] == 2
    db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="SELL", quantity=2, price=110,
        trade_time=datetime(2026, 1, 2, tzinfo=timezone.utc), currency="USD",
    ))
    inserted = db.add_transaction(HoldingTransaction(
        symbol="ABC", market="global", side="SELL_SHORT", quantity=1, price=90,
        trade_time=datetime(2026, 1, 3, tzinfo=timezone.utc), currency="USD",
    ))
    assert inserted["side"] == "SELL"
    assert inserted["intent"] == "SELL_SHORT"
