from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import Settings
from app.core.instruments import (
    TRADINGVIEW_PROVIDER,
    parse_instrument_id,
    split_crypto_pair,
)
from app.instruments.capabilities import capabilities_payload
from app.instruments.catalogue import entry_from_search_result
from app.instruments.catalogue_data import (
    CATALOGUE_SOURCE,
    CATALOGUE_VERSION,
    seeded_instruments,
)
from app.instruments.models import InstrumentSearchResponse
from app.instruments.normalization import normalize_query, title_case_meta, upper
from app.instruments.search import (
    RankedInstrument,
    candidate_payload,
    is_equivalent_listing,
    rank_instruments,
)
from app.providers.tradingview import TradingViewBridge

LEGACY_PROVIDER_NAMES = {
    "TejHQ",
    "Yahoo Finance (yfinance; unofficial)",
    "Binance Spot Public Market Data",
}

NO_MATCH_MESSAGE = "No Supported Instrument Found"
UNAVAILABLE_MESSAGE = "Instrument Recognized — Market Data Unavailable"
AMBIGUOUS_MESSAGE = "Multiple Supported Instruments Found"

_PARTIAL_WINDOW = 10.0
_EXACT_TYPES = {"instrument_id", "symbol", "alias", "name"}


class InstrumentResolutionError(ValueError):
    """The centralized resolver could not produce one safe instrument."""


class InstrumentNotFoundError(InstrumentResolutionError):
    pass


class AmbiguousInstrumentError(InstrumentResolutionError):
    def __init__(self, message: str, candidates: list[dict[str, Any]]):
        super().__init__(message)
        self.candidates = candidates


class InstrumentUnavailableError(InstrumentResolutionError):
    pass


def _parse_intervals(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (TypeError, ValueError):
            return [item for item in value.split(",") if item]
    return []


def instrument_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a stored row into the canonical instrument contract."""
    payload = dict(row)
    payload["name"] = payload.get("name") or payload.get("display_name") or payload.get("symbol") or ""
    payload["display_name"] = payload.get("display_name") or payload.get("name") or payload.get("symbol") or ""
    payload["base_currency"] = payload.get("base_currency") or payload.get("currency")
    payload["quote_currency"] = payload.get("quote_currency") or payload.get("currency")
    payload["settlement_currency"] = payload.get("settlement_currency") or payload.get("currency")
    payload["status"] = payload.get("status") or "active"
    payload["supported_intervals"] = _parse_intervals(payload.get("supported_intervals"))
    payload["aliases"] = list(payload.get("aliases") or [])
    if not payload.get("provider") or payload.get("provider") in LEGACY_PROVIDER_NAMES:
        payload["provider"] = TRADINGVIEW_PROVIDER
    exchange = str(payload.get("exchange") or "").upper()
    symbol = str(payload.get("symbol") or "").upper()
    provider_symbol = str(payload.get("provider_symbol") or "").strip()
    if ":" not in provider_symbol:
        provider_symbol = f"{exchange}:{symbol}" if exchange and symbol else provider_symbol
    payload["provider_symbol"] = provider_symbol
    return payload


class InstrumentResolver:
    """Single source of truth for instrument recognition and provider routing."""

    def __init__(self, settings: Settings, db: Any):
        self.settings = settings
        self.db = db
        self._snapshot: tuple[list[dict[str, Any]], list[dict[str, Any]]] | None = None
        self._snapshot_at = 0.0
        self._bridge: TradingViewBridge | None = None

    def _tradingview(self) -> TradingViewBridge:
        if self._bridge is None:
            self._bridge = TradingViewBridge(self.settings)
        return self._bridge

    def _live_search(
        self,
        query: str,
        *,
        market: str | None = None,
        limit: int = 20,
    ) -> bool:
        """Import exact TradingView search matches not present in the catalogue.

        Failures are deliberately silent: local catalogue resolution must still
        work when the bridge or TradingView is unavailable.
        """
        if not self.settings.tradingview_live_search_enabled or len(query.strip()) < 2:
            return False
        try:
            results = self._tradingview().search(query, limit=min(max(limit, 1), 50))
        except Exception:
            return False
        entries = [
            entry
            for entry in (entry_from_search_result(item) for item in results)
            if entry is not None and (market is None or entry.get("market") == market)
        ]
        if not entries:
            return False
        try:
            self.db.upsert_catalogue_entries(entries)
        except Exception:
            return False
        self.invalidate_cache()
        return True

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------
    def ensure_catalogue(self, *, force: bool = False) -> None:
        stored_version = self.db.catalogue_version()
        count = self.db.catalogue_count()
        if force or stored_version != CATALOGUE_VERSION or count == 0:
            self.db.seed_catalogue(
                seeded_instruments(),
                version=CATALOGUE_VERSION,
                source=CATALOGUE_SOURCE,
            )
        self.invalidate_cache()

    def invalidate_cache(self) -> None:
        self._snapshot = None
        self._snapshot_at = 0.0

    def snapshot(self, *, max_age_seconds: float = 30.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        now = time.monotonic()
        if self._snapshot is None or now - self._snapshot_at > max_age_seconds:
            self._snapshot = (self.db.list_instruments(), self.db.list_aliases())
            self._snapshot_at = now
        return self._snapshot

    def _aliases_for(self, instrument_id: str, aliases: list[dict[str, Any]]) -> list[str]:
        return [
            str(entry.get("alias"))
            for entry in aliases
            if str(entry.get("instrument_id")) == instrument_id
        ]

    def _enrich(self, ranked: RankedInstrument, aliases: list[dict[str, Any]]) -> dict[str, Any]:
        payload = instrument_payload(ranked.row)
        payload["aliases"] = self._aliases_for(str(payload.get("instrument_id")), aliases)
        payload["capabilities"] = capabilities_payload(payload, self.settings)
        payload["asset_label"] = title_case_meta(
            str(payload.get("asset_type") or "equity"), str(payload.get("market") or "")
        )
        return payload

    # ------------------------------------------------------------------
    # Search / resolve
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        limit: int = 25,
        market: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_catalogue()
        clean = normalize_query(query)
        rows, aliases = self.snapshot()
        ranked = rank_instruments(rows, aliases, clean, limit=limit, market=market)
        if not ranked and self._live_search(clean, market=market, limit=limit):
            rows, aliases = self.snapshot(max_age_seconds=0.0)
            ranked = rank_instruments(rows, aliases, clean, limit=limit, market=market)
        candidates = [candidate_payload(item) for item in ranked]
        status = "resolved" if ranked else "not_found"
        instrument = None
        message = None
        if ranked:
            exact_any = any(
                item.match_type in _EXACT_TYPES and item.score >= 176 for item in ranked
            )
            recognized = self._recognized_asset(clean)
            if not exact_any and recognized is not None:
                status = "unsupported"
                message = UNAVAILABLE_MESSAGE
                candidates = [candidate_payload(item) for item in ranked]
            else:
                status, instrument, candidates, message = self._recognition(
                    clean, ranked, aliases, requested_exchange=None, requested_market=market
                )
        else:
            pair = split_crypto_pair(clean.replace("/", "").replace("-", "").replace("_", ""))
            if pair is not None:
                status = "unsupported"
                message = UNAVAILABLE_MESSAGE
            else:
                message = NO_MATCH_MESSAGE
        response = InstrumentSearchResponse(
            query=query,
            normalized=clean,
            status=status,
            message=message,
            instrument=instrument,
            candidates=candidates if status != "resolved" else candidates,
            count=len(candidates),
            recognized=self._recognized_asset(clean) if status in {"unsupported", "not_found"} else None,
        )
        return response.model_dump(mode="json")

    def resolve(
        self,
        query: str | None = None,
        *,
        instrument_id: str | None = None,
        exchange: str | None = None,
        market: str | None = None,
        allow_legacy: bool = False,
    ) -> dict[str, Any]:
        self.ensure_catalogue()
        rows, aliases = self.snapshot()

        if instrument_id:
            row = next(
                (item for item in rows if str(item.get("instrument_id")) == instrument_id),
                None,
            )
            if row is not None:
                ranked = RankedInstrument(row=row, score=220.0, match_type="instrument_id")
                return self._resolved_payload(query or instrument_id, ranked, aliases, [])
            parsed = parse_instrument_id(instrument_id)
            if parsed is not None:
                legacy_market, legacy_exchange, symbol = parsed
                if allow_legacy:
                    resolved = self.db.resolve_instrument(
                        symbol, legacy_market, exchange=legacy_exchange
                    )
                    self.invalidate_cache()
                    return self._resolved_row(query or instrument_id, resolved.model_dump(), aliases)
            return InstrumentSearchResponse(
                query=query or instrument_id,
                normalized=query or instrument_id,
                status="not_found",
                message=NO_MATCH_MESSAGE,
                count=0,
            ).model_dump(mode="json")

        clean = normalize_query(query or "")
        ranked = rank_instruments(
            rows, aliases, clean, limit=40, market=market
        )
        if exchange:
            requested = upper(exchange)
            on_exchange = [
                item for item in ranked if upper(str(item.row.get("exchange") or "")) == requested
            ]
            ranked = on_exchange
        if not ranked:
            if self._live_search(clean, market=market, limit=40):
                rows, aliases = self.snapshot(max_age_seconds=0.0)
                ranked = rank_instruments(rows, aliases, clean, limit=40, market=market)
                if exchange:
                    requested = upper(exchange)
                    ranked = [
                        item for item in ranked
                        if upper(str(item.row.get("exchange") or "")) == requested
                    ]
        if not ranked:
            pair = split_crypto_pair(clean.replace("/", "").replace("-", "").replace("_", ""))
            if pair is not None:
                return InstrumentSearchResponse(
                    query=query or "",
                    normalized=clean,
                    status="unsupported",
                    message=UNAVAILABLE_MESSAGE,
                    count=0,
                    recognized=self._recognized_asset(clean),
                ).model_dump(mode="json")
            if allow_legacy and market:
                # Explicit legacy market/exchange input: create the canonical
                # identity only for that exact request. Search never does this.
                try:
                    resolved = self.db.resolve_instrument(clean, market, exchange=exchange)
                except ValueError:
                    resolved = None
                if resolved is not None:
                    self.invalidate_cache()
                    return self._resolved_row(query or "", resolved.model_dump(), aliases)
            return InstrumentSearchResponse(
                query=query or "",
                normalized=clean,
                status="not_found",
                message=NO_MATCH_MESSAGE,
                count=0,
            ).model_dump(mode="json")

        exact_any = any(
            item.match_type in _EXACT_TYPES and item.score >= 176 for item in ranked
        )
        if not exact_any:
            # A pair such as BTCUSD is recognized from verified base/quote assets
            # but has no verified listing. It is not silently mapped to BTCUSDT.
            recognized = self._recognized_asset(clean)
            if recognized is not None:
                return InstrumentSearchResponse(
                    query=query or "",
                    normalized=clean,
                    status="unsupported",
                    message=UNAVAILABLE_MESSAGE,
                    candidates=[candidate_payload(item) for item in ranked],
                    count=len(ranked),
                    recognized=recognized,
                ).model_dump(mode="json")

        status, instrument, candidates, message = self._recognition(
            clean, ranked, aliases, requested_exchange=exchange, requested_market=market
        )
        if status == "resolved" and allow_legacy and instrument is None:
            status = "not_found"
            message = NO_MATCH_MESSAGE
        return InstrumentSearchResponse(
            query=query or "",
            normalized=clean,
            status=status,
            message=message,
            instrument=instrument,
            candidates=candidates,
            count=len(candidates),
            recognized=None,
        ).model_dump(mode="json")

    def resolve_or_raise(
        self,
        query: str | None = None,
        *,
        instrument_id: str | None = None,
        exchange: str | None = None,
        market: str | None = None,
        allow_legacy: bool = False,
    ) -> dict[str, Any]:
        result = self.resolve(
            query,
            instrument_id=instrument_id,
            exchange=exchange,
            market=market,
            allow_legacy=allow_legacy,
        )
        if result["status"] == "resolved" and result.get("instrument"):
            return result["instrument"]
        if result["status"] == "ambiguous":
            raise AmbiguousInstrumentError(result.get("message") or AMBIGUOUS_MESSAGE, result["candidates"])
        if result["status"] == "unsupported":
            raise InstrumentUnavailableError(result.get("message") or UNAVAILABLE_MESSAGE)
        raise InstrumentNotFoundError(result.get("message") or NO_MATCH_MESSAGE)

    # ------------------------------------------------------------------
    # Direct lookup / capabilities
    # ------------------------------------------------------------------
    def get(self, instrument_id: str) -> dict[str, Any] | None:
        self.ensure_catalogue()
        rows, aliases = self.snapshot()
        row = next(
            (item for item in rows if str(item.get("instrument_id")) == instrument_id),
            None,
        )
        if row is None:
            row = self.db.get_instrument(instrument_id)
        if row is None:
            return None
        payload = instrument_payload(row)
        payload["aliases"] = self._aliases_for(instrument_id, aliases)
        payload["capabilities"] = capabilities_payload(payload, self.settings)
        payload["asset_label"] = title_case_meta(
            str(payload.get("asset_type") or "equity"), str(payload.get("market") or "")
        )
        return payload

    def market_target(
        self,
        *,
        symbol: str | None = None,
        instrument_id: str | None = None,
        market: str | None = None,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        """Resolve the market-data target used by analysis, quotes and backtests.

        Explicit legacy market/exchange input is still honoured for previously
        recorded identifiers. New callers pass only ``instrument_id`` or a
        free-form symbol and let the resolver determine the provider.
        """
        if instrument_id:
            instrument = self.get(instrument_id)
            if instrument is not None:
                return instrument
            parsed = parse_instrument_id(instrument_id)
            if parsed is None:
                raise InstrumentNotFoundError(f"Unknown instrument {instrument_id}")
            legacy_market, legacy_exchange, legacy_symbol = parsed
            if market and market != legacy_market:
                raise InstrumentNotFoundError(
                    f"Instrument {instrument_id} does not belong to the {market} market"
                )
            return instrument_payload(
                self.db.resolve_instrument(
                    legacy_symbol, legacy_market, exchange=legacy_exchange
                ).model_dump()
            )

        if market:
            # Explicit legacy request: preserve existing behaviour and exact
            # exchange, but validate the canonical identity.
            if not symbol:
                raise InstrumentNotFoundError("Provide an instrument or symbol")
            return instrument_payload(
                self.db.resolve_instrument(symbol, market, exchange=exchange).model_dump()
            )

        if not symbol:
            raise InstrumentNotFoundError(NO_MATCH_MESSAGE)
        return self.resolve_or_raise(symbol, exchange=exchange)

    # ------------------------------------------------------------------
    # Internal recognition rules
    # ------------------------------------------------------------------
    def _recognition(
        self,
        query: str,
        ranked: list[RankedInstrument],
        aliases: list[dict[str, Any]],
        *,
        requested_exchange: str | None,
        requested_market: str | None,
    ) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], str | None]:
        if not ranked:
            return "not_found", None, [], NO_MATCH_MESSAGE

        exact = [item for item in ranked if item.match_type in _EXACT_TYPES and item.score >= 176]
        pool = exact if exact else ranked
        top_score = pool[0].score
        close = [item for item in pool if top_score - item.score <= (_PARTIAL_WINDOW if exact else _PARTIAL_WINDOW)]

        # Collapse the same security listed on multiple exchanges. Different
        # companies or trading pairs remain distinct and ambiguous.
        primary = close[0]
        conflicts = [item for item in close[1:] if not is_equivalent_listing(primary, item)]
        if conflicts:
            candidates = [candidate_payload(item) for item in close]
            # An exact symbol wins over a lower-confidence name/alias match, but
            # two different instruments with that exact symbol are ambiguous.
            if len({item.instrument_id for item in close}) > 1:
                return "ambiguous", None, candidates, AMBIGUOUS_MESSAGE
        if requested_exchange:
            requested = upper(requested_exchange)
            match = next(
                (item for item in ranked if upper(str(item.row.get("exchange") or "")) == requested),
                None,
            )
            if match is None:
                return "not_found", None, [candidate_payload(item) for item in ranked], NO_MATCH_MESSAGE
            primary = match

        status = str(primary.row.get("status") or "active").lower()
        if status not in {"active", "listed"}:
            return (
                "unsupported",
                None,
                [candidate_payload(item) for item in close],
                UNAVAILABLE_MESSAGE,
            )
        instrument = self._enrich(primary, aliases)
        candidates = [candidate_payload(item) for item in ranked]
        return "resolved", instrument, candidates, None

    def _resolved_payload(
        self,
        query: str,
        ranked: RankedInstrument,
        aliases: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instrument = self._enrich(ranked, aliases)
        status = str(ranked.row.get("status") or "active").lower()
        if status not in {"active", "listed"}:
            return InstrumentSearchResponse(
                query=query,
                normalized=normalize_query(query),
                status="unsupported",
                message=UNAVAILABLE_MESSAGE,
                candidates=candidates,
                count=len(candidates),
            ).model_dump(mode="json")
        return InstrumentSearchResponse(
            query=query,
            normalized=normalize_query(query),
            status="resolved",
            instrument=instrument,
            candidates=candidates,
            count=len(candidates),
        ).model_dump(mode="json")

    def _resolved_row(
        self,
        query: str,
        row: dict[str, Any],
        aliases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = instrument_payload(row)
        payload["aliases"] = self._aliases_for(str(payload.get("instrument_id")), aliases)
        payload["capabilities"] = capabilities_payload(payload, self.settings)
        payload["asset_label"] = title_case_meta(
            str(payload.get("asset_type") or "equity"), str(payload.get("market") or "")
        )
        return InstrumentSearchResponse(
            query=query,
            normalized=normalize_query(query),
            status="resolved",
            instrument=payload,
            count=1,
        ).model_dump(mode="json")

    def _recognized_asset(self, query: str) -> dict[str, Any] | None:
        compact = query.replace("/", "").replace("-", "").replace("_", "").strip().upper()
        pair = split_crypto_pair(compact)
        if pair is None:
            return None
        base, quote = pair
        return {
            "symbol": compact,
            "asset_class": "cryptocurrency",
            "base_currency": base,
            "quote_currency": quote,
            "trading_pair": f"{base}/{quote}",
            "reason": "No verified Binance Spot listing exists for this exact pair in TradingView.",
        }
