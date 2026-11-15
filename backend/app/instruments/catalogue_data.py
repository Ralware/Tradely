from __future__ import annotations

from typing import Any, Iterable

from app.core.instruments import TRADINGVIEW_PROVIDER, split_crypto_pair

CATALOGUE_VERSION = "2026.11.3"
CATALOGUE_SOURCE = "Bundled Verified Catalogue (NSE/NASDAQ/NYSE/Binance Spot Listings; TradingView identities)"
CATALOGUE_RELEASE_DATE = "2026-11-16T00:00:00+00:00"

INDIA_PROVIDER = TRADINGVIEW_PROVIDER
GLOBAL_PROVIDER = TRADINGVIEW_PROVIDER
CRYPTO_PROVIDER = TRADINGVIEW_PROVIDER

INDIA_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]
GLOBAL_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]
CRYPTO_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1wk", "1mo",
]


_ASSET_NAMES: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BNB",
    "XRP": "XRP", "ADA": "Cardano", "DOGE": "Dogecoin", "AVAX": "Avalanche",
    "TRX": "TRON", "DOT": "Polkadot", "LINK": "Chainlink", "LTC": "Litecoin",
    "BCH": "Bitcoin Cash", "ATOM": "Cosmos", "NEAR": "NEAR Protocol",
    "APT": "Aptos", "ARB": "Arbitrum", "OP": "Optimism", "SUI": "Sui",
    "PEPE": "Pepe", "SHIB": "Shiba Inu", "FIL": "Filecoin",
    "ICP": "Internet Computer", "ETC": "Ethereum Classic", "XLM": "Stellar",
    "ALGO": "Algorand", "VET": "VeChain", "INJ": "Injective",
    "TIA": "Celestia", "SEI": "Sei", "JUP": "Jupiter", "WIF": "dogwifhat",
    "TON": "Toncoin", "ENA": "Ethena", "RENDER": "Render",
    "FET": "Artificial Superintelligence Alliance", "POL": "Polygon Ecosystem Token",
    "AAVE": "Aave", "UNI": "Uniswap", "MKR": "Maker", "LDO": "Lido DAO",
    "STX": "Stacks", "CRV": "Curve DAO", "SAND": "The Sandbox",
    "MANA": "Decentraland", "AXS": "Axie Infinity", "GALA": "Gala",
    "THETA": "Theta Network", "FLOW": "Flow", "EOS": "EOS", "XTZ": "Tezos",
    "NEO": "Neo", "IOTA": "IOTA", "DASH": "Dash", "ZEC": "ZCash",
    "USDT": "Tether", "USDC": "USD Coin", "FDUSD": "First Digital USD",
    "EUR": "Euro", "TRY": "Turkish Lira",
}


def _equity(
    symbol: str,
    name: str,
    market: str,
    exchange: str,
    currency: str,
    aliases: Iterable[str] = (),
) -> dict[str, Any]:
    provider = INDIA_PROVIDER if market == "india" else GLOBAL_PROVIDER
    intervals = INDIA_INTERVALS if market == "india" else GLOBAL_INTERVALS
    return {
        "instrument_id": f"{market}:{exchange}:{symbol}",
        "symbol": symbol,
        "name": name,
        "display_name": name,
        "market": market,
        "exchange": exchange,
        "currency": currency,
        "asset_type": "equity",
        "provider": provider,
        "provider_symbol": f"{exchange}:{symbol}",
        "provider_instrument_id": f"{exchange}:{symbol}",
        "base_currency": currency,
        "quote_currency": currency,
        "settlement_currency": currency,
        "trading_pair": "",
        "supported_intervals": intervals,
        "status": "active",
        "catalogue_source": CATALOGUE_SOURCE,
        "catalogue_updated_at": CATALOGUE_RELEASE_DATE,
        "is_catalogue": True,
        "aliases": list(aliases),
    }


def _crypto(symbol: str, extra_aliases: Iterable[str] = ()) -> dict[str, Any]:
    pair = split_crypto_pair(symbol)
    if pair is None:
        raise ValueError(f"{symbol} is not a verifiable crypto pair")
    base, quote = pair
    name = f"{_ASSET_NAMES.get(base, base)} / {_ASSET_NAMES.get(quote, quote)}"
    return {
        "instrument_id": f"crypto:BINANCE:{symbol}",
        "symbol": symbol,
        "name": name,
        "display_name": name,
        "market": "crypto",
        "exchange": "BINANCE",
        "currency": quote,
        "asset_type": "crypto",
        "provider": CRYPTO_PROVIDER,
        "provider_symbol": f"BINANCE:{symbol}",
        "provider_instrument_id": f"BINANCE:{symbol}",
        "base_currency": base,
        "quote_currency": quote,
        "settlement_currency": quote,
        "trading_pair": f"{base}/{quote}",
        "supported_intervals": CRYPTO_INTERVALS,
        "status": "active",
        "catalogue_source": CATALOGUE_SOURCE,
        "catalogue_updated_at": CATALOGUE_RELEASE_DATE,
        "is_catalogue": True,
        "aliases": list(extra_aliases),
    }


_INDIA_EQUITIES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("RELIANCE", "Reliance Industries", "NSE", ("Reliance", "RIL")),
    ("TCS", "Tata Consultancy Services", "NSE", ("Tata Consultancy", "TCS Ltd")),
    ("INFY", "Infosys", "NSE", ("Infosys Ltd",)),
    ("HDFCBANK", "HDFC Bank", "NSE", ("HDFC",)),
    ("ICICIBANK", "ICICI Bank", "NSE", ("ICICI",)),
    ("SBIN", "State Bank of India", "NSE", ("SBI",)),
    ("BHARTIARTL", "Bharti Airtel", "NSE", ("Airtel",)),
    ("LT", "Larsen & Toubro", "NSE", ("L&T", "Larsen and Toubro")),
    ("ITC", "ITC", "NSE", ()),
    ("KOTAKBANK", "Kotak Mahindra Bank", "NSE", ("Kotak",)),
    ("AXISBANK", "Axis Bank", "NSE", ()),
    ("ASIANPAINT", "Asian Paints", "NSE", ()),
    ("HINDUNILVR", "Hindustan Unilever", "NSE", ("HUL",)),
    ("BAJFINANCE", "Bajaj Finance", "NSE", ()),
    ("MARUTI", "Maruti Suzuki India", "NSE", ("Maruti Suzuki",)),
    ("SUNPHARMA", "Sun Pharmaceutical Industries", "NSE", ("Sun Pharma",)),
    ("TITAN", "Titan Company", "NSE", ()),
    ("ULTRACEMCO", "UltraTech Cement", "NSE", ("UltraTech",)),
    ("WIPRO", "Wipro", "NSE", ()),
    ("NESTLEIND", "Nestle India", "NSE", ("Nestle",)),
    ("POWERGRID", "Power Grid Corporation of India", "NSE", ("Power Grid",)),
    ("NTPC", "NTPC", "NSE", ()),
    ("TATAMOTORS", "Tata Motors", "NSE", ()),
    ("TATASTEEL", "Tata Steel", "NSE", ()),
    ("ADANIENT", "Adani Enterprises", "NSE", ("Adani",)),
    ("ADANIPORTS", "Adani Ports and Special Economic Zone", "NSE", ("Adani Ports",)),
    ("ONGC", "Oil and Natural Gas Corporation", "NSE", ("Oil and Natural Gas",)),
    ("COALINDIA", "Coal India", "NSE", ()),
    ("HCLTECH", "HCL Technologies", "NSE", ("HCL",)),
    ("TECHM", "Tech Mahindra", "NSE", ()),
    ("GRASIM", "Grasim Industries", "NSE", ()),
    ("JSWSTEEL", "JSW Steel", "NSE", ()),
    ("DRREDDY", "Dr. Reddy's Laboratories", "NSE", ("Dr Reddy", "Dr Reddys")),
    ("CIPLA", "Cipla", "NSE", ()),
    ("DIVISLAB", "Divi's Laboratories", "NSE", ("Divis",)),
    ("EICHERMOT", "Eicher Motors", "NSE", ("Eicher",)),
    ("HEROMOTOCO", "Hero MotoCorp", "NSE", ("Hero",)),
    ("BAJAJ-AUTO", "Bajaj Auto", "NSE", ()),
    ("BRITANNIA", "Britannia Industries", "NSE", ("Britannia",)),
    ("HINDALCO", "Hindalco Industries", "NSE", ("Hindalco",)),
    ("INDUSINDBK", "IndusInd Bank", "NSE", ()),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise", "NSE", ("Apollo Hospitals",)),
    ("SHRIRAMFIN", "Shriram Finance", "NSE", ()),
    ("SBILIFE", "SBI Life Insurance", "NSE", ()),
    ("HDFCLIFE", "HDFC Life Insurance", "NSE", ()),
    ("BPCL", "Bharat Petroleum Corporation", "NSE", ("Bharat Petroleum",)),
    ("TATACONSUM", "Tata Consumer Products", "NSE", ()),
    ("BAJAJFINSV", "Bajaj Finserv", "NSE", ()),
    ("LTIM", "LTIMindtree", "NSE", ("LTI", "Mindtree")),
    ("DMART", "Avenue Supermarts", "NSE", ("Dmart",)),
]

_GLOBAL_EQUITIES: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("AAPL", "Apple Inc.", "NASDAQ", "USD", ("Apple",)),
    ("MSFT", "Microsoft Corporation", "NASDAQ", "USD", ("Microsoft",)),
    ("NVDA", "NVIDIA Corporation", "NASDAQ", "USD", ("Nvidia",)),
    ("GOOGL", "Alphabet Inc. Class A", "NASDAQ", "USD", ("Google", "Alphabet")),
    ("GOOG", "Alphabet Inc. Class C", "NASDAQ", "USD", ()),
    ("AMZN", "Amazon.com Inc.", "NASDAQ", "USD", ("Amazon",)),
    ("META", "Meta Platforms Inc.", "NASDAQ", "USD", ("Facebook", "Meta")),
    ("TSLA", "Tesla Inc.", "NASDAQ", "USD", ("Tesla",)),
    ("AVGO", "Broadcom Inc.", "NASDAQ", "USD", ("Broadcom",)),
    ("COST", "Costco Wholesale Corporation", "NASDAQ", "USD", ("Costco",)),
    ("NFLX", "Netflix Inc.", "NASDAQ", "USD", ("Netflix",)),
    ("AMD", "Advanced Micro Devices", "NASDAQ", "USD", ("Advanced Micro Devices",)),
    ("INTC", "Intel Corporation", "NASDAQ", "USD", ("Intel",)),
    ("CSCO", "Cisco Systems", "NASDAQ", "USD", ("Cisco",)),
    ("ADBE", "Adobe Inc.", "NASDAQ", "USD", ("Adobe",)),
    ("PEP", "PepsiCo Inc.", "NASDAQ", "USD", ("Pepsi", "PepsiCo")),
    ("QCOM", "Qualcomm Inc.", "NASDAQ", "USD", ("Qualcomm",)),
    ("TXN", "Texas Instruments", "NASDAQ", "USD", ()),
    ("AMAT", "Applied Materials", "NASDAQ", "USD", ()),
    ("MU", "Micron Technology", "NASDAQ", "USD", ("Micron",)),
    ("JPM", "JPMorgan Chase & Co.", "NYSE", "USD", ("JPMorgan", "JP Morgan")),
    ("V", "Visa Inc.", "NYSE", "USD", ("Visa",)),
    ("MA", "Mastercard Inc.", "NYSE", "USD", ("Mastercard",)),
    ("JNJ", "Johnson & Johnson", "NYSE", "USD", ("Johnson and Johnson",)),
    ("WMT", "Walmart Inc.", "NYSE", "USD", ("Walmart",)),
    ("PG", "Procter & Gamble", "NYSE", "USD", ("Procter and Gamble", "P&G")),
    ("HD", "Home Depot", "NYSE", "USD", ("Home Depot",)),
    ("BAC", "Bank of America", "NYSE", "USD", ("Bank of America",)),
    ("XOM", "Exxon Mobil Corporation", "NYSE", "USD", ("Exxon", "ExxonMobil")),
    ("CVX", "Chevron Corporation", "NYSE", "USD", ("Chevron",)),
    ("KO", "Coca-Cola Company", "NYSE", "USD", ("Coca Cola", "Coca-Cola")),
    ("DIS", "Walt Disney Company", "NYSE", "USD", ("Disney",)),
    ("BA", "Boeing Company", "NYSE", "USD", ("Boeing",)),
    ("IBM", "International Business Machines", "NYSE", "USD", ("IBM",)),
    ("ORCL", "Oracle Corporation", "NYSE", "USD", ("Oracle",)),
    ("CRM", "Salesforce Inc.", "NYSE", "USD", ("Salesforce",)),
    ("UBER", "Uber Technologies", "NYSE", "USD", ("Uber",)),
    ("BRK.B", "Berkshire Hathaway Inc. Class B", "NYSE", "USD", ("Berkshire Hathaway",)),
    ("TSM", "Taiwan Semiconductor Manufacturing", "NYSE", "USD", ("TSMC", "Taiwan Semiconductor")),
    ("ASML", "ASML Holding NV", "NASDAQ", "USD", ("ASML",)),
    ("SHEL", "Shell plc", "NYSE", "USD", ("Shell",)),
    ("SAP", "SAP SE", "NYSE", "USD", ("SAP",)),
    ("SHOP", "Shopify Inc.", "NYSE", "USD", ("Shopify",)),
    ("BABA", "Alibaba Group Holding", "NYSE", "USD", ("Alibaba",)),
]

_CRYPTO_BASES: tuple[str, ...] = (
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "TRX", "DOT",
    "LINK", "LTC", "BCH", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "PEPE",
    "SHIB", "FIL", "ICP", "ETC", "XLM", "ALGO", "VET", "INJ", "TIA", "SEI",
    "JUP", "WIF", "TON", "ENA", "RENDER", "FET", "POL", "AAVE", "UNI", "MKR",
    "LDO", "STX", "CRV", "SAND", "MANA", "AXS", "GALA", "THETA", "FLOW",
    "EOS", "XTZ", "NEO", "IOTA", "DASH", "ZEC",
)

_CRYPTO_CROSS_PAIRS: tuple[str, ...] = (
    "ETHBTC", "SOLBTC", "SOLETH", "SOLBNB", "BNBETH", "BNBBTC", "XRPBTC",
    "ADABTC", "DOGEBTC", "LINKETH", "BTCUSDC", "ETHUSDC", "BTCFDUSD",
    "ETHFDUSD", "BNBEUR", "BTCTRY",
)


def seeded_instruments() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for symbol, name, exchange, aliases in _INDIA_EQUITIES:
        entries.append(_equity(symbol, name, "india", exchange, "INR", aliases))
    # Verified secondary listings of the same securities on BSE. They keep a
    # distinct canonical identity but are equivalent for name-only resolution.
    for symbol, name, _exchange, _aliases in _INDIA_EQUITIES[:3]:
        entries.append(_equity(symbol, name, "india", "BSE", "INR", ()))
    for symbol, name, exchange, currency, aliases in _GLOBAL_EQUITIES:
        entries.append(_equity(symbol, name, "global", exchange, currency, aliases))

    for base in _CRYPTO_BASES:
        pair = f"{base}USDT"
        primary_aliases: tuple[str, ...] = ()
        if base in _ASSET_NAMES:
            primary_aliases = (_ASSET_NAMES[base], base)
        entries.append(_crypto(pair, primary_aliases))
    for pair in _CRYPTO_CROSS_PAIRS:
        entries.append(_crypto(pair))
    return entries
