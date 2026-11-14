from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.instruments import (
    canonical_instrument,
    instrument_id_for,
    normalize_symbol,
    parse_instrument_id,
    resolve_exchange,
)
from app.core.models import HoldingTransaction, Instrument, WatchlistItem

SCHEMA_VERSION = 2
_CATALOGUE_COLUMNS: dict[str, str] = {
    "display_name": "TEXT NOT NULL DEFAULT ''",
    "base_currency": "TEXT NOT NULL DEFAULT ''",
    "quote_currency": "TEXT NOT NULL DEFAULT ''",
    "settlement_currency": "TEXT NOT NULL DEFAULT ''",
    "trading_pair": "TEXT NOT NULL DEFAULT ''",
    "provider_instrument_id": "TEXT NOT NULL DEFAULT ''",
    "supported_intervals": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "catalogue_source": "TEXT NOT NULL DEFAULT ''",
    "catalogue_updated_at": "TEXT",
    "is_catalogue": "INTEGER NOT NULL DEFAULT 0",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _instrument_from_row(row: dict[str, Any]) -> Instrument:
    payload = dict(row)
    intervals = payload.get("supported_intervals")
    if isinstance(intervals, str):
        try:
            parsed = json.loads(intervals)
            payload["supported_intervals"] = parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            payload["supported_intervals"] = [item for item in intervals.split(",") if item]
    payload["is_catalogue"] = bool(payload.get("is_catalogue"))
    allowed = set(Instrument.model_fields)
    return Instrument(**{key: value for key, value in payload.items() if key in allowed})



class Database:
    """SQLite persistence for the private single-owner installation.

    Migrations are additive: existing watchlist and ledger rows are preserved,
    canonical instrument columns are backfilled, and no table is recreated.
    """

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
        existed = self.file_path.exists() and self.file_path.stat().st_size > 0
        previous_version = 0
        if existed:
            with self.connect() as connection:
                row = connection.execute("PRAGMA user_version").fetchone()
                previous_version = int(row[0] if row else 0)
        if existed and previous_version < SCHEMA_VERSION:
            self._backup_before_migration(previous_version)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS instruments (
                    instrument_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    market TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_symbol TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    base_currency TEXT NOT NULL DEFAULT '',
                    quote_currency TEXT NOT NULL DEFAULT '',
                    settlement_currency TEXT NOT NULL DEFAULT '',
                    trading_pair TEXT NOT NULL DEFAULT '',
                    provider_instrument_id TEXT NOT NULL DEFAULT '',
                    supported_intervals TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    catalogue_source TEXT NOT NULL DEFAULT '',
                    catalogue_updated_at TEXT,
                    is_catalogue INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instrument_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'alias',
                    created_at TEXT NOT NULL,
                    UNIQUE(alias, instrument_id)
                );
                CREATE INDEX IF NOT EXISTS idx_instrument_aliases_alias
                    ON instrument_aliases(alias);
                CREATE TABLE IF NOT EXISTS catalogue_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    instrument_id TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT '',
                    asset_type TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    provider_symbol TEXT NOT NULL DEFAULT '',
                    resolution_status TEXT NOT NULL DEFAULT 'resolved',
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
                    notes TEXT,
                    instrument_id TEXT NOT NULL DEFAULT '',
                    instrument_name TEXT NOT NULL DEFAULT '',
                    exchange TEXT NOT NULL DEFAULT '',
                    asset_type TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    provider_symbol TEXT NOT NULL DEFAULT '',
                    amount REAL NOT NULL DEFAULT 0,
                    actual_amount REAL NOT NULL DEFAULT 0,
                    quote_provider TEXT NOT NULL DEFAULT '',
                    quote_time TEXT,
                    quote_type TEXT NOT NULL DEFAULT '',
                    quote_status TEXT NOT NULL DEFAULT '',
                    quote_currency TEXT NOT NULL DEFAULT '',
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    resolution_status TEXT NOT NULL DEFAULT 'resolved'
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_symbol
                    ON holding_transactions(symbol, market, trade_time);
                CREATE TABLE IF NOT EXISTS quote_snapshots (
                    instrument_id TEXT PRIMARY KEY,
                    quote_json TEXT NOT NULL,
                    quote_time TEXT,
                    retrieved_at TEXT NOT NULL
                );
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
            self._migrate(connection)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _backup_before_migration(self, previous_version: int) -> Path:
        """Create a consistent backup before an additive schema migration."""
        backup_dir = self.file_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{self.file_path.stem}-v{previous_version}-{stamp}.sqlite3"
        source = sqlite3.connect(self.file_path)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return target

    def latest_backup(self) -> Path | None:
        backup_dir = self.file_path.parent / "backups"
        if not backup_dir.is_dir():
            return None
        backups = sorted(backup_dir.glob(f"{self.file_path.stem}-*.sqlite3"))
        return backups[-1] if backups else None


    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------
    def _columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}

    def _add_column(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        if column not in self._columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate(self, connection: sqlite3.Connection) -> None:
        for column, definition in _CATALOGUE_COLUMNS.items():
            self._add_column(connection, "instruments", column, definition)

        watchlist_columns = {
            "instrument_id": "TEXT NOT NULL DEFAULT ''",
            "currency": "TEXT NOT NULL DEFAULT ''",
            "asset_type": "TEXT NOT NULL DEFAULT ''",
            "provider": "TEXT NOT NULL DEFAULT ''",
            "provider_symbol": "TEXT NOT NULL DEFAULT ''",
            "resolution_status": "TEXT NOT NULL DEFAULT 'resolved'",
        }
        for column, definition in watchlist_columns.items():
            self._add_column(connection, "watchlist", column, definition)

        transaction_columns = {
            "instrument_id": "TEXT NOT NULL DEFAULT ''",
            "instrument_name": "TEXT NOT NULL DEFAULT ''",
            "exchange": "TEXT NOT NULL DEFAULT ''",
            "asset_type": "TEXT NOT NULL DEFAULT ''",
            "provider": "TEXT NOT NULL DEFAULT ''",
            "provider_symbol": "TEXT NOT NULL DEFAULT ''",
            "amount": "REAL NOT NULL DEFAULT 0",
            "actual_amount": "REAL NOT NULL DEFAULT 0",
            "quote_provider": "TEXT NOT NULL DEFAULT ''",
            "quote_time": "TEXT",
            "quote_type": "TEXT NOT NULL DEFAULT ''",
            "quote_status": "TEXT NOT NULL DEFAULT ''",
            "quote_currency": "TEXT NOT NULL DEFAULT ''",
            "idempotency_key": "TEXT NOT NULL DEFAULT ''",
            "resolution_status": "TEXT NOT NULL DEFAULT 'resolved'",
        }
        for column, definition in transaction_columns.items():
            self._add_column(connection, "holding_transactions", column, definition)

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_instrument "
            "ON holding_transactions(instrument_id, trade_time)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_idempotency "
            "ON holding_transactions(idempotency_key) WHERE idempotency_key <> ''"
        )
        connection.execute(
            """UPDATE holding_transactions
               SET amount = CASE WHEN amount = 0 THEN quantity * price ELSE amount END,
                   actual_amount = CASE
                     WHEN actual_amount = 0 THEN quantity * price ELSE actual_amount
                   END
               WHERE amount = 0 OR actual_amount = 0"""
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_instrument "
            "ON watchlist(instrument_id) WHERE instrument_id <> ''"
        )

        # Backfill canonical identity without deleting or rewriting financial data.
        for row in connection.execute(
            "SELECT * FROM watchlist WHERE instrument_id = '' OR instrument_id IS NULL"
        ).fetchall():
            try:
                instrument = canonical_instrument(
                    row["symbol"], row["market"], exchange=row["exchange"] or None,
                    name=row["display_name"] or None,
                )
            except ValueError:
                continue
            self._upsert_instrument(connection, instrument)
            connection.execute(
                """UPDATE watchlist
                   SET instrument_id=?, currency=?, asset_type=?, provider=?, provider_symbol=?,
                       display_name=CASE WHEN display_name='' THEN ? ELSE display_name END
                   WHERE id=?""",
                (instrument.instrument_id, instrument.currency, instrument.asset_type,
                 instrument.provider, instrument.provider_symbol, instrument.name, row["id"]),
            )

        for row in connection.execute(
            "SELECT * FROM holding_transactions WHERE instrument_id = '' OR instrument_id IS NULL"
        ).fetchall():
            try:
                instrument = canonical_instrument(
                    row["symbol"], row["market"], exchange=row["exchange"] or None,
                    name=row["instrument_name"] or None, currency=row["currency"] or None,
                )
            except ValueError:
                continue
            self._upsert_instrument(connection, instrument)
            connection.execute(
                """UPDATE holding_transactions
                   SET instrument_id=?, instrument_name=?, exchange=?, asset_type=?,
                       provider=?, provider_symbol=?
                   WHERE id=?""",
                (instrument.instrument_id, instrument.name, instrument.exchange,
                 instrument.asset_type, instrument.provider, instrument.provider_symbol, row["id"]),
            )

        # Legacy rows that still have no canonical identity are retained and
        # explicitly marked. They are never deleted, rewritten or guessed into a
        # different instrument.
        connection.execute(
            "UPDATE watchlist SET resolution_status='unresolved' "
            "WHERE (instrument_id='' OR instrument_id IS NULL)"
        )
        connection.execute(
            "UPDATE holding_transactions SET resolution_status='unresolved' "
            "WHERE (instrument_id='' OR instrument_id IS NULL)"
        )

    # ------------------------------------------------------------------
    # Instruments
    # ------------------------------------------------------------------
    def _upsert_instrument(self, connection: sqlite3.Connection, instrument: Instrument) -> None:
        now = _utc_now_iso()
        intervals = json.dumps(instrument.supported_intervals or [])
        display_name = instrument.display_name or instrument.name
        base_currency = instrument.base_currency or instrument.currency
        quote_currency = instrument.quote_currency or instrument.currency
        settlement_currency = instrument.settlement_currency or instrument.currency
        catalogue_updated = (
            instrument.catalogue_updated_at.isoformat()
            if isinstance(instrument.catalogue_updated_at, datetime)
            else instrument.catalogue_updated_at
        )
        connection.execute(
            """INSERT INTO instruments
               (instrument_id, symbol, name, market, exchange, currency, asset_type,
                provider, provider_symbol, display_name, base_currency, quote_currency,
                settlement_currency, trading_pair, provider_instrument_id,
                supported_intervals, status, catalogue_source, catalogue_updated_at,
                is_catalogue, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(instrument_id) DO UPDATE SET
                 name=CASE
                   WHEN excluded.name <> excluded.symbol THEN excluded.name
                   ELSE instruments.name
                 END,
                 display_name=CASE
                   WHEN excluded.display_name <> '' THEN excluded.display_name
                   ELSE instruments.display_name
                 END,
                 exchange=excluded.exchange,
                 currency=excluded.currency,
                 asset_type=excluded.asset_type,
                 provider=excluded.provider,
                 provider_symbol=excluded.provider_symbol,
                 base_currency=CASE
                   WHEN excluded.base_currency <> '' THEN excluded.base_currency
                   ELSE instruments.base_currency
                 END,
                 quote_currency=CASE
                   WHEN excluded.quote_currency <> '' THEN excluded.quote_currency
                   ELSE instruments.quote_currency
                 END,
                 settlement_currency=CASE
                   WHEN excluded.settlement_currency <> '' THEN excluded.settlement_currency
                   ELSE instruments.settlement_currency
                 END,
                 trading_pair=CASE
                   WHEN excluded.trading_pair <> '' THEN excluded.trading_pair
                   ELSE instruments.trading_pair
                 END,
                 provider_instrument_id=CASE
                   WHEN excluded.provider_instrument_id <> '' THEN excluded.provider_instrument_id
                   ELSE instruments.provider_instrument_id
                 END,
                 supported_intervals=CASE
                   WHEN excluded.supported_intervals NOT IN ('', '[]')
                     THEN excluded.supported_intervals
                   ELSE instruments.supported_intervals
                 END,
                 status=CASE
                   WHEN excluded.status <> '' THEN excluded.status
                   ELSE instruments.status
                 END,
                 catalogue_source=CASE
                   WHEN excluded.catalogue_source <> '' THEN excluded.catalogue_source
                   ELSE instruments.catalogue_source
                 END,
                 catalogue_updated_at=COALESCE(
                   excluded.catalogue_updated_at, instruments.catalogue_updated_at
                 ),
                 is_catalogue=MAX(instruments.is_catalogue, excluded.is_catalogue),
                 updated_at=excluded.updated_at""",
            (instrument.instrument_id, instrument.symbol, instrument.name, instrument.market,
             instrument.exchange, instrument.currency, instrument.asset_type, instrument.provider,
             instrument.provider_symbol, display_name, base_currency, quote_currency,
             settlement_currency, instrument.trading_pair or "",
             instrument.provider_instrument_id or "", intervals, instrument.status or "active",
             instrument.catalogue_source or "", catalogue_updated, 1 if instrument.is_catalogue else 0,
             now, now),
        )

    def upsert_instrument(self, instrument: Instrument) -> dict[str, Any]:
        with self.connect() as connection:
            self._upsert_instrument(connection, instrument)
            row = connection.execute(
                "SELECT * FROM instruments WHERE instrument_id=?", (instrument.instrument_id,)
            ).fetchone()
        return dict(row)

    # ------------------------------------------------------------------
    # Instrument catalogue
    # ------------------------------------------------------------------
    def seed_catalogue(
        self,
        entries: list[dict[str, Any]],
        *,
        version: str,
        source: str,
    ) -> int:
        """Upsert verified catalogue entries and their aliases.

        Additive and idempotent: existing user-created instruments are kept and
        only the supplied catalogue identities are refreshed.
        """
        now = _utc_now_iso()
        written = 0
        with self.connect() as connection:
            for entry in entries:
                payload = dict(entry)
                aliases = [str(alias) for alias in payload.pop("aliases", []) if str(alias).strip()]
                allowed = set(Instrument.model_fields)
                instrument = Instrument(
                    **{key: value for key, value in payload.items() if key in allowed}
                )
                self._upsert_instrument(connection, instrument)
                for alias in aliases:
                    connection.execute(
                        """INSERT OR IGNORE INTO instrument_aliases
                           (alias, instrument_id, kind, created_at)
                           VALUES(?,?,?,?)""",
                        (alias, instrument.instrument_id, "alias", now),
                    )
                written += 1
            for key, value in (
                ("version", version),
                ("source", source),
                ("updated_at", now),
            ):
                connection.execute(
                    """INSERT INTO catalogue_meta(key, value, updated_at) VALUES(?,?,?)
                       ON CONFLICT(key) DO UPDATE SET
                         value=excluded.value, updated_at=excluded.updated_at""",
                    (key, value, now),
                )
        return written

    def catalogue_meta(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM catalogue_meta WHERE key=?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def catalogue_version(self) -> str | None:
        try:
            return self.catalogue_meta("version")
        except sqlite3.Error:
            return None

    def catalogue_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM instruments WHERE is_catalogue=1"
            ).fetchone()
        return int(row["count"] if row else 0)

    def list_aliases(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT alias, instrument_id, kind, created_at FROM instrument_aliases"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_alias(self, instrument_id: str, alias: str, kind: str = "alias") -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO instrument_aliases
                   (alias, instrument_id, kind, created_at) VALUES(?,?,?,?)""",
                (alias, instrument_id, kind, _utc_now_iso()),
            )

    def upsert_catalogue_entries(self, entries: list[dict[str, Any]]) -> int:
        """Add provider-refreshed listings without changing catalogue version."""
        now = _utc_now_iso()
        written = 0
        with self.connect() as connection:
            for entry in entries:
                payload = dict(entry)
                aliases = [str(alias) for alias in payload.pop("aliases", []) if str(alias).strip()]
                allowed = set(Instrument.model_fields)
                instrument = Instrument(
                    **{key: value for key, value in payload.items() if key in allowed}
                )
                self._upsert_instrument(connection, instrument)
                for alias in aliases:
                    connection.execute(
                        """INSERT OR IGNORE INTO instrument_aliases
                           (alias, instrument_id, kind, created_at) VALUES(?,?,?,?)""",
                        (alias, instrument.instrument_id, "alias", now),
                    )
                written += 1
        return written

    def mark_instrument_status(self, instrument_id: str, status: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE instruments SET status=?, updated_at=? WHERE instrument_id=?",
                (status, _utc_now_iso(), instrument_id),
            )
        return cursor.rowcount > 0

    def resolve_instrument(
        self,
        symbol: str,
        market: str,
        *,
        exchange: str | None = None,
        name: str | None = None,
        currency: str | None = None,
        asset_type: str | None = None,
        provider: str | None = None,
        provider_symbol: str | None = None,
        create: bool = True,
    ) -> Instrument:
        instrument = canonical_instrument(
            symbol, market, exchange=exchange, name=name, currency=currency,
            asset_type=asset_type, provider=provider, provider_symbol=provider_symbol,
        )
        if create:
            self.upsert_instrument(instrument)
        return instrument

    def get_instrument(self, instrument_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_instruments(self, market: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM instruments"
        parameters: list[Any] = []
        if market:
            query += " WHERE market=?"
            parameters.append(market)
        query += " ORDER BY market, symbol"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def search_instruments(self, query: str, market: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        value = query.strip().upper()
        if not value:
            return []
        sql = (
            "SELECT * FROM instruments WHERE (UPPER(symbol) LIKE ? OR UPPER(name) LIKE ?)"
        )
        parameters: list[Any] = [f"%{value}%", f"%{value}%"]
        if market:
            sql += " AND market=?"
            parameters.append(market)
        sql += " ORDER BY CASE WHEN UPPER(symbol)=? THEN 0 ELSE 1 END, symbol LIMIT ?"
        parameters.extend([value, limit])
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def instrument_for_id(self, instrument_id: str) -> dict[str, Any] | None:
        existing = self.get_instrument(instrument_id)
        if existing:
            return existing
        parsed = parse_instrument_id(instrument_id)
        if not parsed:
            return None
        market, exchange, symbol = parsed
        return self.resolve_instrument(symbol, market, exchange=exchange).model_dump()

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------
    def get_watchlist(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT w.*,
                          i.name AS instrument_name,
                          COALESCE(i.currency, w.currency, '') AS instrument_currency,
                          COALESCE(i.asset_type, w.asset_type, '') AS instrument_asset_type,
                          COALESCE(i.provider, w.provider, '') AS instrument_provider,
                          COALESCE(i.provider_symbol, w.provider_symbol, '') AS instrument_provider_symbol,
                          COALESCE((
                              SELECT SUM(CASE WHEN t.side='BUY' THEN t.quantity ELSE -t.quantity END)
                              FROM holding_transactions t
                              WHERE t.instrument_id = w.instrument_id
                          ), 0) AS held_quantity
                   FROM watchlist w
                   LEFT JOIN instruments i ON i.instrument_id = w.instrument_id
                   ORDER BY w.market, w.symbol"""
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["currency"] = item.get("instrument_currency") or item.get("currency") or ""
            item["asset_type"] = item.get("instrument_asset_type") or item.get("asset_type") or ""
            item["provider"] = item.get("instrument_provider") or item.get("provider") or ""
            item["provider_symbol"] = (
                item.get("instrument_provider_symbol") or item.get("provider_symbol") or item["symbol"]
            )
            item["name"] = item.get("instrument_name") or item.get("display_name") or item["symbol"]
            item["is_held"] = float(item.get("held_quantity") or 0) > 1e-9
            item["held_quantity"] = max(0.0, float(item.get("held_quantity") or 0))
            items.append(item)
        return items

    def _watchlist_instrument(self, item: WatchlistItem) -> Instrument:
        if item.instrument_id:
            row = self.get_instrument(item.instrument_id)
            if row is not None:
                instrument = _instrument_from_row(row)
                if item.symbol and item.market:
                    expected = canonical_instrument(
                        item.symbol, item.market, exchange=item.exchange
                    ).instrument_id
                    if expected != instrument.instrument_id:
                        raise ValueError(
                            "instrument_id does not match symbol, market and exchange"
                        )
                return instrument
            parsed = parse_instrument_id(item.instrument_id)
            if parsed is None:
                raise ValueError(f"Unknown instrument {item.instrument_id}")
            market, exchange, symbol = parsed
            return canonical_instrument(symbol, market, exchange=exchange)
        if not item.symbol or not item.market:
            raise ValueError("Provide instrument_id or symbol and market")
        return canonical_instrument(
            item.symbol, item.market, exchange=item.exchange,
            name=item.display_name or None,
        )

    def add_watchlist(self, item: WatchlistItem) -> dict[str, Any]:
        instrument = self._watchlist_instrument(item)
        now = _utc_now_iso()
        with self.connect() as connection:
            self._upsert_instrument(connection, instrument)
            connection.execute(
                """INSERT OR IGNORE INTO watchlist
                   (symbol, market, exchange, display_name, created_at, instrument_id, currency,
                    asset_type, provider, provider_symbol, resolution_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (instrument.symbol, instrument.market, instrument.exchange,
                 item.display_name or instrument.name, now, instrument.instrument_id,
                 instrument.currency, instrument.asset_type, instrument.provider,
                 instrument.provider_symbol, "resolved"),
            )
            connection.execute(
                """UPDATE watchlist
                   SET instrument_id=?, currency=?, asset_type=?, provider=?, provider_symbol=?,
                       resolution_status='resolved',
                       display_name=CASE
                         WHEN display_name='' THEN ?
                         ELSE display_name
                       END
                   WHERE symbol=? AND market=? AND exchange=?""",
                (instrument.instrument_id, instrument.currency, instrument.asset_type,
                 instrument.provider, instrument.provider_symbol, instrument.name,
                 instrument.symbol, instrument.market, instrument.exchange),
            )
            row = connection.execute(
                """SELECT w.*, COALESCE(i.name, w.display_name, w.symbol) AS instrument_name
                   FROM watchlist w LEFT JOIN instruments i ON i.instrument_id=w.instrument_id
                   WHERE w.instrument_id=? OR
                         (w.symbol=? AND w.market=? AND w.exchange=?)""",
                (instrument.instrument_id, instrument.symbol, instrument.market,
                 instrument.exchange),
            ).fetchone()
        result = dict(row)
        result["name"] = result.get("instrument_name") or result.get("display_name") or result["symbol"]
        return result

    def remove_watchlist(self, symbol: str, market: str, exchange: str | None) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE symbol=? AND market=? AND exchange=?",
                (symbol.upper(), market, (exchange or "").upper()),
            )
        return cursor.rowcount > 0

    def remove_watchlist_instrument(self, instrument_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM watchlist WHERE instrument_id=?", (instrument_id,)
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Transactions and FIFO validation
    # ------------------------------------------------------------------
    def _available_quantity(
        self, connection: sqlite3.Connection, instrument_id: str, currency: str,
        trade_time: str, excluding_id: int | None = None,
    ) -> float:
        sql = (
            """SELECT COALESCE(SUM(CASE WHEN side='BUY' THEN quantity ELSE -quantity END), 0) AS quantity
               FROM holding_transactions
               WHERE instrument_id=? AND currency=? AND trade_time<=?"""
        )
        parameters: list[Any] = [instrument_id, currency, trade_time]
        if excluding_id is not None:
            sql += " AND id<>?"
            parameters.append(excluding_id)
        row = connection.execute(sql, parameters).fetchone()
        return float(row["quantity"] or 0)

    def available_quantity(
        self, instrument_id: str, currency: str, trade_time: datetime | str,
    ) -> float:
        value = trade_time.isoformat() if isinstance(trade_time, datetime) else trade_time
        with self.connect() as connection:
            return self._available_quantity(connection, instrument_id, currency, value)

    def _validate_instrument_ledger(
        self, connection: sqlite3.Connection, instrument_id: str, *,
        currency: str | None = None, excluding_id: int | None = None,
    ) -> None:
        sql = (
            "SELECT side, quantity, currency FROM holding_transactions "
            "WHERE instrument_id=?"
        )
        parameters: list[Any] = [instrument_id]
        if currency is not None:
            sql += " AND currency=?"
            parameters.append(currency)
        if excluding_id is not None:
            sql += " AND id<>?"
            parameters.append(excluding_id)
        sql += " ORDER BY trade_time, id"
        quantity = 0.0
        for row in connection.execute(sql, parameters).fetchall():
            if row["side"] == "BUY":
                quantity += float(row["quantity"])
            else:
                quantity -= float(row["quantity"])
                if quantity < -1e-9:
                    raise ValueError(
                        "This change would leave the ledger with a sell larger than recorded holdings"
                    )

    def get_transaction_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM holding_transactions WHERE idempotency_key=?", (key,)
            ).fetchone()
        return dict(row) if row else None

    def add_transaction(self, transaction: HoldingTransaction) -> dict[str, Any]:
        row, _ = self.add_transaction_once(transaction)
        return row

    def add_transaction_once(
        self, transaction: HoldingTransaction,
    ) -> tuple[dict[str, Any], bool]:
        """Insert one ledger row, returning ``(row, was_duplicate)``.

        The idempotency key is enforced by a unique index. A retried request
        returns the original row instead of recording a second transaction.
        """
        instrument = canonical_instrument(
            transaction.symbol, transaction.market, exchange=transaction.exchange,
            name=transaction.name, currency=transaction.currency,
            asset_type=transaction.asset_type, provider=transaction.provider,
            provider_symbol=transaction.provider_symbol,
        )
        if transaction.instrument_id and transaction.instrument_id != instrument.instrument_id:
            raise ValueError("instrument_id does not match symbol, market and exchange")
        currency = transaction.currency.strip().upper()
        with self.connect() as connection:
            self._upsert_instrument(connection, instrument)
            if transaction.idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM holding_transactions WHERE idempotency_key=?",
                    (transaction.idempotency_key,),
                ).fetchone()
                if existing:
                    return dict(existing), True
            if currency != instrument.currency:
                if transaction.side == "SELL":
                    available = self._available_quantity(
                        connection, instrument.instrument_id, currency, transaction.trade_time.isoformat()
                    )
                    if transaction.quantity > available + 1e-9:
                        raise ValueError(
                            f"Sell quantity {transaction.quantity} exceeds recorded holdings {available}"
                        )
                raise ValueError(
                    f"Currency {currency} does not match instrument currency {instrument.currency}"
                )

            if transaction.side == "SELL":
                available = self._available_quantity(
                    connection, instrument.instrument_id, instrument.currency,
                    transaction.trade_time.isoformat(),
                )
                if transaction.quantity > available + 1e-9:
                    raise ValueError(
                        f"Sell quantity {transaction.quantity} exceeds recorded holdings {available}"
                    )

            amount = transaction.amount
            if amount is None or amount <= 0:
                amount = transaction.quantity * transaction.price
            actual_amount = transaction.actual_amount
            if actual_amount is None or actual_amount <= 0:
                actual_amount = transaction.quantity * transaction.price
            cursor = connection.execute(
                """INSERT INTO holding_transactions
                   (symbol, market, side, quantity, price, trade_time, currency, fees, notes,
                    instrument_id, instrument_name, exchange, asset_type, provider, provider_symbol,
                    amount, actual_amount, quote_provider, quote_time, quote_type, quote_status,
                    quote_currency, idempotency_key)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (instrument.symbol, instrument.market, transaction.side,
                 transaction.quantity, transaction.price, transaction.trade_time.isoformat(),
                 instrument.currency, transaction.fees, transaction.notes,
                 instrument.instrument_id, instrument.name, instrument.exchange,
                 instrument.asset_type, instrument.provider, instrument.provider_symbol,
                 amount, actual_amount, transaction.quote_provider or "",
                 transaction.quote_time.isoformat() if transaction.quote_time else None,
                 transaction.quote_type or "", transaction.quote_status or "",
                 transaction.quote_currency or "", transaction.idempotency_key or ""),
            )
            row = connection.execute(
                "SELECT * FROM holding_transactions WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            self._validate_instrument_ledger(connection, instrument.instrument_id)
        return dict(row), False

    def list_transactions(self, instrument_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM holding_transactions"
        parameters: list[Any] = []
        if instrument_id:
            sql += " WHERE instrument_id=?"
            parameters.append(instrument_id)
        sql += " ORDER BY trade_time, id"
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def get_transaction(self, transaction_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM holding_transactions WHERE id=?", (transaction_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_transaction(self, transaction_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM holding_transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Transaction {transaction_id} was not found")
            instrument_id = row["instrument_id"] or instrument_id_for(
                row["symbol"], row["market"], row["exchange"] or "NSE"
            )
            connection.execute("DELETE FROM holding_transactions WHERE id=?", (transaction_id,))
            # Replay all remaining rows for this instrument. A deletion that would
            # create a historical oversell raises; the connection context manager
            # then rolls the deletion back.
            self._validate_instrument_ledger(connection, instrument_id)
        return dict(row)

    # ------------------------------------------------------------------
    # Quote snapshots
    # ------------------------------------------------------------------
    @staticmethod
    def _timestamp_value(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def save_quote_snapshot(self, instrument_id: str, quote: dict[str, Any]) -> None:
        quote_time = quote.get("quote_time")
        retrieved_at = quote.get("retrieved_at") or _utc_now_iso()
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT quote_time FROM quote_snapshots WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
            if existing:
                old = self._timestamp_value(existing["quote_time"])
                new = self._timestamp_value(quote_time)
                if old and new and new < old:
                    return
            connection.execute(
                """INSERT INTO quote_snapshots(instrument_id, quote_json, quote_time, retrieved_at)
                   VALUES(?,?,?,?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     quote_json=excluded.quote_json,
                     quote_time=excluded.quote_time,
                     retrieved_at=excluded.retrieved_at""",
                (instrument_id, json.dumps(quote, default=str), quote_time, retrieved_at),
            )

    def get_quote_snapshot(self, instrument_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM quote_snapshots WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
        if not row:
            return None
        try:
            quote = json.loads(row["quote_json"])
        except (TypeError, ValueError):
            return None
        quote.setdefault("quote_time", row["quote_time"])
        quote.setdefault("retrieved_at", row["retrieved_at"])
        return quote

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def save_signal(self, payload: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO signal_audit
                   (symbol, market, strategy, strategy_version, state, as_of, payload_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (payload["symbol"], payload["market"], payload["strategy"], payload["strategy_version"],
                 payload["state"], payload.get("as_of"), json.dumps(payload, default=str), _utc_now_iso()),
            )
