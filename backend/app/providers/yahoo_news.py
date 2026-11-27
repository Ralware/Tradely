from __future__ import annotations

import hashlib
import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
MAX_RESPONSE_BYTES = 2_000_000
MAX_ARTICLES = 50


class YahooNewsError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def safe_http_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
        return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ""))
    except ValueError:
        return None


def canonical_article_url(value: str | None) -> str | None:
    safe = safe_http_url(value)
    if not safe:
        return None
    parts = urlsplit(safe)
    query = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() != "tsrc" and not key.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def _plain_text(value: Any, limit: int = 2000) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    extractor = _TextExtractor()
    try:
        extractor.feed(html.unescape(value))
        text = " ".join(extractor.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def _timestamp_epoch(value: Any) -> str | None:
    try:
        number = float(value)
        if number <= 0:
            return None
        return datetime.fromtimestamp(number, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _timestamp_rss(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _fingerprint(title: str, publisher: str | None, published_at: str | None) -> str:
    text = "|".join((title.casefold().strip(), (publisher or "").casefold().strip(), published_at or ""))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_search_article(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = _plain_text(raw.get("title"), 500)
    url = safe_http_url(raw.get("link") or raw.get("url"))
    if not title or not url:
        return None
    thumbnail = raw.get("thumbnail")
    resolutions = thumbnail.get("resolutions") if isinstance(thumbnail, dict) else None
    thumbnail_url = None
    if isinstance(resolutions, list):
        for item in resolutions:
            if isinstance(item, dict) and (thumbnail_url := safe_http_url(item.get("url"))):
                break
    publisher = _plain_text(raw.get("publisher"), 160)
    published_at = _timestamp_epoch(raw.get("providerPublishTime"))
    related = raw.get("relatedTickers")
    related_symbols = sorted({str(item).strip().upper() for item in related if isinstance(item, str) and item.strip()}) if isinstance(related, list) else []
    return {
        "yahoo_id": str(raw.get("uuid")).strip()[:160] if raw.get("uuid") else None,
        "title": title,
        "summary": _plain_text(raw.get("summary") or raw.get("description")),
        "publisher": publisher,
        "published_at": published_at,
        "article_url": url,
        "canonical_url": canonical_article_url(url),
        "thumbnail_url": thumbnail_url,
        "related_symbols": related_symbols,
        "source": "Yahoo Finance Search",
        "fingerprint": _fingerprint(title, publisher, published_at),
    }


def normalize_rss_item(item: ET.Element) -> dict[str, Any] | None:
    title = _plain_text(item.findtext("title"), 500)
    url = safe_http_url(item.findtext("link"))
    if not title or not url:
        return None
    guid = item.findtext("guid")
    return {
        "yahoo_id": guid.strip()[:160] if guid and guid.strip() else None,
        "title": title,
        "summary": _plain_text(item.findtext("description")),
        # Yahoo's RSS item does not identify the original publisher.
        "publisher": None,
        "published_at": _timestamp_rss(item.findtext("pubDate")),
        "article_url": url,
        "canonical_url": canonical_article_url(url),
        "thumbnail_url": None,
        "related_symbols": [],
        "source": "Yahoo Finance RSS",
        "fingerprint": _fingerprint(title, None, _timestamp_rss(item.findtext("pubDate"))),
    }


def _normal_name(value: str) -> str:
    value = re.sub(r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|plc|class [a-z])\b", " ", value.casefold())
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def rss_item_is_relevant(article: dict[str, Any], symbol: str, company_name: str) -> bool:
    title = str(article.get("title") or "").casefold()
    summary = str(article.get("summary") or "").casefold()
    text = f" {title} {summary} "
    name = _normal_name(company_name)
    if len(name) >= 5 and f" {name} " in f" {_normal_name(text)} ":
        return True
    ticker = symbol.upper()
    if len(ticker) >= 3 and re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", text.upper()):
        return True
    # Common Yahoo suffixes are not normally repeated in headlines.
    base = re.sub(r"\.(NS|BO)$", "", ticker)
    return len(base) >= 4 and re.search(rf"(?<![A-Z0-9]){re.escape(base)}(?![A-Z0-9])", text.upper()) is not None


class YahooFinanceNewsProvider:
    """Small, bounded adapter for Yahoo Finance's public search and RSS endpoints."""

    def __init__(self, *, timeout_seconds: float = 8.0, max_retries: int = 2, client: httpx.Client | None = None):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, min(max_retries, 3))
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "Tradely/1.0 (+local financial research)", "Accept": "application/json, application/rss+xml, application/xml;q=0.9, */*;q=0.1"},
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._last_status: str = "unknown"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    @property
    def status(self) -> str:
        return self._last_status

    def _get(self, url: str, params: dict[str, str | int]) -> bytes:
        last_error: YahooNewsError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.get(url, params=params)
                status = response.status_code
                if status == 429 or status >= 500:
                    retry_after = None
                    try:
                        retry_after = min(10.0, max(0.0, float(response.headers.get("Retry-After", ""))))
                    except (TypeError, ValueError):
                        pass
                    last_error = YahooNewsError("Yahoo Finance is temporarily unavailable", status_code=status, retry_after=retry_after)
                    if attempt < self.max_retries:
                        time.sleep(retry_after if retry_after is not None else min(2.0, 0.35 * (2**attempt)))
                        continue
                    break
                if status in {403, 404}:
                    raise YahooNewsError("Yahoo Finance rejected the news request", status_code=status)
                if status < 200 or status >= 300:
                    raise YahooNewsError("Yahoo Finance returned an unexpected response", status_code=status)
                data = response.content
                if len(data) > MAX_RESPONSE_BYTES:
                    raise YahooNewsError("Yahoo Finance response exceeded the size limit", status_code=status)
                self._last_status = "available"
                return data
            except httpx.TimeoutException as exc:
                last_error = YahooNewsError("Yahoo Finance request timed out")
                if attempt < self.max_retries:
                    time.sleep(min(2.0, 0.35 * (2**attempt)))
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = YahooNewsError("Yahoo Finance connection failed")
                if attempt < self.max_retries:
                    time.sleep(min(2.0, 0.35 * (2**attempt)))
                    continue
                raise last_error from exc
        self._last_status = "unavailable"
        if last_error:
            raise last_error
        raise YahooNewsError("Yahoo Finance request failed")

    def search(self, query: str) -> dict[str, Any]:
        raw = self._get(SEARCH_URL, {"q": query, "quotesCount": 10, "newsCount": 50})
        try:
            parsed = httpx.Response(200, content=raw).json()
        except (ValueError, UnicodeDecodeError) as exc:
            self._last_status = "unavailable"
            raise YahooNewsError("Yahoo Finance returned malformed JSON") from exc
        if not isinstance(parsed, dict):
            raise YahooNewsError("Yahoo Finance search returned an unexpected structure")
        return parsed

    def search_instruments(self, query: str) -> list[dict[str, Any]]:
        payload = self.search(query)
        quotes = payload.get("quotes")
        if not isinstance(quotes, list):
            return []
        results: list[dict[str, Any]] = []
        for raw in quotes[:10]:
            if not isinstance(raw, dict):
                continue
            symbol = raw.get("symbol")
            name = raw.get("longname") or raw.get("shortname")
            if not isinstance(symbol, str) or not symbol.strip() or not isinstance(name, str) or not name.strip():
                continue
            results.append({
                "yahoo_symbol": symbol.strip().upper(),
                "name": _plain_text(name, 180) or name.strip(),
                "exchange": _plain_text(raw.get("exchDisp") or raw.get("exchange"), 80),
                "instrument_type": _plain_text(raw.get("typeDisp") or raw.get("quoteType"), 80),
                "quote_type": str(raw.get("quoteType") or ""),
            })
        return results

    def get_symbol_articles(self, yahoo_symbol: str, company_name: str) -> list[dict[str, Any]]:
        search_error: YahooNewsError | None = None
        search_articles: list[dict[str, Any]] = []
        queries = list(dict.fromkeys(query.strip() for query in (yahoo_symbol, company_name) if query.strip()))
        for query in queries:
            try:
                payload = self.search(query)
                news = payload.get("news")
                candidates = [normalize_search_article(item) for item in news[:MAX_ARTICLES]] if isinstance(news, list) else []
                search_articles.extend(
                    item for item in candidates
                    if item and self._search_article_relevant(item, yahoo_symbol, company_name)
                )
            except YahooNewsError as exc:
                search_error = search_error or exc
                logger.warning("Yahoo Finance search retrieval failed query=%s status=%s", query, exc.status_code)
        if search_articles:
            return self._deduplicate(search_articles)

        try:
            raw = self._get(RSS_URL, {"s": yahoo_symbol, "region": "US", "lang": "en-US"})
            if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise YahooNewsError("Yahoo Finance RSS contained prohibited declarations")
            root = ET.fromstring(raw)
            items = root.findall("./channel/item")
            rss = [normalize_rss_item(item) for item in items[:MAX_ARTICLES]]
            articles = [item for item in rss if item and rss_item_is_relevant(item, yahoo_symbol, company_name)]
            return self._deduplicate(articles)
        except (YahooNewsError, ET.ParseError, ValueError) as exc:
            self._last_status = "unavailable"
            logger.warning("Yahoo Finance RSS retrieval failed status=%s", getattr(exc, "status_code", None))
            if search_error:
                raise search_error from exc
            if isinstance(exc, YahooNewsError):
                raise
            raise YahooNewsError("Yahoo Finance returned invalid RSS") from exc

    @staticmethod
    def _search_article_relevant(article: dict[str, Any], yahoo_symbol: str, company_name: str) -> bool:
        related = [str(value).upper() for value in article.get("related_symbols", [])]
        if related:
            return yahoo_symbol.upper() in related
        return rss_item_is_relevant(article, yahoo_symbol, company_name)

    @staticmethod
    def _deduplicate(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for article in articles:
            key = article.get("canonical_url") or article.get("yahoo_id") or article.get("fingerprint")
            if key:
                by_key.setdefault(str(key), article)
        return sorted(by_key.values(), key=lambda item: item.get("published_at") or "", reverse=True)[:MAX_ARTICLES]
