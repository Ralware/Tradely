# Tradely — Endpoint Inventory

Audited: 16 November 2026

The React application is the maintained frontend. In production, FastAPI serves `frontend/dist/index.html` at `/` and its assets at `/assets/*`; Vite continues to serve the frontend and proxy `/api` during development.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Application status and scope flags |
| `/api/providers/status` | GET | TradingView bridge health, purpose, and known delay/history limits |
| `/api/market/candles` | GET | Normalised OHLCV, source attribution, split-adjustment state, and freshness |
| `/api/scanner/watchlist` | GET | Daily deterministic strategy scan of the saved watchlist |
| `/api/instruments/search` | GET | Catalogue and live TradingView market search |
| `/api/instruments/resolve` | GET | Resolve a symbol, name or `instrument_id` to one canonical identity |
| `/api/instruments/catalogue/refresh` | POST | Import matching supported listings from live TradingView search (`q=...`) |
| `/api/instruments/{instrument_id}/capabilities` | GET | Supported intervals, quote availability, and provider limitations |
| `/api/instruments/{instrument_id}` | GET | Stored canonical instrument metadata |
| `/api/instruments/{instrument_id}/quote` | GET | Latest cached or refreshed TradingView quote |
| `/api/instruments/{instrument_id}/history` | GET | Canonical-instrument OHLCV history |
| `/api/instruments/{symbol}/analysis` | GET | Indicators, strategy signal, data-quality warnings, and completed candles |
| `/api/instruments/{symbol}/indicators` | GET | Per-bar indicator values for charts |
| `/api/instruments/{symbol}/technicals` | GET | Indicator-based technical summary |
| `/api/instruments/{symbol}/news` | GET | Explicit empty result; no news provider is bundled |
| `/api/backtests/trend-breakout` | POST | Daily deterministic research backtest |
| `/api/risk/position-size` | POST | Local position sizing calculation |
| `/api/signals/history` | GET | Saved signal audit history |
| `/api/watchlist` | GET, POST | Read and maintain local watchlist entries |
| `/api/watchlist/instruments/{instrument_id}` | DELETE | Remove a watchlist entry by canonical identity |
| `/api/watchlist/{market}/{symbol}` | DELETE | Remove a local watchlist entry by symbol |
| `/api/watchlist/quotes` | GET | Latest quotes for every watchlist instrument |
| `/api/market/quotes` | GET | Deduplicated quotes by `instrument_id`, `symbol`, or watchlist |
| `/api/market/quotes/stream` | GET | SSE feed replaying the shared TradingView quote cache |
| `/api/portfolio/transactions` | GET, POST | Local transaction ledger |
| `/api/portfolio/transactions/preview` | POST | Server-authoritative notional-to-quantity preview |
| `/api/portfolio/transactions/{transaction_id}` | DELETE | Delete a transaction when the remaining ledger stays valid |
| `/api/portfolio/summary` | GET | Currency-separated portfolio valuation summary |
| `/api/portfolio/positions` | GET | Local FIFO positions and realised P&L |
| `/api/portfolio/positions/{instrument_id}` | GET | Position detail, ledger history, and candles |

Removed routes: `/api/crypto/markets`, `/api/instruments/{symbol}/fundamentals`, `/api/instruments/{symbol}/events`, and `/api/us/issuers/{cik}/filings`.

Provider routing is deliberately single-source: every candle, quote, symbol-metadata, search and technical-rating request goes through `app.providers.tradingview` to the loopback bridge on `127.0.0.1:8010`, which imports the bundled unofficial TradingView library. Provider symbols use `EXCHANGE:SYMBOL` (for example `NSE:RELIANCE`, `NASDAQ:AAPL`, `BINANCE:BTCUSDT`). History is requested split-adjusted; the final incomplete candle is dropped and analysis/chart/history requests load the maximum bars TradingView exposes for that timeframe, with no fixed bar cap. Date-bounded backtests and historical transaction prices still use their selected window. Anonymous quotes are labelled delayed from TradingView's own `delay`/`update_mode` fields. News is not sourced; the endpoint returns a `count: 0` payload with an explicit note rather than fabricated articles. If the bridge is unavailable, requests fail clearly and cached quotes may be returned as `cached`/`stale`.
