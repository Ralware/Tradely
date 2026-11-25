from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.instruments import (
    TRADINGVIEW_PROVIDER,
    canonical_instrument,
    instrument_id_for,
    parse_instrument_id,
)
from app.core.models import (
    HOLDING_QUANTITY_TOLERANCE,
    HoldingTransaction,
    Instrument,
    WatchlistItem,
)

SCHEMA_VERSION = 6
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
    return datetime.now(UTC).isoformat()


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _timestamp_microseconds(value: Any) -> int | None:
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        return None
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _normalized_news_timestamp(value: Any) -> str | None:
    parsed = _parse_utc_datetime(value)
    if parsed is not None:
        return parsed.isoformat()
    return value if isinstance(value, str) and value else None


def _news_date_filters(date_from: str | None, date_to: str | None) -> tuple[str, list[int]]:
    clauses: list[str] = []
    values: list[int] = []
    if date_from:
        start = _timestamp_microseconds(date_from)
        if start is None:
            raise ValueError("Invalid news date_from timestamp")
        clauses.append("a.published_at_us>=?")
        values.append(start)
    if date_to:
        end = _timestamp_microseconds(date_to)
        if end is None:
            raise ValueError("Invalid news date_to timestamp")
        clauses.append("a.published_at_us<=?")
        values.append(end)
    return (" AND " + " AND ".join(clauses) if clauses else ""), values


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
                    intent TEXT NOT NULL DEFAULT '',
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
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
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

    def save_news_refresh(
        self,
        *,
        instrument_id: str,
        symbol: str,
        articles: list[dict[str, Any]],
        attempted_at: str,
        expires_at: str,
    ) -> None:
        """Upsert normalized Yahoo articles and associate them with one canonical instrument."""
        with self.connect() as connection:
            for article in articles:
                yahoo_id = article.get("yahoo_id")
                canonical_url = article.get("canonical_url")
                existing = None
                if yahoo_id:
                    existing = connection.execute(
                        "SELECT article_id FROM news_articles WHERE yahoo_id=? LIMIT 1", (yahoo_id,)
                    ).fetchone()
                if existing is None and canonical_url:
                    existing = connection.execute(
                        "SELECT article_id FROM news_articles WHERE canonical_url=? LIMIT 1", (canonical_url,)
                    ).fetchone()
                article_id = str(existing["article_id"]) if existing else str(article.get("article_id") or "")
                published_raw = article.get("published_at")
                published_at = _normalized_news_timestamp(published_raw)
                published_at_us = _timestamp_microseconds(published_at)
                timestamp_supplied = published_raw is not None
                if not article_id:
                    seed = f"yahoo:{yahoo_id}" if yahoo_id else f"url:{canonical_url}" if canonical_url else f"fingerprint:{article.get('fingerprint', '')}"
                    article_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()
                now = attempted_at
                if existing:
                    connection.execute(
                        """UPDATE news_articles SET
                           yahoo_id=COALESCE(yahoo_id,?), title=?,
                           summary=COALESCE(?,summary), publisher=COALESCE(?,publisher),
                           published_at=COALESCE(?,published_at),
                           published_at_us=CASE WHEN ? THEN ? ELSE published_at_us END,
                           article_url=?,
                           canonical_url=COALESCE(?,canonical_url),
                           thumbnail_url=COALESCE(?,thumbnail_url), related_symbols_json=?,
                           primary_symbol=COALESCE(primary_symbol,?), source=?, last_updated_at=?
                           WHERE article_id=?""",
                        (yahoo_id, article["title"], article.get("summary"), article.get("publisher"),
                         published_at, int(timestamp_supplied), published_at_us, article["article_url"], canonical_url,
                         article.get("thumbnail_url"), json.dumps(article.get("related_symbols") or []),
                         symbol, article.get("source") or "Yahoo Finance", now, article_id),
                    )
                else:
                    connection.execute(
                        """INSERT INTO news_articles
                           (article_id,yahoo_id,title,summary,publisher,published_at,published_at_us,article_url,
                            canonical_url,thumbnail_url,related_symbols_json,primary_symbol,source,
                            first_seen_at,last_updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (article_id, yahoo_id, article["title"], article.get("summary"),
                         article.get("publisher"), published_at, published_at_us, article["article_url"],
                         canonical_url, article.get("thumbnail_url"),
                         json.dumps(article.get("related_symbols") or []), symbol,
                         article.get("source") or "Yahoo Finance", now, now),
                    )
                connection.execute(
                    """INSERT INTO news_article_symbols
                       (article_id,instrument_id,symbol,associated_at) VALUES(?,?,?,?)
                       ON CONFLICT(article_id,instrument_id) DO UPDATE SET
                         symbol=excluded.symbol,associated_at=excluded.associated_at""",
                    (article_id, instrument_id, symbol, now),
                )
            connection.execute(
                """INSERT INTO news_symbol_cache
                   (instrument_id,symbol,last_attempt_at,last_success_at,expires_at,status,
                    provider_status,error_code,failure_count)
                   VALUES(?,?,?,? ,?,'ok','available',NULL,0)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     symbol=excluded.symbol,last_attempt_at=excluded.last_attempt_at,
                     last_success_at=excluded.last_success_at,expires_at=excluded.expires_at,
                     status='ok',provider_status='available',error_code=NULL,failure_count=0""",
                (instrument_id, symbol, attempted_at, attempted_at, expires_at),
            )
            # Retain at most 500 recent article links for each canonical instrument.
            connection.execute(
                """DELETE FROM news_article_symbols WHERE instrument_id=? AND article_id IN (
                   SELECT article_id FROM news_article_symbols WHERE instrument_id=?
                   ORDER BY associated_at DESC LIMIT -1 OFFSET 500)""",
                (instrument_id, instrument_id),
            )
            connection.execute(
                """DELETE FROM news_articles WHERE article_id NOT IN
                   (SELECT article_id FROM news_article_symbols)"""
            )

    def begin_news_refresh(self, *, instrument_id: str, symbol: str, attempted_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO news_symbol_cache
                   (instrument_id,symbol,last_attempt_at,last_success_at,expires_at,status,
                    provider_status,error_code,failure_count)
                   VALUES(?,?,?,NULL,NULL,'refreshing','pending',NULL,0)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     symbol=excluded.symbol,last_attempt_at=excluded.last_attempt_at,
                     status='refreshing',provider_status='pending',error_code=NULL""",
                (instrument_id, symbol, attempted_at),
            )

    def mark_news_refresh_failure(
        self, *, instrument_id: str, symbol: str, attempted_at: str,
        provider_status: str, error_code: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO news_symbol_cache
                   (instrument_id,symbol,last_attempt_at,last_success_at,expires_at,status,
                    provider_status,error_code,failure_count)
                   VALUES(?,?,?,NULL,NULL,'error',?,?,1)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     symbol=excluded.symbol,last_attempt_at=excluded.last_attempt_at,
                     status='error',provider_status=excluded.provider_status,
                     error_code=excluded.error_code,failure_count=news_symbol_cache.failure_count+1""",
                (instrument_id, symbol, attempted_at, provider_status, error_code[:80]),
            )

    def news_cache_state(self, instrument_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM news_symbol_cache WHERE instrument_id=?", (instrument_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_news(
        self, *, instrument_id: str | None = None, symbol: str | None = None,
        query: str | None = None, date_from: str | None = None, date_to: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT DISTINCT a.* FROM news_articles a JOIN news_article_symbols s USING(article_id) WHERE 1=1"
        values: list[Any] = []
        if instrument_id:
            sql += " AND s.instrument_id=?"
            values.append(instrument_id)
        elif symbol:
            sql += " AND UPPER(s.symbol)=UPPER(?)"
            values.append(symbol)
        if query:
            sql += " AND (a.title LIKE ? OR COALESCE(a.summary,'') LIKE ? OR COALESCE(a.publisher,'') LIKE ?)"
            pattern = f"%{query}%"
            values.extend((pattern, pattern, pattern))
        date_clause, date_values = _news_date_filters(date_from, date_to)
        sql += date_clause
        values.extend(date_values)
        sql += " ORDER BY a.published_at_us IS NULL ASC, a.published_at_us DESC, a.first_seen_at DESC LIMIT ? OFFSET ?"
        values.extend((limit, offset))
        with self.connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["related_symbols"] = json.loads(item.pop("related_symbols_json") or "[]")
            except (TypeError, ValueError):
                item["related_symbols"] = []
            result.append(item)
        return result

    def count_news(
        self, *, instrument_id: str | None = None, symbol: str | None = None,
        query: str | None = None, date_from: str | None = None, date_to: str | None = None,
    ) -> int:
        sql = "SELECT COUNT(DISTINCT a.article_id) FROM news_articles a JOIN news_article_symbols s USING(article_id) WHERE 1=1"
        values: list[Any] = []
        if instrument_id:
            sql += " AND s.instrument_id=?"
            values.append(instrument_id)
        elif symbol:
            sql += " AND UPPER(s.symbol)=UPPER(?)"
            values.append(symbol)
        if query:
            sql += " AND (a.title LIKE ? OR COALESCE(a.summary,'') LIKE ? OR COALESCE(a.publisher,'') LIKE ?)"
            pattern = f"%{query}%"
            values.extend((pattern, pattern, pattern))
        date_clause, date_values = _news_date_filters(date_from, date_to)
        sql += date_clause
        values.extend(date_values)
        with self.connect() as connection:
            row = connection.execute(sql, values).fetchone()
        return int(row[0] if row else 0)

    def list_news_cache_states(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM news_symbol_cache ORDER BY last_attempt_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]


    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------
    def _columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}

    def _add_column(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        if column not in self._columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_bars (
                instrument_id TEXT NOT NULL, interval TEXT NOT NULL, timestamp TEXT NOT NULL,
                open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
                volume REAL NOT NULL, source TEXT NOT NULL, adjustment_status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(instrument_id, interval, timestamp, adjustment_status, source)
            );
            CREATE INDEX IF NOT EXISTS idx_market_bars_range
                ON market_bars(instrument_id, interval, timestamp);
            CREATE TABLE IF NOT EXISTS market_analytics_snapshots (
                snapshot_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, interval TEXT NOT NULL,
                ohlcv_fingerprint TEXT NOT NULL, indicator_version TEXT NOT NULL,
                indicator_dependency_version TEXT NOT NULL, rating_version TEXT NOT NULL,
                provider_identity TEXT NOT NULL, source_identity TEXT NOT NULL,
                adjustment_status TEXT NOT NULL, latest_candle_at TEXT NOT NULL,
                candle_count INTEGER NOT NULL, generated_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL, status TEXT NOT NULL, payload BLOB NOT NULL,
                payload_checksum TEXT NOT NULL,
                UNIQUE(instrument_id, interval, ohlcv_fingerprint, schema_version)
            );
            CREATE INDEX IF NOT EXISTS idx_analytics_latest
                ON market_analytics_snapshots(instrument_id, interval, status, generated_at);
            CREATE TABLE IF NOT EXISTS strategy_snapshots (
                strategy_snapshot_id TEXT PRIMARY KEY, market_snapshot_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL, interval TEXT NOT NULL, ohlcv_fingerprint TEXT NOT NULL,
                strategy_version TEXT NOT NULL, strategy_configuration_hash TEXT NOT NULL,
                direction_mode TEXT NOT NULL, position_side TEXT NOT NULL,
                generated_at TEXT NOT NULL, status TEXT NOT NULL, payload BLOB NOT NULL,
                payload_checksum TEXT NOT NULL,
                UNIQUE(instrument_id, interval, ohlcv_fingerprint, strategy_version,
                       strategy_configuration_hash, direction_mode, position_side)
            );
            CREATE INDEX IF NOT EXISTS idx_strategy_snapshots_parent
                ON strategy_snapshots(market_snapshot_id, status);
            CREATE TABLE IF NOT EXISTS analytics_jobs (
                job_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL, interval TEXT NOT NULL,
                job_type TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'QUEUED', scheduled_at TEXT NOT NULL,
                started_at TEXT, completed_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5, lease_until TEXT, worker_id TEXT,
                last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_analytics_jobs_dispatch
                ON analytics_jobs(status, scheduled_at, priority DESC, created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_jobs_active_identity
                ON analytics_jobs(instrument_id, interval, job_type)
                WHERE status IN ('QUEUED','RUNNING');
            CREATE TABLE IF NOT EXISTS news_articles (
                article_id TEXT PRIMARY KEY, yahoo_id TEXT UNIQUE, title TEXT NOT NULL,
                summary TEXT, publisher TEXT, published_at TEXT, published_at_us INTEGER, article_url TEXT NOT NULL,
                canonical_url TEXT UNIQUE, thumbnail_url TEXT, related_symbols_json TEXT NOT NULL DEFAULT '[]',
                primary_symbol TEXT, source TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_published ON news_articles(published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_article_yahoo ON news_articles(yahoo_id);
            CREATE TABLE IF NOT EXISTS news_article_symbols (
                article_id TEXT NOT NULL REFERENCES news_articles(article_id) ON DELETE CASCADE,
                instrument_id TEXT NOT NULL, symbol TEXT NOT NULL, associated_at TEXT NOT NULL,
                PRIMARY KEY(article_id,instrument_id)
            );
            CREATE INDEX IF NOT EXISTS idx_news_symbol_date
                ON news_article_symbols(instrument_id,associated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_symbol_text ON news_article_symbols(symbol);
            CREATE TABLE IF NOT EXISTS news_symbol_cache (
                instrument_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, last_attempt_at TEXT,
                last_success_at TEXT, expires_at TEXT, status TEXT NOT NULL,
                provider_status TEXT NOT NULL, error_code TEXT, failure_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_news_cache_expiry ON news_symbol_cache(expires_at);
            """
        )
        self._add_column(connection, "news_articles", "published_at_us", "INTEGER")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_news_published_us ON news_articles(published_at_us DESC)")
        for row in connection.execute(
            "SELECT article_id,published_at FROM news_articles WHERE published_at_us IS NULL AND published_at IS NOT NULL"
        ).fetchall():
            timestamp_us = _timestamp_microseconds(row["published_at"])
            if timestamp_us is not None:
                connection.execute(
                    "UPDATE news_articles SET published_at_us=? WHERE article_id=?",
                    (timestamp_us, row["article_id"]),
                )

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
            "intent": "TEXT NOT NULL DEFAULT ''",
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
               "UPDATE holding_transactions SET intent=side WHERE intent=''"
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

    def backfill_tradingview_metadata(self) -> int:
        """Idempotently move stored provider metadata to TradingView identities.

        Ledger quantities, prices and historical ``quote_provider`` audit fields
        are never rewritten. Only the forward-looking instrument provider and
        its exchange-qualified symbol are migrated.
        """
        legacy = (
            "TejHQ",
            "Yahoo Finance (yfinance; unofficial)",
            "Binance Spot Public Market Data",
        )
        now = _utc_now_iso()
        updated = 0
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE instruments
                   SET provider=?,
                       provider_symbol=CASE
                         WHEN instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> ''
                           THEN exchange || ':' || symbol
                         ELSE provider_symbol
                       END,
                       provider_instrument_id=CASE
                         WHEN instr(COALESCE(provider_instrument_id, ''), ':') = 0
                              AND exchange <> '' AND symbol <> ''
                           THEN exchange || ':' || symbol
                         ELSE provider_instrument_id
                       END,
                       updated_at=?
                   WHERE provider IN (?,?,?)
                      OR (instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> '')""",
                (TRADINGVIEW_PROVIDER, now, *legacy),
            )
            updated += cursor.rowcount
            cursor = connection.execute(
                """UPDATE watchlist
                   SET provider=?,
                       provider_symbol=CASE
                         WHEN instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> ''
                           THEN exchange || ':' || symbol
                         ELSE provider_symbol
                       END
                   WHERE provider IN (?,?,?, '')
                      OR (instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> '')""",
                (TRADINGVIEW_PROVIDER, *legacy),
            )
            updated += cursor.rowcount
            cursor = connection.execute(
                """UPDATE holding_transactions
                   SET provider=?,
                       provider_symbol=CASE
                         WHEN instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> ''
                           THEN exchange || ':' || symbol
                         ELSE provider_symbol
                       END
                   WHERE instrument_id <> ''
                     AND (provider IN (?,?,?) OR provider = ''
                          OR (instr(provider_symbol, ':') = 0 AND exchange <> '' AND symbol <> ''))""",
                (TRADINGVIEW_PROVIDER, *legacy),
            )
            updated += cursor.rowcount
        return updated

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
                              SELECT SUM(CASE COALESCE(NULLIF(t.intent,''), t.side)
                                  WHEN 'BUY' THEN t.quantity
                                  WHEN 'SELL' THEN -t.quantity
                                  WHEN 'SELL_SHORT' THEN -t.quantity
                                  WHEN 'BUY_TO_COVER' THEN t.quantity
                                  ELSE 0 END)
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
            held_quantity = float(item.get("held_quantity") or 0)
            item["is_held"] = abs(held_quantity) > HOLDING_QUANTITY_TOLERANCE
            item["held_quantity"] = held_quantity
            item["held_side"] = (
                "LONG" if held_quantity > HOLDING_QUANTITY_TOLERANCE
                else "SHORT" if held_quantity < -HOLDING_QUANTITY_TOLERANCE
                else None
            )
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
            """SELECT COALESCE(SUM(CASE COALESCE(NULLIF(intent,''), side)
                   WHEN 'BUY' THEN quantity WHEN 'SELL' THEN -quantity ELSE 0 END), 0) AS quantity
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

    def _available_short_quantity(
        self, connection: sqlite3.Connection, instrument_id: str, currency: str,
        trade_time: str,
    ) -> float:
        row = connection.execute(
            """SELECT COALESCE(SUM(CASE COALESCE(NULLIF(intent,''), side)
                   WHEN 'SELL_SHORT' THEN quantity
                   WHEN 'BUY_TO_COVER' THEN -quantity
                   ELSE 0 END), 0) AS quantity
               FROM holding_transactions
               WHERE instrument_id=? AND currency=? AND trade_time<=?""",
            (instrument_id, currency, trade_time),
        ).fetchone()
        return float(row["quantity"] or 0)

    def available_short_quantity(
        self, instrument_id: str, currency: str, trade_time: datetime | str,
    ) -> float:
        value = trade_time.isoformat() if isinstance(trade_time, datetime) else trade_time
        with self.connect() as connection:
            return self._available_short_quantity(connection, instrument_id, currency, value)

    def position_side_at(
        self, instrument_id: str, currency: str, trade_time: datetime | str,
    ) -> str | None:
        long_quantity = self.available_quantity(instrument_id, currency, trade_time)
        short_quantity = self.available_short_quantity(instrument_id, currency, trade_time)
        if long_quantity > HOLDING_QUANTITY_TOLERANCE:
            return "LONG"
        if short_quantity > HOLDING_QUANTITY_TOLERANCE:
            return "SHORT"
        return None

    def _validate_instrument_ledger(
        self, connection: sqlite3.Connection, instrument_id: str, *,
        currency: str | None = None, excluding_id: int | None = None,
    ) -> None:
        sql = (
            "SELECT side, intent, quantity, currency FROM holding_transactions "
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
        balances: dict[str, dict[str, Decimal]] = {}
        for row in connection.execute(sql, parameters).fetchall():
            side = str(row["intent"] or row["side"]).upper()
            quantity = Decimal(str(row["quantity"]))
            balance = balances.setdefault(row["currency"], {"long": Decimal(0), "short": Decimal(0)})
            if side == "BUY":
                if balance["short"] > HOLDING_QUANTITY_TOLERANCE:
                    raise ValueError(
                        "BUY cannot reverse an open SHORT exposure; use BUY_TO_COVER first"
                    )
                balance["long"] += quantity
            elif side == "SELL":
                if balance["long"] <= HOLDING_QUANTITY_TOLERANCE or balance["long"] + HOLDING_QUANTITY_TOLERANCE < quantity:
                    raise ValueError(
                        f"Sell quantity {quantity} exceeds recorded holdings {balance['long']}"
                    )
                remaining = balance["long"] - quantity
                balance["long"] = remaining if remaining > HOLDING_QUANTITY_TOLERANCE else Decimal(0)
            elif side == "SELL_SHORT":
                if balance["long"] > HOLDING_QUANTITY_TOLERANCE:
                    raise ValueError(
                        "SELL_SHORT cannot reverse an open LONG exposure; use SELL first"
                    )
                balance["short"] += quantity
            elif side == "BUY_TO_COVER":
                if balance["short"] <= HOLDING_QUANTITY_TOLERANCE or balance["short"] + HOLDING_QUANTITY_TOLERANCE < quantity:
                    raise ValueError(
                        f"Cover quantity {quantity} exceeds recorded short holdings "
                        f"{balance['short']}"
                    )
                remaining = balance["short"] - quantity
                balance["short"] = remaining if remaining > HOLDING_QUANTITY_TOLERANCE else Decimal(0)
            else:
                raise ValueError(f"Unsupported transaction intent: {side}")

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
                raise ValueError(
                    f"Currency {currency} does not match instrument currency {instrument.currency}"
                )

            amount = transaction.amount
            if amount is None or amount <= 0:
                amount = transaction.quantity * transaction.price
            actual_amount = transaction.actual_amount
            if actual_amount is None or actual_amount <= 0:
                actual_amount = transaction.quantity * transaction.price
            side = transaction.side
            legacy_side = "BUY" if side in {"BUY", "BUY_TO_COVER"} else "SELL"
            cursor = connection.execute(
                """INSERT INTO holding_transactions
                   (symbol, market, side, intent, quantity, price, trade_time, currency, fees, notes,
                    instrument_id, instrument_name, exchange, asset_type, provider, provider_symbol,
                    amount, actual_amount, quote_provider, quote_time, quote_type, quote_status,
                    quote_currency, idempotency_key)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (instrument.symbol, instrument.market, legacy_side, side,
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
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
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
