from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

from app.core.config import Settings
from app.core.models import NewsItem


def _id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        try:
            if re.fullmatch(r"\d{8}T\d{6}Z", value):
                return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            parsed = parsedate_to_datetime(value)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None


class GDELTNewsProvider:
    name = "GDELT"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_error: str | None = None

    def search(self, query: str, symbol: str, limit: int = 20) -> list[NewsItem]:
        self.last_error = None
        if not self.settings.gdelt_enabled:
            self.last_error = "Disabled in configuration"
            return []
        params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": min(limit, 50), "sort": "HybridRel"}
        try:
            response = httpx.get(
                "https://api.gdeltproject.org/api/v2/doc/doc", params=params,
                headers={"User-Agent": "Tradely/0.1 private market research"},
                timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = str(exc)
            return []
        items: list[NewsItem] = []
        for article in payload.get("articles", []):
            url = article.get("url")
            title = article.get("title")
            if not url or not title:
                continue
            publisher = article.get("domain") or article.get("sourceCountry")
            published = _date(article.get("seendate"))
            items.append(NewsItem(
                id=_id(url), title=title, url=url, publisher=publisher,
                published_at=published, summary=None, category="general",
                source=self.name, related_symbols=[symbol], official=False,
            ))
        return items


class YahooFinanceNewsProvider:
    """Unofficial yfinance news accessor for the owner's personal research only."""

    name = "Yahoo Finance News (unofficial)"

    def search(self, symbol: str, market: str) -> list[NewsItem]:
        try:
            import yfinance as yf
        except ImportError:
            return []
        ticker = symbol.upper()
        if market == "india" and not ticker.endswith((".NS", ".BO")):
            ticker += ".NS"
        try:
            rows = yf.Ticker(ticker).news or []
        except Exception:
            return []
        results = []
        for row in rows[:30]:
            content = row.get("content", row)
            title = content.get("title") or row.get("title")
            canonical = content.get("canonicalUrl") or row.get("canonicalUrl") or {}
            url = canonical.get("url") if isinstance(canonical, dict) else canonical
            provider = content.get("provider") or row.get("publisher") or {}
            publisher = provider.get("displayName") if isinstance(provider, dict) else str(provider)
            pub_date = content.get("pubDate") or row.get("providerPublishTime")
            if isinstance(pub_date, (int, float)):
                published = datetime.fromtimestamp(pub_date, tz=timezone.utc)
            else:
                published = _date(str(pub_date)) if pub_date else None
            if title and url:
                results.append(NewsItem(
                    id=_id(str(url)), title=str(title), url=str(url), publisher=publisher,
                    published_at=published, summary=content.get("summary"), category="company",
                    source=self.name, related_symbols=[symbol], official=False,
                ))
        return results
