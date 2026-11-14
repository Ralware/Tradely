# Tradely Frontend Redesign Report

## Scope

The frontend was rebuilt as a dark, information-dense financial terminal while the FastAPI
backend, API contracts, financial formulas, strategy rules and thresholds were preserved.

- No existing route, indicator formula, strategy condition, risk rule or backtest calculation was
  changed.
- No trading algorithm was added to React. Every displayed indicator, signal, risk figure and
  backtest metric still comes from the backend.
- One additive read-only endpoint was approved and added: `GET /api/instruments/{symbol}/technicals`.
  It classifies indicator values that `compute_indicators` already produces and does not compute a
  second set of indicators.

## Interface Architecture

| Area | Implementation |
|---|---|
| Top bar | Brand, desktop navigation, global symbol search with market selector, selected quote, backend status, mobile navigation/watchlist triggers |
| Main workspace | Instrument form, asset heading and quote, supported timeframe selector, three technical gauges, oscillator and moving-average tables, price chart with overlay toggles, underline section tabs |
| Right rail | Watchlist with last/change/change %, selected instrument details, session statistics, performance tiles and sparkline |
| Mobile | Navigation and watchlist move into drawers below the `xl` breakpoint; gauges stack; tables scroll horizontally |
| Palette | Near-black background, charcoal panels, thin grey separators, red sells, green-teal buys, blue accent, muted neutral text |

`terminal-*` Tailwind tokens were retained with new values to limit churn. `terminal-accentSoft`
was added.

## Additive Endpoint

`GET /api/instruments/{symbol}/technicals`

Query parameters match `/analysis`: `market`, `exchange`, `interval`, `days`.

Response:

```json
{
  "symbol": "RELIANCE",
  "market": "india",
  "exchange": "NSE",
  "interval": "1d",
  "source": "Yahoo Finance (yfinance; unofficial)",
  "is_adjusted": true,
  "is_stale": false,
  "as_of": "2026-11-13T05:30:00",
  "close": 1339.699951171875,
  "oscillators": [{ "name": "...", "field": "...", "value": 70.83, "action": "Sell" }],
  "moving_averages": [{ "name": "...", "field": "...", "value": 1308.66, "action": "Buy" }],
  "summary": {
    "oscillators": { "action": "Neutral", "score": 0, "sell": 2, "neutral": 4, "buy": 2 },
    "moving_averages": { "action": "Strong Buy", "score": 1, "sell": 0, "neutral": 0, "buy": 7 },
    "overall": { "action": "Strong Buy", "score": 0.5, "sell": 2, "neutral": 4, "buy": 9 }
  },
  "method": "Conventional threshold classification of backend indicator values..."
}
```

### Oscillator Rules

| Indicator | Buy | Sell | Neutral |
|---|---|---|---|
| RSI (14) | `< 30` | `> 70` | otherwise |
| Stochastic RSI (14) | `< 20` | `> 80` | otherwise |
| Commodity Channel Index (20) | `< -100` | `> 100` | otherwise |
| Average Directional Index (14) | — | — | always Neutral (strength only) |
| MACD (12, 26) | above signal | below signal | equal or missing |
| Money Flow Index (14) | `< 20` | `> 80` | otherwise |
| Chaikin Money Flow (20) | `> 0` | `< 0` | otherwise |
| Bollinger Bands (20, 2) | close below lower band | close above upper band | inside bands |
| VWAP (Session) | close above VWAP | close below VWAP | row omitted when VWAP is unavailable |

### Moving-Average Rules

Close above the average is Buy; close below is Sell; equality or missing data is Neutral.
Rows: EMA 9, SMA 20, EMA 20, SMA 50, EMA 50, SMA 200, EMA 200.

### Assessment

`score = (buy - sell) / total`, used only to position the gauge needle.

- Strong Buy: buy > sell and buy > neutral and `buy >= 2 * max(sell, 1)`
- Buy: buy > sell and buy > neutral
- Strong Sell: sell > buy and sell > neutral and `sell >= 2 * max(buy, 1)`
- Sell: sell > buy and sell > neutral
- Neutral: otherwise

The summary is a conventional technical reading, not the Tradely trend-breakout strategy.

## Supported Timeframes

Only intervals the backend can actually return are offered.

| Market | Intervals | Default history |
|---|---|---|
| Equities | `1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1wk`, `1mo` | 5 / 30 / 30 / 30 / 365 / 500 / 1825 / 3650 days |
| Crypto | `1m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`, `1w`, `1M` | 5 / 30 / 30 / 30 / 365 / 365 / 365 / 500 / 1825 / 3650 days |

Yahoo Finance rejects `2h` for equities, so it is not shown there. Binance supports `2h` and `4h`,
so both are shown for crypto.

## Derived Display Values

These are presentation-only values derived from backend candles; they are not new indicators or
signals.

| Value | Source |
|---|---|
| Watchlist last / change / change % | Last two closes of a `days=7` daily candle response |
| Top-bar and sidebar quote | Last two closes of a `days=7` daily candle response, so the session change is identical at every chart timeframe |
| Performance tiles (1W/1M/3M/6M/YTD/1Y) | Percentage difference between the latest daily close and the close at or before the requested cutoff |
| Sparkline | Last 120 daily closes |
| Drawdown curve in backtesting | Equity points already returned by the backend; the headline max drawdown remains the backend value |
| Chart overlay and pane toggles | Select which backend series are drawn; no values are recomputed |

Crypto-specific metrics such as open interest, liquidations and funding rates are not displayed
because the backend does not provide them. Reference rows absent from the backend (Stochastic %K,
Awesome Oscillator, Momentum, Williams %R, Bull Bear Power, Ultimate Oscillator) are omitted rather
than invented.

## Preserved Features

Dashboard, Markets (India/Global/Crypto), Stock Analysis, Crypto Analysis, Portfolio FIFO ledger,
Backtesting, Settings, news, corporate events, SEC filings, risk sizing, indicator panels, charts,
scanner and watchlist all remain available. Every visible control performs a real action. Loading,
error and empty states are present for every request.

A small `tradely:watchlist-changed` browser event keeps the rail, drawers and page lists in sync
after add/remove operations.

## Verification

- Backend tests: `33 passed` (`.\.venv\Scripts\python.exe -m pytest`).
- TypeScript: `npx tsc -b` passes with no errors.
- Production build: `npm run build` passes (109 modules).
- Live browser checks against `127.0.0.1:5173` and `127.0.0.1:8000`:
  - RELIANCE `1d`: 8 oscillators, 7 moving averages, overall Strong Buy, counts `2 / 4 / 9`.
  - RELIANCE `1h`: 9 oscillators (session VWAP present), overall counts `3 / 6 / 7`.
  - BTCUSDT `1d` and `4h`: gauges, tables and timeframe switching work.
  - Watchlist add/remove updates the rail automatically.
  - Global search for AAPL opens the Global workspace and exposes the Filings tab.
  - Fundamentals load for AAPL, SEC filings validate an empty CIK, and position sizing returns the
    backend risk budget, quantity and planned loss for valid entry/stop inputs.
  - Dashboard, Markets, Portfolio, Backtesting, Settings and the 404 route render without console
    errors.
  - Mobile-width navigation and watchlist drawers open and close.

## Known Limits

- Yahoo intraday history can be shorter than requested; the UI reports the bars actually returned.
- A 1-year performance tile can be unavailable when the returned daily history does not reach the
  cutoff; it then shows `—`.
- Backtest limitations remain exactly as documented by the backend response.
- The summary endpoint reuses the existing candle cache and does not write signal-audit rows.
