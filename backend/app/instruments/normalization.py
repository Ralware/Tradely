from __future__ import annotations

import re
import unicodedata

# Normalisation is deliberately conservative. It removes formatting noise but
# never rewrites a legitimate ticker (for example BRK.B or BAJAJ-AUTO).
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
_WHITESPACE = re.compile(r"[\s\u00a0]+")
_NON_NAME = re.compile(r"[^a-z0-9& ]+")
_COMPACT = re.compile(r"[^A-Z0-9]+")
_CORPORATE_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "ltd",
    "limited", "plc", "llc", "lp", "nv", "sa", "ag", "se", "group",
    "holdings", "holding", "the",
}

EXCHANGE_PRIORITY: dict[str, int] = {
    "NSE": 0,
    "NASDAQ": 0,
    "BINANCE": 0,
    "NYSE": 1,
    "BSE": 1,
    "AMEX": 2,
    "NYSEARCA": 3,
}


def normalize_query(value: str) -> str:
    """Trim, collapse whitespace and remove invisible formatting characters."""
    text = unicodedata.normalize("NFKC", value or "").translate(_ZERO_WIDTH)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


def upper(value: str) -> str:
    return normalize_query(value).upper()


def compact_symbol(value: str) -> str:
    """Uppercase alphanumeric projection used for crypto pair detection."""
    return _COMPACT.sub("", upper(value))


def normalized_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold().replace("&", " and ")
    text = _NON_NAME.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def name_core(value: str) -> str:
    """Name with generic corporate suffixes removed for alias comparisons."""
    words = normalized_name(value).split()
    while words and words[-1] in _CORPORATE_SUFFIXES:
        words.pop()
    return " ".join(words)


def exchange_priority(exchange: str) -> int:
    return EXCHANGE_PRIORITY.get(upper(exchange), 9)


def title_case_meta(asset_type: str, market: str) -> str:
    if asset_type == "crypto":
        return "Cryptocurrency"
    if market == "india":
        return "Indian Equity"
    if market == "global":
        return "International Equity"
    return "Equity"
