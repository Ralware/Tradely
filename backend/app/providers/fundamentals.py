from __future__ import annotations

from typing import Any

import pandas as pd

from app.providers.base import ProviderError


INFO_FIELDS = [
    "longName", "shortName", "symbol", "exchange", "currency", "quoteType", "sector", "industry",
    "marketCap", "enterpriseValue", "trailingPE", "forwardPE", "priceToBook", "trailingEps",
    "forwardEps", "dividendRate", "dividendYield", "beta", "returnOnEquity", "returnOnAssets",
    "profitMargins", "operatingMargins", "grossMargins", "debtToEquity", "currentRatio", "quickRatio",
    "revenueGrowth", "earningsGrowth", "freeCashflow", "operatingCashflow", "totalCash", "totalDebt",
    "bookValue", "sharesOutstanding", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "averageVolume",
    "averageVolume10days", "website", "fullTimeEmployees", "longBusinessSummary",
]


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (pd.isna(value) or value in (float("inf"), float("-inf"))):
            return None
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        numeric = float(value)
        return numeric if pd.notna(numeric) else None
    except (TypeError, ValueError):
        return str(value)


def _statement_payload(statement: pd.DataFrame, max_rows: int = 35) -> dict[str, Any]:
    if statement is None or statement.empty:
        return {"periods": [], "rows": []}
    periods = [column.isoformat() if hasattr(column, "isoformat") else str(column) for column in statement.columns[:4]]
    rows = []
    for name, series in statement.head(max_rows).iterrows():
        values = [_clean_value(value) for value in series.iloc[:4].tolist()]
        rows.append({"metric": str(name), "values": values})
    return {"periods": periods, "rows": rows}


class YahooFundamentalsProvider:
    """Best-effort fundamentals/profile adapter from yfinance (unofficial personal-use data)."""

    name = "Yahoo Finance / yfinance (unofficial)"

    def fetch(self, symbol: str, market: str, exchange: str | None = None) -> dict[str, Any]:
        if market == "crypto":
            raise ProviderError("Fundamental statements are not available through this equity profile endpoint")
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError("yfinance is not installed") from exc
        ticker_symbol = symbol.upper()
        if market == "india" and not ticker_symbol.endswith((".NS", ".BO")):
            ticker_symbol += ".BO" if (exchange or "NSE").upper() == "BSE" else ".NS"
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.get_info()
            income = getattr(ticker, "quarterly_income_stmt", pd.DataFrame())
            balance = getattr(ticker, "quarterly_balance_sheet", pd.DataFrame())
            cashflow = getattr(ticker, "quarterly_cashflow", pd.DataFrame())
        except Exception as exc:
            raise ProviderError(f"Yahoo Finance fundamentals request failed: {exc}") from exc
        clean_info = {key: _clean_value(info.get(key)) for key in INFO_FIELDS if info.get(key) is not None}
        return {
            "symbol": ticker_symbol,
            "source": self.name,
            "profile": clean_info,
            "quarterly_income_statement": _statement_payload(income),
            "quarterly_balance_sheet": _statement_payload(balance),
            "quarterly_cash_flow": _statement_payload(cashflow),
            "limitations": [
                "Unofficial Yahoo Finance data; coverage and field availability vary by exchange and company.",
                "Blank/missing fields are not inferred or filled with estimates.",
                "Financial statement periods are returned as provided by Yahoo; verify material figures against issuer filings.",
            ],
        }
