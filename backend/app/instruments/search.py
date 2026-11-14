from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.instruments.normalization import (
    alias_variants,
    compact_symbol,
    exchange_priority,
    name_core,
    normalize_query,
    normalized_name,
    title_case_meta,
    upper,
)

_MARKET_PRIORITY = {"india": 0, "global": 1, "crypto": 2}


@dataclass(frozen=True)
class RankedInstrument:
    row: dict[str, Any]
    score: float
    match_type: str

    @property
    def instrument_id(self) -> str:
        return str(self.row.get("instrument_id") or "")


def _row(instrument: dict[str, Any], *, score: float, match_type: str) -> RankedInstrument:
    return RankedInstrument(row=instrument, score=round(score, 4), match_type=match_type)


def _alias_index(aliases: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for entry in aliases:
        instrument_id = str(entry.get("instrument_id") or "")
        alias = str(entry.get("alias") or "")
        if instrument_id and alias:
            index.setdefault(instrument_id, []).append(alias)
    return index


def _score(
    instrument: dict[str, Any],
    query: str,
    aliases: list[str],
) -> tuple[float, str] | None:
    q_raw = normalize_query(query)
    q_upper = upper(q_raw)
    q_compact = compact_symbol(q_raw)
    q_name = normalized_name(q_raw)
    q_core = name_core(q_raw)
    if not q_upper and not q_name:
        return None

    instrument_id = str(instrument.get("instrument_id") or "")
    symbol = upper(str(instrument.get("symbol") or ""))
    provider_symbol = upper(str(instrument.get("provider_symbol") or ""))
    name = str(instrument.get("name") or "")
    name_norm = normalized_name(name)
    name_key = name_core(name)
    symbol_compact = compact_symbol(symbol)

    if instrument_id and q_upper == upper(instrument_id):
        return 220.0, "instrument_id"
    if q_upper and (q_upper == symbol or q_upper == provider_symbol):
        return 200.0, "symbol"
    if q_compact and q_compact == symbol_compact:
        return 198.0, "symbol"

    for alias in aliases:
        alias_upper = upper(alias)
        if q_upper == alias_upper or q_compact == compact_symbol(alias):
            return 190.0, "alias"
        if q_name and q_name == normalized_name(alias):
            return 188.0, "alias"
        if q_core and q_core == name_core(alias):
            return 184.0, "alias"

    if q_name and q_name == name_norm:
        return 180.0, "name"
    if q_core and q_core == name_key:
        return 176.0, "name"

    # Partial matching. Shorter query fragments must match a token boundary to
    # avoid turning one letter into an arbitrary instrument selection.
    if symbol and q_upper and symbol.startswith(q_upper):
        return 150.0 - min(len(symbol) - len(q_upper), 20) * 0.25, "partial_symbol"
    if provider_symbol and q_upper and provider_symbol.startswith(q_upper):
        return 148.0 - min(len(provider_symbol) - len(q_upper), 20) * 0.25, "partial_symbol"

    for alias in aliases:
        alias_upper = upper(alias)
        if q_upper and alias_upper.startswith(q_upper):
            return 140.0, "alias"
        if q_name and normalized_name(alias).startswith(q_name):
            return 136.0, "alias"

    if q_name and len(q_name) >= 3 and name_norm.startswith(q_name):
        return 132.0 - min(len(name_norm) - len(q_name), 30) * 0.2, "partial_name"

    tokens = name_norm.split()
    if q_name and len(q_name) >= 3:
        if any(token.startswith(q_name) for token in tokens):
            return 124.0, "partial_name"
        if q_name in name_norm:
            return 112.0, "partial_name"
    if q_core and len(q_core) >= 3 and q_core in name_key:
        return 108.0, "partial_name"

    if symbol and q_upper and len(q_upper) >= 2 and q_upper in symbol:
        return 92.0, "partial_symbol"
    if q_compact and symbol_compact and len(q_compact) >= 3 and q_compact in symbol_compact:
        return 90.0, "partial_symbol"
    return None


def rank_instruments(
    instruments: Iterable[dict[str, Any]],
    aliases: Iterable[dict[str, Any]],
    query: str,
    *,
    limit: int = 25,
    market: str | None = None,
) -> list[RankedInstrument]:
    alias_map = _alias_index(aliases)
    results: list[RankedInstrument] = []
    for instrument in instruments:
        if market and str(instrument.get("market")) != market:
            continue
        scored = _score(instrument, query, alias_map.get(str(instrument.get("instrument_id")), []))
        if scored is None:
            continue
        results.append(_row(instrument, score=scored[0], match_type=scored[1]))
    results.sort(
        key=lambda item: (
            -item.score,
            _MARKET_PRIORITY.get(str(item.row.get("market")), 9),
            exchange_priority(str(item.row.get("exchange") or "")),
            len(str(item.row.get("symbol") or "")),
            str(item.row.get("symbol") or ""),
        )
    )
    return results[:limit]


def is_equivalent_listing(left: RankedInstrument, right: RankedInstrument) -> bool:
    """True when two rows are the same security listed on two exchanges."""
    a, b = left.row, right.row
    if str(a.get("asset_type")) != "equity" or str(b.get("asset_type")) != "equity":
        return False
    if str(a.get("market")) != str(b.get("market")):
        return False
    if name_core(str(a.get("name") or "")) != name_core(str(b.get("name") or "")):
        return False
    return str(a.get("exchange")) != str(b.get("exchange"))


def candidate_payload(ranked: RankedInstrument) -> dict[str, Any]:
    row = ranked.row
    return {
        "instrument_id": row.get("instrument_id"),
        "symbol": row.get("symbol"),
        "name": row.get("name") or row.get("display_name") or row.get("symbol"),
        "display_name": row.get("display_name") or row.get("name") or row.get("symbol"),
        "market": row.get("market"),
        "exchange": row.get("exchange"),
        "currency": row.get("currency"),
        "asset_type": row.get("asset_type"),
        "provider": row.get("provider"),
        "provider_symbol": row.get("provider_symbol"),
        "base_currency": row.get("base_currency"),
        "quote_currency": row.get("quote_currency"),
        "trading_pair": row.get("trading_pair"),
        "status": row.get("status") or "active",
        "score": ranked.score,
        "match_type": ranked.match_type,
        "asset_label": title_case_meta(
            str(row.get("asset_type") or "equity"), str(row.get("market") or "")
        ),
    }
