from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.models import HoldingTransaction, WatchlistItem


class Database:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.file_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(symbol, market, exchange)
                );
                CREATE TABLE IF NOT EXISTS holding_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    price REAL NOT NULL CHECK(price > 0),
                    trade_time TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    fees REAL NOT NULL DEFAULT 0,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_symbol ON holding_transactions(symbol, market, trade_time);
                CREATE TABLE IF NOT EXISTS signal_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    state TEXT NOT NULL,
                    as_of TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def get_watchlist(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM watchlist ORDER BY market, symbol").fetchall()
        return [dict(row) for row in rows]

    def add_watchlist(self, item: WatchlistItem) -> dict[str, Any]:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO watchlist(symbol, market, exchange, display_name, created_at)
                   VALUES(?,?,?,?,?)""",
                (item.symbol.upper(), item.market, (item.exchange or "").upper(), item.display_name or "",
                 datetime.now(timezone.utc).isoformat()),
            )
            row = connection.execute(
                "SELECT * FROM watchlist WHERE symbol=? AND market=? AND exchange=?",
                (item.symbol.upper(), item.market, (item.exchange or "").upper()),
            ).fetchone()
        return dict(row)

    def remove_watchlist(self, symbol: str, market: str, exchange: str | None) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE symbol=? AND market=? AND exchange=?",
                (symbol.upper(), market, (exchange or "").upper()),
            )
        return cursor.rowcount > 0

    def add_transaction(self, transaction: HoldingTransaction) -> dict[str, Any]:
        with self.connect() as connection:
            if transaction.side == "SELL":
                row = connection.execute(
                    """SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END), 0) AS quantity
                       FROM holding_transactions WHERE symbol=? AND market=?""",
                    (transaction.symbol.upper(), transaction.market),
                ).fetchone()
                available = float(row["quantity"] or 0)
                if transaction.quantity > available + 1e-9:
                    raise ValueError(f"Sell quantity {transaction.quantity} exceeds recorded holdings {available}")
            cursor = connection.execute(
                """INSERT INTO holding_transactions
                   (symbol, market, side, quantity, price, trade_time, currency, fees, notes)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (transaction.symbol.upper(), transaction.market, transaction.side,
                 transaction.quantity, transaction.price, transaction.trade_time.isoformat(),
                 transaction.currency.upper(), transaction.fees, transaction.notes),
            )
            row = connection.execute("SELECT * FROM holding_transactions WHERE id=?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def list_transactions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM holding_transactions ORDER BY trade_time, id"
            ).fetchall()
        return [dict(row) for row in rows]

    def save_signal(self, payload: dict[str, Any]) -> None:
        import json

        with self.connect() as connection:
            connection.execute(
                """INSERT INTO signal_audit
                   (symbol, market, strategy, strategy_version, state, as_of, payload_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (payload["symbol"], payload["market"], payload["strategy"], payload["strategy_version"],
                 payload["state"], payload.get("as_of"), json.dumps(payload, default=str),
                 datetime.now(timezone.utc).isoformat()),
            )
