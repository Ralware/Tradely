from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.database import Database
from app.core.models import WatchlistItem
from app.instruments.capabilities import capabilities_for
from app.instruments.catalogue_data import CATALOGUE_VERSION
from app.instruments.resolver import (
    NO_MATCH_MESSAGE,
    UNAVAILABLE_MESSAGE,
    InstrumentResolver,
)
from fastapi.testclient import TestClient


def make_resolver(tmp_path, **settings_overrides) -> InstrumentResolver:
    settings = Settings(
        _env_file=None,
        database_path=str(tmp_path / "catalogue.sqlite3"),
        tradingview_live_search_enabled=False,
        **settings_overrides,
    )
    db = Database(tmp_path / "catalogue.sqlite3")
    resolver = InstrumentResolver(settings, db)
    resolver.ensure_catalogue()
    return resolver


@pytest.fixture()
def resolver(tmp_path):
    return make_resolver(tmp_path)


# ----------------------------------------------------------------------
# Recognition
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("RELIANCE", "india:NSE:RELIANCE"),
        ("TCS", "india:NSE:TCS"),
        ("INFY", "india:NSE:INFY"),
        ("AAPL", "global:NASDAQ:AAPL"),
        ("MSFT", "global:NASDAQ:MSFT"),
        ("BTCUSDT", "crypto:BINANCE:BTCUSDT"),
        ("ETHUSDT", "crypto:BINANCE:ETHUSDT"),
    ],
)
def test_exact_symbols_resolve_to_canonical_identity(resolver, query, expected):
    result = resolver.resolve(query)
    assert result["status"] == "resolved"
    assert result["instrument"]["instrument_id"] == expected
    assert result["instrument"]["symbol"] == expected.split(":")[-1]
    assert result["instrument"]["provider_symbol"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Reliance Industries", "india:NSE:RELIANCE"),
        ("Tata Consultancy Services", "india:NSE:TCS"),
        ("Infosys", "india:NSE:INFY"),
        ("Apple Inc.", "global:NASDAQ:AAPL"),
        ("Microsoft Corporation", "global:NASDAQ:MSFT"),
        ("Bitcoin", "crypto:BINANCE:BTCUSDT"),
        ("Ethereum", "crypto:BINANCE:ETHUSDT"),
    ],
)
def test_company_and_asset_names_resolve(resolver, query, expected):
    result = resolver.resolve(query)
    assert result["status"] == "resolved"
    assert result["instrument"]["instrument_id"] == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Reli", "india:NSE:RELIANCE"),
        ("Micros", "global:NASDAQ:MSFT"),
        ("Nvid", "global:NASDAQ:NVDA"),
    ],
)
def test_partial_queries_resolve_when_unambiguous(resolver, query, expected):
    result = resolver.resolve(query)
    assert result["status"] == "resolved"
    assert result["instrument"]["instrument_id"] == expected


@pytest.mark.parametrize("query", ["  reliance  ", "ReLiAnCe", "\tMSFT\n", " aapl "])
def test_case_and_whitespace_are_normalized(resolver, query):
    result = resolver.resolve(query)
    assert result["status"] == "resolved"


def test_ambiguous_query_returns_candidates_and_no_instrument(resolver):
    result = resolver.resolve("Bit")
    assert result["status"] == "ambiguous"
    assert result["instrument"] is None
    assert result["message"]
    candidate_ids = {item["instrument_id"] for item in result["candidates"]}
    assert "crypto:BINANCE:BTCUSDT" in candidate_ids
    assert "crypto:BINANCE:BCHUSDT" in candidate_ids
    # A candidate list is compact: it carries the fields needed to disambiguate.
    sample = result["candidates"][0]
    assert {"symbol", "name", "market", "exchange", "currency", "asset_type"} <= set(sample)


def test_unlisted_crypto_pair_is_unsupported_and_never_remapped(resolver):
    result = resolver.resolve("BTCUSD")
    assert result["status"] == "unsupported"
    assert result["message"] == UNAVAILABLE_MESSAGE
    assert result["instrument"] is None
    assert result["recognized"]["base_currency"] == "BTC"
    assert result["recognized"]["quote_currency"] == "USD"
    assert result["recognized"]["trading_pair"] == "BTC/USD"
    # BTCUSD must not silently become BTCUSDT.
    assert all(
        item["instrument_id"] != "crypto:BINANCE:BTCUSD"
        for item in result["candidates"]
    )


def test_unknown_query_returns_no_supported_instrument(resolver):
    result = resolver.resolve("XYZ")
    assert result["status"] == "not_found"
    assert result["message"] == NO_MATCH_MESSAGE
    assert result["candidates"] == []


def test_crypto_pair_quote_is_never_assumed(resolver):
    assert resolver.resolve("ETHBTC")["instrument"]["instrument_id"] == "crypto:BINANCE:ETHBTC"
    assert resolver.resolve("BTCUSDC")["instrument"]["instrument_id"] == "crypto:BINANCE:BTCUSDC"
    # A bare base asset resolves only to a verified listed pair.
    assert resolver.resolve("ETH")["instrument"]["instrument_id"] == "crypto:BINANCE:ETHUSDT"


def test_search_returns_candidates_and_resolution(resolver):
    result = resolver.search("Microsof")
    assert result["status"] == "resolved"
    assert result["instrument"]["instrument_id"] == "global:NASDAQ:MSFT"
    assert any(item["instrument_id"] == "global:NASDAQ:MSFT" for item in result["candidates"])

    # "Micro" also matches Micron, so it is reported as ambiguous rather than
    # silently choosing Microsoft.
    ambiguous = resolver.search("Micro")
    assert ambiguous["status"] == "ambiguous"
    assert ambiguous["instrument"] is None

    empty = resolver.search("No Such Company")
    assert empty["status"] == "not_found"
    assert empty["message"] == NO_MATCH_MESSAGE


# ----------------------------------------------------------------------
# Cross-application identity
# ----------------------------------------------------------------------
def test_canonical_identity_is_shared_by_search_watchlist_and_market_target(resolver):
    resolved = resolver.resolve("Reliance")
    instrument = resolved["instrument"]
    instrument_id = instrument["instrument_id"]
    assert instrument_id == "india:NSE:RELIANCE"

    item = resolver.db.add_watchlist(WatchlistItem(instrument_id=instrument_id))
    assert item["instrument_id"] == instrument_id
    assert item["symbol"] == "RELIANCE"
    assert item["currency"] == "INR"

    watchlist = resolver.db.get_watchlist()
    assert [entry["instrument_id"] for entry in watchlist] == [instrument_id]
    assert watchlist[0]["name"] == "Reliance Industries"

    target = resolver.market_target(instrument_id=instrument_id)
    assert target["instrument_id"] == instrument_id
    assert target["provider_symbol"] == "NSE:RELIANCE"

    fetched = resolver.get(instrument_id)
    assert fetched["instrument_id"] == instrument_id
    assert fetched["capabilities"]["instrument_id"] == instrument_id


def test_watchlist_accepts_legacy_identity_and_deduplicates(resolver):
    legacy = resolver.db.add_watchlist(
        WatchlistItem(symbol="reliance", market="india", exchange="NSE")
    )
    assert legacy["instrument_id"] == "india:NSE:RELIANCE"
    again = resolver.db.add_watchlist(WatchlistItem(instrument_id="india:NSE:RELIANCE"))
    assert again["instrument_id"] == "india:NSE:RELIANCE"
    assert len(resolver.db.get_watchlist()) == 1
    assert resolver.db.remove_watchlist_instrument("india:NSE:RELIANCE") is True
    assert resolver.db.get_watchlist() == []


def test_watchlist_rejects_conflicting_identity(resolver):
    with pytest.raises(ValueError, match="does not match"):
        resolver.db.add_watchlist(
            WatchlistItem(
                instrument_id="india:NSE:RELIANCE", symbol="TCS", market="india", exchange="NSE"
            )
        )


def test_catalogue_seed_is_versioned_and_repeatable(resolver):
    assert resolver.db.catalogue_version() == CATALOGUE_VERSION
    assert resolver.db.catalogue_count() >= 100
    resolver.ensure_catalogue(force=True)
    assert resolver.db.catalogue_version() == CATALOGUE_VERSION
    # Re-seeding refreshes listings without duplicating them.
    ids = [item["instrument_id"] for item in resolver.db.list_instruments()]
    assert len(ids) == len(set(ids))


# ----------------------------------------------------------------------
# Provider routing and capabilities
# ----------------------------------------------------------------------
@pytest.mark.parametrize("query", ["RELIANCE", "AAPL", "BTCUSDT"])
def test_provider_routing_is_derived_from_the_resolved_instrument(resolver, query):
    instrument = resolver.resolve(query)["instrument"]
    assert instrument["provider"] == "TradingView (unofficial)"
    assert instrument["capabilities"]["provider_key"] == "tradingview"
    assert ":" in instrument["provider_symbol"]


def test_capabilities_reflect_the_single_tradingview_provider(resolver):
    india = resolver.get("india:NSE:RELIANCE")["capabilities"]
    assert india["provider_key"] == "tradingview"
    assert {"1d", "1h", "1m"} <= set(india["supported_intervals"])
    assert india["real_time_streaming"] is False
    assert india["adjusted_history"] is True
    assert india["backtesting_eligible"] is True
    assert india["news"] is False
    assert any("15 minutes delayed" in item for item in india["data_limitations"])

    global_caps = resolver.get("global:NASDAQ:AAPL")["capabilities"]
    assert global_caps["provider_key"] == "tradingview"
    assert global_caps["adjusted_history"] is True
    assert global_caps["backtesting_eligible"] is True

    crypto = resolver.get("crypto:BINANCE:BTCUSDT")["capabilities"]
    assert crypto["provider_key"] == "tradingview"
    assert crypto["real_time_streaming"] is False
    assert crypto["backtesting_eligible"] is True
    assert {"1m", "4h", "1d"} <= set(crypto["supported_intervals"])
    assert crypto["quantity"]["fractional"] is True
    assert "TradingView symbol metadata" in crypto["quantity"]["source"]


def test_india_history_is_always_split_adjusted(tmp_path):
    resolver = make_resolver(tmp_path)
    capabilities = resolver.get("india:NSE:RELIANCE")["capabilities"]
    assert capabilities["adjusted_history"] is True
    assert capabilities["backtesting_eligible"] is True
    assert capabilities["quote_freshness"] == "real_time_or_delayed"


def test_inactive_instrument_is_recognized_but_unavailable(resolver):
    resolver.db.mark_instrument_status("crypto:BINANCE:BTCUSDT", "delisted")
    resolver.invalidate_cache()

    result = resolver.resolve("BTCUSDT")
    assert result["status"] == "unsupported"
    assert result["message"] == UNAVAILABLE_MESSAGE

    capabilities = resolver.get("crypto:BINANCE:BTCUSDT")["capabilities"]
    assert capabilities["quote_available"] is False
    assert capabilities["historical_ohlcv"] is False
    assert any("delisted" in limitation for limitation in capabilities["data_limitations"])


def test_capabilities_are_explicit_for_equity_quantity_rules(resolver):
    instrument = resolver.resolve("RELIANCE")["instrument"]
    capabilities = capabilities_for(instrument, resolver.settings)
    assert capabilities.quantity.quantity_step == 1
    assert capabilities.quantity.fractional is False
    assert capabilities.quote_freshness == "real_time_or_delayed"


# ----------------------------------------------------------------------
# HTTP surface
# ----------------------------------------------------------------------
@pytest.fixture()
def instrument_api(tmp_path):
    from app.main import app

    original_db = app.state.db
    original_resolver = app.state.instrument_resolver
    settings = Settings(
        _env_file=None,
        database_path=str(tmp_path / "api.sqlite3"),
        tradingview_live_search_enabled=False,
    )
    db = Database(tmp_path / "api.sqlite3")
    resolver = InstrumentResolver(settings, db)
    resolver.ensure_catalogue()
    app.state.db = db
    app.state.instrument_resolver = resolver
    client = TestClient(app, base_url="http://127.0.0.1")
    try:
        yield SimpleNamespace(client=client, db=db, resolver=resolver)
    finally:
        app.state.db = original_db
        app.state.instrument_resolver = original_resolver


def test_api_search_and_resolve_share_one_identity(instrument_api):
    search = instrument_api.client.get("/api/instruments/search", params={"q": "Reliance"})
    assert search.status_code == 200
    search_payload = search.json()
    assert search_payload["status"] == "resolved"

    resolved = instrument_api.client.get("/api/instruments/resolve", params={"query": "Reliance"})
    assert resolved.status_code == 200
    resolved_payload = resolved.json()
    assert resolved_payload["resolved"] is True
    assert resolved_payload["instrument"]["instrument_id"] == "india:NSE:RELIANCE"
    assert (
        search_payload["instrument"]["instrument_id"]
        == resolved_payload["instrument"]["instrument_id"]
    )


def test_api_unsupported_pair_is_a_valid_response_with_clear_message(instrument_api):
    response = instrument_api.client.get(
        "/api/instruments/resolve", params={"query": "BTCUSD"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unsupported"
    assert payload["message"] == UNAVAILABLE_MESSAGE
    assert payload["resolved"] is False


def test_api_watchlist_accepts_instrument_id_only(instrument_api):
    created = instrument_api.client.post(
        "/api/watchlist", json={"instrument_id": "global:NASDAQ:MSFT"}
    )
    assert created.status_code == 200
    item = created.json()
    assert item["instrument_id"] == "global:NASDAQ:MSFT"
    assert item["symbol"] == "MSFT"
    assert item["currency"] == "USD"

    items = instrument_api.client.get("/api/watchlist").json()["items"]
    assert [entry["instrument_id"] for entry in items] == ["global:NASDAQ:MSFT"]

    removed = instrument_api.client.delete("/api/watchlist/instruments/global:NASDAQ:MSFT")
    assert removed.status_code == 200
    assert removed.json()["removed"] is True
    assert instrument_api.client.get("/api/watchlist").json()["items"] == []


# ----------------------------------------------------------------------
# Migration and data preservation
# ----------------------------------------------------------------------
LEGACY_SCHEMA = """
CREATE TABLE instruments (
    instrument_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,
    exchange TEXT NOT NULL,
    currency TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(symbol, market, exchange)
);
CREATE TABLE holding_transactions (
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
PRAGMA user_version = 1;
"""


def _legacy_database(path):
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
        connection.execute(
            "INSERT INTO instruments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "india:NSE:RELIANCE", "RELIANCE", "RELIANCE", "india", "NSE", "INR",
                "equity", "TejHQ", "RELIANCE", now, now,
            ),
        )
        connection.executemany(
            "INSERT INTO watchlist(symbol, market, exchange, display_name, created_at) "
            "VALUES(?,?,?,?,?)",
            [
                ("RELIANCE", "india", "NSE", "Reliance Industries", now),
                ("BTC", "crypto", "", "Bitcoin", now),
            ],
        )
        connection.executemany(
            "INSERT INTO holding_transactions"
            "(symbol, market, side, quantity, price, trade_time, currency, fees, notes) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            [
                ("RELIANCE", "india", "BUY", 10, 100.0, now, "INR", 1.5, "first lot"),
                ("RELIANCE", "india", "BUY", 5, 110.0, now, "INR", 2.5, "second lot"),
                ("BTC", "crypto", "BUY", 0.25, 20000.0, now, "USDT", 0.0, "legacy unresolved"),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def test_migration_preserves_ledger_and_marks_unresolved_rows(tmp_path):
    path = tmp_path / "tradely.sqlite3"
    _legacy_database(path)

    db = Database(path)
    assert db.catalogue_version() is None or db.catalogue_count() == 0

    transactions = db.list_transactions()
    assert len(transactions) == 3

    resolved = [row for row in transactions if row["instrument_id"]]
    unresolved = [row for row in transactions if not row["instrument_id"]]
    assert len(resolved) == 2
    assert len(unresolved) == 1
    assert unresolved[0]["resolution_status"] == "unresolved"
    assert unresolved[0]["symbol"] == "BTC"
    assert unresolved[0]["quantity"] == 0.25

    first = resolved[0]
    assert first["quantity"] == 10
    assert first["price"] == 100.0
    assert first["fees"] == 1.5
    assert first["notes"] == "first lot"
    assert first["currency"] == "INR"
    assert first["instrument_id"] == "india:NSE:RELIANCE"
    assert first["amount"] == pytest.approx(1000.0)
    assert first["actual_amount"] == pytest.approx(1000.0)

    watchlist = db.get_watchlist()
    by_symbol = {item["symbol"]: item for item in watchlist}
    assert by_symbol["RELIANCE"]["instrument_id"] == "india:NSE:RELIANCE"
    assert by_symbol["RELIANCE"]["resolution_status"] == "resolved"
    assert by_symbol["BTC"]["instrument_id"] == ""
    assert by_symbol["BTC"]["resolution_status"] == "unresolved"

    backup = db.latest_backup()
    assert backup is not None and backup.exists()
    source = sqlite3.connect(backup)
    try:
        columns = {row[1] for row in source.execute("PRAGMA table_info(holding_transactions)")}
        assert "instrument_id" not in columns  # backup holds the pre-migration schema
        assert source.execute("SELECT COUNT(*) FROM holding_transactions").fetchone()[0] == 3
        assert source.execute("SELECT quantity FROM holding_transactions WHERE id=1").fetchone()[0] == 10
    finally:
        source.close()


def test_migration_is_additive_and_repeatable(tmp_path):
    path = tmp_path / "repeat.sqlite3"
    _legacy_database(path)
    db = Database(path)
    first_rows = db.list_transactions()
    backups_after_first = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups_after_first) == 1

    reopened = Database(path)
    assert len(reopened.list_transactions()) == len(first_rows) == 3
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    assert reopened.get_transaction(first_rows[0]["id"])["quantity"] == first_rows[0]["quantity"]
