"""Application module entry points.

The project keeps its logical implementation under app.* packages, while these
wrapper modules preserve the requested feature-oriented module layout without
breaking existing imports.
"""

from app.modules.analysis import *  # noqa: F401,F403
from app.modules.backtesting import *  # noqa: F401,F403
from app.modules.instruments import *  # noqa: F401,F403
from app.modules.market_data import *  # noqa: F401,F403
from app.modules.portfolio import *  # noqa: F401,F403
from app.modules.watchlist import *  # noqa: F401,F403

__all__ = [
    "Account",
    "AmbiguousInstrumentError",
    "InstrumentNotFoundError",
    "InstrumentResolutionError",
    "InstrumentResolver",
    "InstrumentUnavailableError",
    "Ledger",
    "Lot",
    "MarketDataProvider",
    "MarketService",
    "ProviderError",
    "TradingViewProvider",
    "WatchlistItem",
    "build_ledger",
    "build_technical_summary",
    "compute_indicators",
    "evaluate_trend_breakout",
    "run_trend_breakout_backtest",
    "validate_ohlcv",
]
