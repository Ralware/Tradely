from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from app.providers.yahoo_news import YahooFinanceNewsProvider, YahooNewsError

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def yahoo_symbol_for(instrument: dict[str, Any]) -> str:
    """Map known Tradely exchange identities to Yahoo symbols without guessing listings."""
    symbol = str(instrument.get("symbol") or "").strip().upper()
    market = str(instrument.get("market") or "")
    exchange = str(instrument.get("exchange") or "").upper()
    if not symbol:
        raise ValueError("Instrument has no symbol")
    if symbol.startswith("^") or re.search(r"\.(NS|BO)$", symbol):
        return symbol
    if market == "india":
        if exchange in {"NSE", "NSI"}:
            return f"{symbol}.NS"
        if exchange in {"BSE", "BOM"}:
            return f"{symbol}.BO"
        raise ValueError(f"No verified Yahoo listing mapping for India exchange {exchange!r}")
    if market == "crypto":
        base = str(instrument.get("base_currency") or "").upper()
        quote = str(instrument.get("quote_currency") or "").upper()
        if not base:
            match = re.fullmatch(r"([A-Z0-9]+?)(USDT|USDC|USD)", symbol)
            base = match.group(1) if match else ""
            quote = quote or (match.group(2) if match else "")
        if base and quote in {"USD", "USDT", "USDC"}:
            return f"{base}-USD"
        if re.fullmatch(r"[A-Z0-9]+-[A-Z0-9]+", symbol):
            return symbol
        raise ValueError("No verified Yahoo Finance symbol mapping for this crypto pair")
    # Yahoo Finance uses a hyphen for the internally seeded BRK.B ticker.
    return "BRK-B" if symbol == "BRK.B" else symbol


def _name_key(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|class [a-z])\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


class NewsService:
    """SQLite-backed stale-while-revalidate Yahoo news service."""

    def __init__(self, db: Any, resolver: Any, settings: Any, provider: YahooFinanceNewsProvider | None = None):
        self.db = db
        self.resolver = resolver
        self.settings = settings
        self.provider = provider or YahooFinanceNewsProvider(
            timeout_seconds=float(getattr(settings, "news_timeout_seconds", 8.0)),
            max_retries=int(getattr(settings, "news_max_retries", 2)),
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(4, int(getattr(settings, "news_max_concurrency", 3)))),
            thread_name_prefix="tradely-news",
        )
        self._guard = threading.Lock()
        self._futures: dict[str, Future[Any]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_watchlist_refresh = 0.0
        self._last_error_code: str | None = None

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.provider.close()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watchlist_loop, name="tradely-news-watchlist", daemon=True)
        self._thread.start()

    def _watchlist_loop(self) -> None:
        interval = max(30, int(getattr(self.settings, "news_watchlist_refresh_seconds", 300)))
        while not self._stop.wait(min(interval, 30)):
            if time.monotonic() - self._last_watchlist_refresh >= interval:
                self.refresh_watchlist()

    def refresh_watchlist(self) -> int:
        self._last_watchlist_refresh = time.monotonic()
        scheduled = 0
        try:
            for item in self.db.get_watchlist():
                instrument_id = str(item.get("instrument_id") or "")
                instrument = self.resolver.get(instrument_id) if instrument_id else None
                if not instrument:
                    continue
                if self.request_refresh(instrument, force=True, respect_cooldown=True):
                    scheduled += 1
        except Exception:
            logger.exception("Unable to schedule cached news refresh for watchlist")
        return scheduled

    def resolve_instrument(self, query: str | None = None, instrument_id: str | None = None) -> dict[str, Any]:
        if instrument_id:
            instrument = self.resolver.get(instrument_id)
            if instrument:
                return instrument
            raise ValueError("No supported instrument matches that identifier")
        value = (query or "").strip()
        if not value or len(value) > 120 or not re.fullmatch(r"[\w.^&/ -]+", value, flags=re.UNICODE):
            raise ValueError("Enter a valid ticker or company name")
        try:
            return self.resolver.resolve_or_raise(value)
        except Exception as original:
            # Yahoo suffixes are only translated through the explicit NSE/BSE mapping.
            match = re.fullmatch(r"([A-Z0-9&-]+)\.(NS|BO)", value.upper())
            if match:
                market, exchange = "india", "NSE" if match.group(2) == "NS" else "BSE"
                result = self.resolver.resolve(match.group(1), market=market, exchange=exchange)
                if result.get("status") == "resolved" and result.get("instrument"):
                    return result["instrument"]
            # Resolve Yahoo-discovered listings only when the result maps back to an exact
            # supported Tradely instrument and the normalized company identity agrees.
            try:
                for candidate in self.provider.search_instruments(value):
                    mapped = self._map_yahoo_candidate(candidate)
                    if mapped and candidate["yahoo_symbol"].casefold() == value.casefold():
                        return mapped
            except YahooNewsError:
                pass
            raise original

    def _map_yahoo_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        yahoo_symbol = str(candidate.get("yahoo_symbol") or "").upper()
        try:
            instrument = self.resolver.resolve_or_raise(yahoo_symbol)
            expected_yahoo = yahoo_symbol_for(instrument)
            if expected_yahoo == yahoo_symbol and _name_key(str(instrument.get("name") or "")) == _name_key(str(candidate.get("name") or "")):
                return instrument
        except Exception:
            pass
        match = re.fullmatch(r"([A-Z0-9&-]+)\.(NS|BO)", yahoo_symbol)
        if match:
            market, exchange = "india", "NSE" if match.group(2) == "NS" else "BSE"
            try:
                result = self.resolver.resolve(match.group(1), market=market, exchange=exchange)
                instrument = result.get("instrument") if result.get("status") == "resolved" else None
                if instrument and _name_key(str(instrument.get("name") or "")) == _name_key(str(candidate.get("name") or "")):
                    return instrument
            except Exception:
                pass
        crypto_match = re.fullmatch(r"([A-Z0-9]+)-USD", yahoo_symbol)
        if crypto_match:
            try:
                result = self.resolver.resolve(crypto_match.group(1) + "USDT", market="crypto")
                instrument = result.get("instrument") if result.get("status") == "resolved" else None
                yahoo_name = _name_key(str(candidate.get("name") or ""))
                if instrument and yahoo_symbol_for(instrument) == yahoo_symbol:
                    internal_name = _name_key(str(instrument.get("name") or ""))
                    if yahoo_name.removesuffix(" usd") == internal_name:
                        return instrument
            except Exception:
                pass
        return None

    def search_instruments(self, query: str) -> dict[str, Any]:
        value = query.strip()
        if len(value) < 1 or len(value) > 120:
            raise ValueError("Search query must contain 1–120 characters")
        candidates = self.provider.search_instruments(value)
        results = []
        seen: set[str] = set()
        for candidate in candidates:
            instrument = self._map_yahoo_candidate(candidate)
            if not instrument or instrument["instrument_id"] in seen:
                continue
            seen.add(instrument["instrument_id"])
            results.append({
                "instrument_id": instrument["instrument_id"],
                "symbol": instrument["symbol"],
                "yahoo_symbol": candidate["yahoo_symbol"],
                "name": instrument.get("name") or candidate["name"],
                "exchange": instrument.get("exchange") or candidate.get("exchange"),
                "market": instrument.get("market"),
                "instrument_type": candidate.get("instrument_type") or instrument.get("asset_type"),
                "instrument": instrument,
            })
        return {"query": value, "items": results, "count": len(results), "provider": "Yahoo Finance"}

    def request_refresh(self, instrument: dict[str, Any], *, force: bool, respect_cooldown: bool = True) -> bool:
        instrument_id = str(instrument.get("instrument_id") or "")
        if not instrument_id:
            return False
        now = _now()
        state = self.db.news_cache_state(instrument_id)
        # News is intentionally not cached. The cooldown below only prevents a
        # burst of identical provider requests from multiple open tabs.
        cooldown = max(5, int(getattr(self.settings, "news_refresh_cooldown_seconds", 30)))
        if respect_cooldown and state and state.get("last_attempt_at"):
            try:
                attempted = datetime.fromisoformat(str(state["last_attempt_at"])).astimezone(UTC)
                if (now - attempted).total_seconds() < cooldown:
                    return False
            except ValueError:
                pass
        with self._guard:
            if instrument_id in self._futures and not self._futures[instrument_id].done():
                return False
            self.db.begin_news_refresh(
                instrument_id=instrument_id,
                symbol=str(instrument.get("symbol") or "").upper(),
                attempted_at=_iso(now),
            )
            future = self._executor.submit(self._refresh_one, instrument)
            self._futures[instrument_id] = future
            future.add_done_callback(lambda _done, key=instrument_id: self._forget_future(key))
        return True

    def _forget_future(self, instrument_id: str) -> None:
        with self._guard:
            current = self._futures.get(instrument_id)
            if current and current.done():
                self._futures.pop(instrument_id, None)

    def _refresh_one(self, instrument: dict[str, Any]) -> None:
        instrument_id = str(instrument["instrument_id"])
        symbol = str(instrument["symbol"]).upper()
        attempted = _now()
        try:
            yahoo_symbol = yahoo_symbol_for(instrument)
            articles = self.provider.get_symbol_articles(yahoo_symbol, str(instrument.get("name") or symbol))
            for article in articles:
                article["primary_symbol"] = symbol
            # The expiry only marks when the next forced refresh is expected;
            # feeds always schedule a refresh regardless of this timestamp.
            ttl = max(5, int(getattr(self.settings, "news_refresh_cooldown_seconds", 30)))
            self.db.save_news_refresh(
                instrument_id=instrument_id, symbol=symbol, articles=articles,
                attempted_at=_iso(attempted), expires_at=_iso(attempted + timedelta(seconds=ttl)),
            )
            self._last_error_code = None
            logger.info("Yahoo news refresh completed symbol=%s article_count=%d", symbol, len(articles))
        except (YahooNewsError, ValueError) as exc:
            code = f"http_{exc.status_code}" if isinstance(exc, YahooNewsError) and exc.status_code else "provider_unavailable" if isinstance(exc, YahooNewsError) else "symbol_mapping_unavailable"
            self._last_error_code = code
            self.db.mark_news_refresh_failure(
                instrument_id=instrument_id, symbol=symbol, attempted_at=_iso(attempted),
                provider_status=self.provider.status, error_code=code,
            )
            logger.warning("Yahoo news refresh failed symbol=%s code=%s", symbol, code)
        except Exception:
            self._last_error_code = "internal_error"
            self.db.mark_news_refresh_failure(
                instrument_id=instrument_id, symbol=symbol, attempted_at=_iso(attempted),
                provider_status=self.provider.status, error_code="internal_error",
            )
            logger.exception("Unexpected news refresh failure symbol=%s", symbol)

    @staticmethod
    def _article_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items = []
        for row in rows:
            item = dict(row)
            item["id"] = item.pop("article_id", "")
            item.pop("yahoo_id", None)
            item.pop("canonical_url", None)
            item.pop("related_symbols_json", None)
            items.append(item)
        return items

    def symbol_feed(
        self, instrument: dict[str, Any], *, page: int = 1, page_size: int = 10,
        query: str | None = None, date_from: str | None = None, date_to: str | None = None,
    ) -> dict[str, Any]:
        self.request_refresh(instrument, force=True, respect_cooldown=True)
        instrument_id = str(instrument["instrument_id"])
        state = self.db.news_cache_state(instrument_id)
        now = _now()
        stale = not state or not state.get("expires_at")
        if state and state.get("expires_at"):
            try:
                stale = datetime.fromisoformat(str(state["expires_at"])).astimezone(UTC) <= now
            except ValueError:
                stale = True
        offset = (page - 1) * page_size
        rows = self.db.list_news(
            instrument_id=instrument_id, query=query, date_from=date_from, date_to=date_to,
            limit=page_size, offset=offset,
        )
        items = self._article_payload(rows)
        count = self.db.count_news(instrument_id=instrument_id, query=query, date_from=date_from, date_to=date_to)
        return {
            "symbol": instrument.get("symbol"), "yahoo_symbol": yahoo_symbol_for(instrument),
            "market": instrument.get("market"), "exchange": instrument.get("exchange"),
            "instrument": instrument, "items": items, "count": count,
            "page": page, "page_size": page_size, "stale": stale,
            "last_successful_refresh": state.get("last_success_at") if state else None,
            "last_attempted_refresh": state.get("last_attempt_at") if state else None,
            "refresh_status": state.get("status") if state else "pending",
            "provider_status": state.get("provider_status") if state else self.provider.status,
            "error_code": state.get("error_code") if state else None,
        }

    def general_feed(
        self, *, page: int = 1, page_size: int = 20, query: str | None = None,
        date_from: str | None = None, date_to: str | None = None, symbol: str | None = None,
    ) -> dict[str, Any]:
        self.refresh_watchlist()
        offset = (page - 1) * page_size
        rows = self.db.list_news(
            symbol=symbol, query=query, date_from=date_from, date_to=date_to,
            limit=page_size, offset=offset,
        )
        items = self._article_payload(rows)
        count = self.db.count_news(symbol=symbol, query=query, date_from=date_from, date_to=date_to)
        states = self.db.list_news_cache_states()
        last_success = max((str(item["last_success_at"]) for item in states if item.get("last_success_at")), default=None)
        stale = False
        for state in states:
            try:
                stale = stale or state.get("status") != "ok" or datetime.fromisoformat(str(state.get("expires_at"))).astimezone(UTC) <= _now()
            except (TypeError, ValueError):
                stale = True
        return {
            "items": items, "count": count, "page": page, "page_size": page_size,
            "sort": "newest", "stale": stale,
            "last_updated": last_success,
            "coverage": "Yahoo Finance headlines cached for Tradely watchlist and instruments previously searched or analyzed; not a complete market-wide feed.",
        }

    def refresh_status(self, instrument: dict[str, Any] | None = None) -> dict[str, Any]:
        if instrument:
            states = [self.db.news_cache_state(str(instrument.get("instrument_id") or ""))]
            states = [item for item in states if item]
        else:
            states = self.db.list_news_cache_states()
        return {
            "provider": "Yahoo Finance", "provider_status": self.provider.status,
            "last_successful_retrieval": max((str(item["last_success_at"]) for item in states if item.get("last_success_at")), default=None),
            "last_attempted_retrieval": max((str(item["last_attempt_at"]) for item in states if item.get("last_attempt_at")), default=None),
            "cache_entries": len(states),
            "failures": sum(1 for item in states if item.get("status") == "error"),
            "items": [{
                "instrument_id": item.get("instrument_id"), "symbol": item.get("symbol"),
                "last_success_at": item.get("last_success_at"), "last_attempt_at": item.get("last_attempt_at"),
                "cache_expires_at": item.get("expires_at"), "status": item.get("status"),
                "provider_status": item.get("provider_status"), "error_code": item.get("error_code"),
                "failure_count": item.get("failure_count", 0),
            } for item in states],
        }
