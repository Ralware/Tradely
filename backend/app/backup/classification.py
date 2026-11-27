"""Selective, portable backup support for Tradely.

The backup subsystem deliberately separates three classes of data:

* Essential user data (``ESSENTIAL_TABLES``) is exported to a versioned,
  compressed JSON document and is the only data that enters Git.
* Regenerable application data (market bars, analytics snapshots, news and API
  caches) is never exported; it is rebuilt by the existing providers and
  pipelines.
* Temporary data (WAL/SHM files, logs, exports, lock files, partial writes) is
  excluded from both backups and Git.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    """Description of one table that participates in portable backups."""

    name: str
    order_by: str
    natural_key: tuple[str, ...]
    decimal_columns: tuple[str, ...] = ()
    id_column: str | None = "id"
    required: bool = True
    description: str = ""


# Only non-regenerable user data belongs here.  Market candles, indicator
# snapshots, strategy snapshots, news articles and quote caches are excluded.
ESSENTIAL_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        name="instruments",
        order_by="instrument_id",
        natural_key=("instrument_id",),
        id_column=None,
        description="Canonical identities referenced by watchlists and the ledger.",
    ),
    TableSpec(
        name="instrument_aliases",
        order_by="id",
        natural_key=("alias", "instrument_id"),
        description="User/catalogue search aliases.",
    ),
    TableSpec(
        name="watchlist",
        order_by="id",
        natural_key=("symbol", "market", "exchange"),
        description="Watchlists and their display configuration.",
    ),
    TableSpec(
        name="holding_transactions",
        order_by="id",
        natural_key=("idempotency_key",),
        decimal_columns=("quantity", "price", "fees", "amount", "actual_amount"),
        description="Buy/sell/short ledger history with exact financial values.",
    ),
    TableSpec(
        name="catalogue_meta",
        order_by="key",
        natural_key=("key",),
        id_column=None,
        required=False,
        description="Catalogue version metadata.",
    ),
)

ESSENTIAL_TABLE_NAMES: tuple[str, ...] = tuple(spec.name for spec in ESSENTIAL_TABLES)
REQUIRED_TABLE_NAMES: tuple[str, ...] = tuple(
    spec.name for spec in ESSENTIAL_TABLES if spec.required
)
TABLE_SPECS: dict[str, TableSpec] = {spec.name: spec for spec in ESSENTIAL_TABLES}

# Tables that are rebuilt from providers or local pipelines.  They are listed
# here so audit output and backup metadata can explain what was intentionally
# excluded.
REGENERABLE_TABLES: tuple[str, ...] = (
    "market_bars",
    "market_analytics_snapshots",
    "analytics_jobs",
    "news_articles",
    "news_article_symbols",
    "news_symbol_cache",
    "quote_snapshots",
)

TEMPORARY_PATTERNS: tuple[str, ...] = (
    "*.sqlite3-wal",
    "*.sqlite3-shm",
    "*.sqlite3-journal",
    "*.tmp",
    "*.partial",
    "*.lock",
    "*.log",
)


def table_category(name: str) -> str:
    """Return the classification label for a table name."""
    if name in TABLE_SPECS:
        return "A"
    if name in REGENERABLE_TABLES:
        return "B"
    return "C"


def table_description(name: str) -> str:
    spec = TABLE_SPECS.get(name)
    if spec is not None:
        return spec.description
    if name in REGENERABLE_TABLES:
        return "Regenerable cache or market dataset; excluded from portable backups."
    return "Temporary or unclassified table."
