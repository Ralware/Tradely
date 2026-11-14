from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from app.core.config import Settings
from app.core.instruments import CRYPTO_QUOTE_ASSETS
from app.instruments.catalogue_data import _crypto, _equity


def _binance_entries(settings: Settings) -> list[dict[str, Any]]:
    response = httpx.get(
        "https://data-api.binance.vision/api/v3/exchangeInfo",
        timeout=settings.http_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    entries: list[dict[str, Any]] = []
    for item in payload.get("symbols", []):
        symbol = str(item.get("symbol") or "").upper()
        quote = str(item.get("quoteAsset") or "").upper()
        status = str(item.get("status") or "")
        if (
            not symbol
            or quote not in CRYPTO_QUOTE_ASSETS
            or status != "TRADING"
            or not item.get("isSpotTradingAllowed", True)
        ):
            continue
        try:
            entry = _crypto(symbol)
        except ValueError:
            continue
        entry["catalogue_source"] = "Binance Spot exchangeInfo (live)"
        entry["status"] = "active"
        entries.append(entry)
    return entries


def _nse_entries(settings: Settings) -> list[dict[str, Any]]:
    response = httpx.get(
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        headers={"User-Agent": "Tradely/1.0 (private personal research)"},
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    entries: list[dict[str, Any]] = []
    for row in reader:
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        name = str(row.get("NAME OF COMPANY") or "").strip()
        series = str(row.get(" SERIES") or row.get("SERIES") or "").strip().upper()
        if not symbol or not name or series not in {"EQ", "BE", "BZ"}:
            continue
        entry = _equity(symbol, name.title(), "india", "NSE", "INR")
        entry["catalogue_source"] = "NSE Equity List archive (live)"
        entries.append(entry)
    return entries


def refresh_catalogue(db: Any, settings: Settings) -> dict[str, Any]:
    """Best-effort catalogue refresh from legitimate public sources.

    Failures are reported explicitly and never replace the bundled catalogue.
    """
    report: dict[str, Any] = {"updated": 0, "sources": {}, "errors": []}
    for name, loader in (("Binance Spot exchangeInfo", _binance_entries),
                         ("NSE Equity List", _nse_entries)):
        try:
            entries = loader(settings)
            written = db.upsert_catalogue_entries(entries)
            report["sources"][name] = {"entries": written}
            report["updated"] += written
        except Exception as exc:  # network/provider changes must be explicit
            report["sources"][name] = {"entries": 0}
            report["errors"].append(f"{name}: {exc}")
    return report
