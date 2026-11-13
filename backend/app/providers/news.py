from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

from app.core.config import Settings
from app.core.models import CorporateEvent, NewsItem


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


class RSSNewsProvider:
    name = "Publisher RSS"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_errors: list[str] = []

    def search(self, query: str, symbol: str) -> list[NewsItem]:
        self.last_errors = []
        results: list[NewsItem] = []
        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9&.-]+", query) if len(term) > 2]
        for feed_url in self.settings.rss_urls:
            try:
                response = httpx.get(feed_url, timeout=self.settings.http_timeout_seconds,
                                     headers={"User-Agent": "Tradely/0.1 private research"})
                response.raise_for_status()
                root = ET.fromstring(response.text)
            except (httpx.HTTPError, ET.ParseError) as exc:
                self.last_errors.append(f"{feed_url}: {exc}")
                continue
            rss_items = root.findall(".//item")
            atom_items = root.findall(".//{*}entry")
            for item in rss_items + atom_items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if not link:
                    link_element = item.find("{*}link")
                    link = (link_element.attrib.get("href", "") if link_element is not None else "").strip()
                description = (item.findtext("description") or item.findtext("{*}summary") or
                               item.findtext("{*}content") or "").strip()
                pub_date = (item.findtext("pubDate") or item.findtext("{*}published") or
                            item.findtext("{*}updated"))
                haystack = (title + " " + description).lower()
                if not link or not title or (terms and not any(term in haystack for term in terms)):
                    continue
                results.append(NewsItem(
                    id=_id(link), title=title, url=link, publisher=feed_url,
                    published_at=_date(pub_date), summary=re.sub(r"<[^>]+>", "", description)[:500],
                    category="general", source=self.name, related_symbols=[symbol], official=False,
                ))
        return results


class TejHQActionsProvider:
    name = "TejHQ corporate actions"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_error: str | None = None

    def get_actions(self, symbol: str) -> list[CorporateEvent]:
        self.last_error = None
        try:
            response = httpx.get(
                f"https://api.tejhq.dev/v1/actions/{symbol.upper()}",
                timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = str(exc)
            return []
        events: list[CorporateEvent] = []
        today = datetime.now(timezone.utc).date()
        for item in payload.get("data", []):
            date_value = item.get("ex_date") or item.get("record_date")
            try:
                event_date = datetime.fromisoformat(date_value).date() if date_value else None
            except ValueError:
                event_date = None
            event_type = str(item.get("type") or "corporate_action")
            description = str(item.get("raw_subject") or event_type)
            events.append(CorporateEvent(
                id=_id(f"tej:{symbol}:{date_value}:{event_type}:{description}"),
                symbol=symbol.upper(), event_type=event_type, description=description,
                event_date=event_date,
                status="historical" if event_date and event_date < today else ("confirmed" if event_date else "unverified"),
                source=self.name, source_url="https://tejhq.dev/docs", official=False,
            ))
        return events


class SECEdgarProvider:
    name = "SEC EDGAR"

    def __init__(self, settings: Settings):
        self.settings = settings

    def recent_filings(self, cik: str) -> list[NewsItem]:
        if "contact@example.invalid" in self.settings.sec_user_agent or not self.settings.sec_user_agent.strip():
            raise RuntimeError("Set SEC_USER_AGENT in .env to a real identifying name and contact email before using EDGAR.")
        normalized = str(cik).strip().zfill(10)
        if not normalized.isdigit():
            return []
        headers = {"User-Agent": self.settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
        try:
            response = httpx.get(
                f"https://data.sec.gov/submissions/CIK{normalized}.json", headers=headers,
                timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []
        recent = payload.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        company = payload.get("name", normalized)
        results = []
        for index in range(min(40, len(forms), len(dates), len(accessions), len(docs))):
            accession_compact = accessions[index].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(normalized)}/{accession_compact}/{docs[index]}"
            results.append(NewsItem(
                id=_id(url), title=f"{company}: {forms[index]} filing", url=url,
                publisher="U.S. Securities and Exchange Commission", published_at=_date(dates[index]),
                summary=f"Official SEC filing form {forms[index]}.", category="filing",
                source=self.name, official=True,
            ))
        return results


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
